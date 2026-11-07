"""Action-handler implementations extracted from ``agent.py``.

The ``DigitalBeing`` facade remains the stable public surface. The one legacy
class-qualified deferral call is injected by that facade, preserving late
binding without a circular import. Knowledge persistence stays on ``self``.
"""

import random
from typing import Dict, Optional

from config.simulation_config import LR_CONFIG
from src.core.buffered_logger import get_logger
from src.memory.knowledge_quality import STOP_WORDS, normalize_concept_name


def _act_explore_impl(self, target=None) -> Dict:
    """Исследование как работа, а не как счётчик.

        Раньше ``act("explore")`` попадал в тип «default»: энергия
        списывалась, строка возвращалась, мир не менялся. Отсюда бралось
        зацикливание — агенту не за что было зацепиться, чтобы сменить
        действие.

        Теперь исследование выбирает конкретную тему и прогоняет её через
        мышление: появляется гипотеза, запись в ментальных моделях или
        ответ из сети. Это наблюдаемый результат.
        """
    target = str(target).strip() if target is not None else self._pick_exploration_target()
    if not target or not self._is_learnable(target):
        return {
            "target": "",
            "text": "Ответ: исследовать нечего — все концепции уверены",
        }

    try:
        thought = self.think(f"вопрос: {target}")
    except Exception as exc:
        get_logger().log(f"[EXPLORE] ошибка мышления по '{target}': {exc}")
        return {
            "target": target,
            "text": f"Ответ: попыталась изучить '{target}', но не смогла: {exc}",
        }

    short = str(thought).replace("\n", " ")[:100]
    return {
        "target": target,
        "thought": thought,
        "text": f"Ответ: изучила '{target}' — {short}",
    }


def _act_decompose_impl(self, target=None) -> Dict:
    """Разбирает слабую концепцию на под-вопросы и сохраняет их.

        Декомпозиция — работа: она создаёт новые темы, с которыми агент
        столкнётся в следующих циклах. Раньше под-вопросы вычислялись,
        попадали в текст ответа и терялись: мир не менялся, действие
        считалось бесплодным, попадало в тупики — и при этом служило
        запасным вариантом выхода из тупика. Агент тратил циклы на
        действие, которое по построению ничего не делало (в замере —
        115–162 выбора за 500 циклов).
        """
    target = str(target).strip() if target is not None else self._pick_decomposable_target()
    if not target or not self._is_learnable(target):
        return {"target": "", "text": "Ответ: разбирать нечего"}

    try:
        parts = self._decompose_query(target) or []
    except Exception as exc:
        get_logger().log(f"[DECOMPOSE] ошибка для '{target}': {exc}")
        parts = []

    if not parts:
        return {
            "target": target,
            "text": f"Ответ: '{target}' не разбивается на части",
        }

    queued = self._queue_sub_questions(parts)
    suffix = (
        f"; в очередь вопросов +{queued}" if queued else ""
    )
    return {
        "target": target,
        "parts": list(parts)[:5],
        "queued": queued,
        "text": (
            f"Ответ: разобрала '{target}' на {len(parts)} частей: "
            + "; ".join(str(p) for p in parts[:3])
            + suffix
        ),
    }


def _queue_sub_questions_impl(self, parts) -> int:
    """Ставит под-вопросы в очередь открытых вопросов.

        Ограничения те же, что в ``thinking_pipeline``: не больше
        ``OPEN_QUESTIONS_MAX_UNANSWERED`` неотвеченных, по одной попытке
        размышления на под-вопрос и без дублей. Иначе декомпозиция
        вытеснила бы всё остальное из очереди.

        Returns:
            Сколько вопросов реально добавлено.
        """
    ask = getattr(self, "ask_user", None)
    if not callable(ask):
        return 0
    limit = int(getattr(LR_CONFIG, "OPEN_QUESTIONS_MAX_UNANSWERED", 3) or 0)
    try:
        existing = self.get_open_questions()
    except Exception:
        existing = []
    unanswered = sum(1 for q in existing if not q.get("answered"))
    known = {
        str(q.get("text", "")).strip().lower() for q in existing
    }

    added = 0
    for part in parts:
        if unanswered + added >= limit:
            break
        text = str(part or "").strip()
        key = text.lower()
        if not text or key in known or "стратегия=" in key:
            continue
        try:
            result = ask(
                text, source="decomposition", max_explorations=1
            )
        except Exception as exc:
            get_logger().log(
                f"[DECOMPOSE] не удалось поставить '{text[:40]}': {exc}"
            )
            continue
        if result.get("status") == "queued":
            added += 1
            known.add(key)
    return added


def _act_synthesize_impl(self, target=None) -> Dict:
    """Синтез: попытка собрать определение из уже известных связей.

        Использует ментальные модели. Если определение уже есть —
        усиливает уверенность через новый опыт.
        """
    target = target if target is not None else self._pick_exploration_target()
    if not target or not self._is_learnable(target):
        return {"target": "", "text": "Ответ: синтезировать нечего"}

    # Сначала — связи, подкреплённые свидетельствами (вес выше порога):
    # их укрепляет сон, когда видит одну концепцию в формулировке
    # другой. Только если таких нет, смотрим широкий обход графа.
    #
    # Раньше здесь стоял вызов с именем ``max_depth``, а параметр
    # называется ``max_distance``: TypeError молча глотался, и синтез
    # всегда отвечал «нет связанных концепций». Действие при этом
    # считалось выполненным.
    names: list = []
    try:
        node = self.mental_models.concepts.get(target)
        if node is not None:
            names = [
                item["concept"]
                for item in node.get_related_concepts(0.3)
                if item.get("concept") in self.mental_models.concepts
            ][:3]
    except Exception as exc:
        get_logger().log(f"[SYNTHESIS] ошибка связей '{target}': {exc}")
        names = []

    if not names:
        try:
            related = self.mental_models.find_related_concepts(
                target, max_distance=2
            )
        except Exception:
            related = []
        # find_related_concepts возвращает ConceptNode, а не словари:
        # второй слой той же ошибки — оба вида обращений надо уметь.
        for item in related[:3]:
            name = (
                item.get("concept")
                if isinstance(item, dict)
                else getattr(item, "name", None)
            )
            if name:
                names.append(name)

    if not names:
        return {
            "target": target,
            "text": f"Ответ: для '{target}' нет связанных концепций",
        }

    hypothesis = (
        f"'{target}' можно понять через: " + ", ".join(str(n) for n in names)
    )
    try:
        self.mental_models.encounter_concept(
            target,
            f"синтез_цикл_{self.cycle_count}",
            hypothesis,
            evidence_kind="hypothesis", source="self:synthesis",
        )
    except Exception as exc:
        get_logger().log(f"[SYNTHESIS] не удалось записать: {exc}")

    return {
        "target": target,
        "text": f"Ответ: синтезировала '{target}' через {names}",
    }


def _act_reflect_impl(self) -> Dict:
    """Рефлексия как действие: обзор собственных паттернов."""
    try:
        reflection = self.reflect()
    except Exception as exc:
        get_logger().log(f"[REFLECTION] ошибка: {exc}")
        return {"text": f"Ответ: рефлексия не удалась: {exc}"}

    patterns = reflection.get("patterns") or []
    if not patterns:
        return {"text": "Ответ: рефлексия — новых паттернов нет"}
    first = patterns[0]
    description = str(first.get("description", ""))[:80]
    return {
        "text": (
            f"Ответ: заметила паттерн — {description} "
            f"(уверенность {float(first.get('confidence', 0)):.0%})"
        )
    }


def _defer_ask_intention_impl(self, target: str) -> None:
    """Пауза повторного выбора вопроса по теме (backoff 5..50).

        «Нетерпеливый вопрос» (TICKET-2) и верификация 2026-11-06
        (V-1): отказ — «отложен» или «не переспрашиваю» — не должен
        выбираться заново каждый цикл. Без записи здесь намерение
        крутилось вхолостую: 214 из 309 циклов живого прогона ушли на
        выбор-отказ ask_user по одной теме, сжигая АТФ тела и загоняя
        существо обратно в глубокий отдых.
        """
    deferrals: Dict[tuple, tuple] = {}
    saved_deferrals = getattr(self, "_deferred_intentions", None)
    if isinstance(saved_deferrals, dict):
        deferrals = saved_deferrals
    self._deferred_intentions = deferrals
    key = ("ask_user", target)
    _, count = deferrals.get(key, (0, 0))
    count += 1
    backoff = min(5 * (2 ** (count - 1)), 50)
    deferrals[key] = (self.cycle_count + backoff, count)


def _act_ask_user_impl(self, target=None, *, DigitalBeing) -> Dict:
    """Спросить человека о том, что агенту непонятно.

        До этой проводки действие ``ask_user`` (его предлагала мотивация
        как «ask_question») доходило до ``act()`` и молча заканчивалось:
        подсистема ``UserInteraction`` умеет задавать вопросы, публикует
        события, окно их показывает — но никто не вызывал её из петли.
        Агент «хотела спросить» и не спрашивал.

        Вопрос задаётся только по реальной нужде: берётся тема, в которой
        агент не уверена. Спрашивать о том, что уже знает, — шум.
        """
    interaction = getattr(self, "user_interaction", None)
    if interaction is None:
        return {"text": "Ответ: спросить некого — нет связи с человеком"}

    if (
        target is not None
        and not self._recently_explained_by_user(target)
        and str(target).strip().lower() in self._META_TOPIC_WORDS
    ):
        target = None

    target = target if target is not None else self._pick_exploration_target()
    if not target or not self._is_learnable(target):
        return {"text": "Ответ: не о чем спрашивать — всё понятно"}

    if self._recently_explained_by_user(target):
        # V-1 (верификация 2026-11-06): отказ «не переспрашиваю»
        # тоже гасит намерение — иначе тема выбиралась каждый цикл.
        # через класс: act() работает и на лёгких тестовых объектах
        DigitalBeing._defer_ask_intention(self, target)
        return {
            "text": (
                f"Ответ: человек недавно объяснил '{target}' — "
                f"не переспрашиваю"
            )
        }

    question = (
        f"Я разбираюсь с темой «{target}» и пока не уверена, "
        f"что понимаю её правильно. Можешь объяснить своими словами?"
    )
    try:
        result = interaction.ask_user(
            question=question,
            context=f"самостоятельный вопрос по теме: {target}",
            cycle=self.cycle_count,
        )
    except Exception as exc:
        get_logger().log(f"[ASK] не удалось спросить: {exc}")
        return {"text": f"Ответ: хотела спросить про '{target}', но не смогла"}

    if result.get("status") != "queued":
        # Лимит вопросов или пауза — это нормально, не ошибка.
        reason = result.get("reason", "не сейчас")
        # «Нетерпеливый вопрос» (TICKET-2): отложенное намерение не
        # должно выбираться заново каждый цикл. Экспоненциальный
        # backoff: 5, 10, 20, 40, максимум 50 циклов тишины — тема
        # жива, но не крутится вхолостую.
        # через класс: act() работает и на лёгких тестовых объектах
        DigitalBeing._defer_ask_intention(self, target)
        return {
            "target": target,
            "text": f"Ответ: вопрос про '{target}' отложен ({reason})",
        }

    # Вопрос дошёл — backoff по этой теме сбрасывается.
    cleared = getattr(self, "_deferred_intentions", None)
    if cleared:
        cleared.pop(("ask_user", target), None)
    self._record_will("questions_asked", target, "самостоятельный вопрос")
    return {
        "target": target,
        "text": f"Ответ: спросила человека про '{target}'",
    }


def _act_communicate_impl(self) -> Dict:
    """Рассказать человеку что-то, что агент счёл важным.

        Действие ``communicate`` (мотивация: «поделиться знанием»,
        «ответить пользователю») раньше тоже ничего не делало.
        """
    interaction = getattr(self, "user_interaction", None)
    if interaction is None:
        return {"text": "Ответ: рассказать некому — нет связи с человеком"}

    message = self._compose_share_message(record=True)
    if not message:
        return {"text": "Ответ: нечего рассказать — нет новостей"}

    try:
        interaction.send_message(
            content=message,
            msg_type="statement",
            tone="casual",
            urgency=0.4,
            context="делюсь тем, что узнала",
            cycle=self.cycle_count,
        )
    except Exception as exc:
        get_logger().log(f"[COMMUNICATE] не удалось отправить: {exc}")
        return {"text": f"Ответ: хотела рассказать, но не смогла: {exc}"}

    self._record_will("messages_sent", "share", "делюсь знанием")
    self._last_share_cycle = self.cycle_count
    return {"text": f"Ответ: рассказала человеку: {message[:60]}"}


def _compose_share_message_impl(self, record: bool = False) -> str:
    """Текст сообщения: о самом свежем или самом слабом знании.

        Берём то, что агент недавно узнал и в чём уже уверен: делиться
        догадкой, которую сам не проверил, — нечестно.

        «Собеседник-4»: уже рассказанное не повторяется (_shared_topics).
        При ``record=True`` выбранная тема помечается рассказанной; проверка
        без записи (гейт кандидатов в social_scan) не сжигает тему.
        """
    concepts = getattr(self.mental_models, "concepts", None)
    if not isinstance(concepts, dict) or not concepts:
        return ""

    shared = getattr(self, "_shared_topics", None)
    if not isinstance(shared, dict):
        shared = {}
        self._shared_topics = shared

    # Предпочитаем концепции с собственной формулировкой.
    candidates = [
        (name, node)
        for name, node in concepts.items()
        if len(str(getattr(node, "definition_hypothesis", "") or "")) > 10
        and not name.startswith(("_", "убеждение_"))
        and name not in shared
    ]
    if not candidates:
        return ""

    name, node = max(
        candidates,
        key=lambda item: getattr(item[1], "last_updated", None) or 0,
        default=(None, None),
    )
    if not name:
        return ""
    if record:
        self._remember_shared_topic(name)
    definition = str(getattr(node, "definition_hypothesis", ""))[:200]
    return f"Я разобралась с темой «{name}»: {definition}"


def _remember_shared_topic_impl(self, topic: str) -> None:
    """Запомнить, что тему уже рассказали человеку (шапка 50)."""
    shared = getattr(self, "_shared_topics", None)
    if not isinstance(shared, dict):
        shared = {}
        self._shared_topics = shared
    shared[str(topic)] = int(self.cycle_count)
    if len(shared) > 50:
        for old_topic, _stamp in sorted(
            shared.items(), key=lambda item: item[1]
        )[: len(shared) - 50]:
            shared.pop(old_topic, None)


def _act_web_search_impl(self, target: Optional[str] = None) -> Dict:
    """Найти в сети тему намерения, а при его отсутствии — новую тему.

        Действие ``web_search`` предлагалось мотивацией, но не
        исполнялось. При этом ``WebSearcher`` уже был подключён к
        мышлению — не хватало только вызова из петли.

        «Охота-1»: промах по теме оставляет след (кулдаун повторной
        охоты, не сериализуется — сон стирает след), а удачный заход на
        соседнюю статью — след добычи: новая неуверенная концепция в
        ментальных моделях.
        """
    searcher = getattr(self, "web_searcher", None)
    if searcher is None or not getattr(searcher, "is_enabled", False):
        return {
            "text": "Ответ: поиск в сети недоступен или выключен"
        }

    # K13: выбранное намерение имеет приоритет над селектором новизны.
    # Случайная/слабая тема допустима только для поиска без намерения.
    target = str(target).strip() if target is not None else self._pick_exploration_target()
    if not target:
        return {"text": "Ответ: искать нечего — нет темы"}

    # Кулдаун промаха: след неудачной охоты ещё свеж — не трогаем.
    misses = getattr(self, "_hunt_misses", None)
    if not isinstance(misses, dict):
        misses = self._hunt_misses = {}
    cooldown = int(getattr(LR_CONFIG, "HUNT_MISS_COOLDOWN_CYCLES", 200) or 0)
    last_miss = misses.get(target)
    if (
        cooldown > 0
        and last_miss is not None
        and (self.cycle_count - last_miss) < cooldown
    ):
        return {
            "target": target,
            "text": (
                f"Ответ: про '{target}' уже охотилась и промахнулась — "
                f"след ещё свеж"
            ),
        }

    try:
        result = searcher.search(target)
    except Exception as exc:
        get_logger().log(f"[WEB] поиск упал: {exc}")
        return {
            "target": target,
            "text": f"Ответ: поиск по '{target}' не удался",
        }

    if not result.get("found"):
        misses[target] = self.cycle_count
        reason = result.get("error") or "не найдено"
        return {
            "target": target,
            "text": f"Ответ: в сети про '{target}' ничего ({reason})",
        }

    extract = str(result.get("extract") or "")
    title = str(result.get("title") or target)
    if not extract:
        misses[target] = self.cycle_count
        return {
            "target": target,
            "text": f"Ответ: нашла '{title}', но без содержания",
        }

    # Сохраняем как знание: без записи поиск ничего не изменил бы.
    try:
        from src.memory.knowledge_quality import check_entry

        if check_entry(target, extract):
            misses[target] = self.cycle_count
            return {
                "target": target,
                "text": f"Ответ: результат по '{target}' отклонён как слабый",
            }
        self.knowledge_base[target] = extract
        self._known_definitions[target] = extract
        self._save_knowledge_base()
    except Exception as exc:
        get_logger().log(f"[WEB] не удалось сохранить: {exc}")
        return {
            "target": target,
            "text": f"Ответ: нашла '{title}', но не сохранила",
        }

    # Добыча есть — след промаха по этой теме смываем.
    misses.pop(target, None)

    self._record_will("web_searches", target, f"нашла в сети: {title}")

    # «Охота-1»: след добычи. Полнотекстовый поиск мог привести не к
    # той концепции, что искали, а к соседней — она становится новой
    # неуверенной темой. Фильтры те же, что у обычной встречи с
    # неизвестным: не служебное слово, не метатема, достаточной длины.
    trail = None
    concept = normalize_concept_name(title)
    if concept and concept != normalize_concept_name(target):
        already_known = concept in getattr(self.mental_models, "concepts", {})
        if (
            not already_known
            and len(concept) >= 3
            and concept not in STOP_WORDS
            and self._is_learnable(concept)
            and not self._is_meta_topic(concept)
        ):
            try:
                self.mental_models.encounter_concept(
                    concept_name=concept,
                    context=f"след_охоты_цикл_{self.cycle_count}",
                    outcome=f"Встретила по следам '{target}'",
                    valence=0.0,
                )
                trail = concept
                get_logger().log(f"[HUNT] след добычи: '{target}' → '{concept}'")
            except Exception as exc:
                get_logger().log(f"[HUNT] след не записан: {exc}")

    text = f"Ответ: нашла в сети «{title}» про '{target}'"
    if trail:
        text += f"; по следам — новая тема '{trail}'"
    return {
        "target": target,
        "text": text,
    }


def _pick_news_topic_impl(self) -> Optional[str]:
    """Тема новостей — то, что существо сейчас занимает.

        Активная цель; если её нет — случайная известная концепция:
        читают и о знакомом, не только о насущном. Поиск идёт по фразе
        целиком — Викиновости сами разберут слова.
        """
    goal = getattr(self, "active_goal", None)
    if isinstance(goal, dict):
        title = str(goal.get("title") or "").strip()
        if title:
            return title[:60]
    concepts = getattr(getattr(self, "mental_models", None), "concepts", None)
    if isinstance(concepts, dict) and concepts:
        learnable = [n for n in concepts if self._is_learnable(n)]
        if learnable:
            return random.choice(learnable)[:60]
    return None


def _act_read_news_impl(self) -> Dict:
    """Прочитать новости по тому, что занимает.

        «Источники-2»: окно в «сегодня». Новость — впечатление, а не
        знание: в knowledge_base она не идёт (определение вечно, новость
        — про сейчас); её след — эпизод дневника и запись в реестре
        воли. Кулдаун по теме (читал или не нашлось — одинаково) живёт
        только в памяти: сон стирает его.
        """
    searcher = getattr(self, "web_searcher", None)
    if searcher is None or not getattr(searcher, "is_enabled", False):
        return {"text": "Ответ: новости недоступны — поиск выключен"}

    topic = self._pick_news_topic()
    if not topic:
        return {"text": "Ответ: новости не о чем читать — нет темы"}

    reads = getattr(self, "_news_reads", None)
    if not isinstance(reads, dict):
        reads = self._news_reads = {}
    cooldown = int(getattr(LR_CONFIG, "NEWS_READ_COOLDOWN_CYCLES", 300) or 0)
    last_read = reads.get(topic)
    if (
        cooldown > 0
        and last_read is not None
        and (self.cycle_count - last_read) < cooldown
    ):
        return {
            "target": topic,
            "text": (
                f"Ответ: новости про '{topic}' недавно проверяла — "
                f"вернусь позже"
            ),
        }

    try:
        result = searcher.search_news(topic)
    except Exception as exc:
        get_logger().log(f"[NEWS] чтение упало: {exc}")
        return {
            "target": topic,
            "text": f"Ответ: новости по '{topic}' не удались",
        }

    if not result.get("found"):
        reads[topic] = self.cycle_count
        return {
            "target": topic,
            "text": f"Ответ: свежих новостей про '{topic}' не нашлось",
        }

    reads[topic] = self.cycle_count
    title = str(result.get("title") or topic)
    extract = str(result.get("extract") or "")
    snippet = extract[:200]
    if len(extract) > 200:
        snippet = snippet.rsplit(" ", 1)[0] + "…"
    self._record_will("news_reads", topic, f"прочитала новость: {title}")
    return {
        "target": topic,
        "text": (
            f"Ответ: прочитала новость про '{topic}': «{title}». "
            f"{snippet}"
        ),
    }


def _act_browse_web_impl(self) -> Dict:
    """Погулять по открытому интернету по тому, что занимает.

        «Интернет-1»: компас (search_web) даёт краткий ответ и ссылки,
        затем существо читает одну страницу сама (open_page). Страница —
        впечатление, не знание: в knowledge_base она не идёт (веб шумный,
        определениям там не место); её след — эпизод дневника и волевой
        акт ``web_browses``. Кулдаун по теме живёт только в памяти:
        сон стирает его.
        """
    searcher = getattr(self, "web_searcher", None)
    if searcher is None or not getattr(searcher, "is_enabled", False):
        return {"text": "Ответ: интернет недоступен — поиск выключен"}

    topic = self._pick_news_topic()
    if not topic:
        return {"text": "Ответ: гулять по интернету не о чем — нет темы"}

    browses = getattr(self, "_web_browses", None)
    if not isinstance(browses, dict):
        browses = self._web_browses = {}
    cooldown = int(getattr(LR_CONFIG, "WEB_BROWSE_COOLDOWN_CYCLES", 300) or 0)
    last_browse = browses.get(topic)
    if (
        cooldown > 0
        and last_browse is not None
        and (self.cycle_count - last_browse) < cooldown
    ):
        return {
            "target": topic,
            "text": (
                f"Ответ: интернет про '{topic}' недавно обошла — "
                f"вернусь позже"
            ),
        }

    try:
        compass = searcher.search_web(topic)
    except Exception as exc:
        get_logger().log(f"[WEB] компас упал: {exc}")
        return {
            "target": topic,
            "text": f"Ответ: интернет по '{topic}' не отозвался",
        }

    if not compass.get("found"):
        browses[topic] = self.cycle_count
        return {
            "target": topic,
            "text": f"Ответ: интернет про '{topic}' ничего не подсказал",
        }

    # Куда пойти: ссылка мгновенного ответа, иначе первая связанная.
    destination = str(compass.get("url") or "").strip()
    if not destination:
        for link in compass.get("related") or []:
            candidate = str(link.get("url") or "").strip()
            if candidate:
                destination = candidate
                break

    if not destination:
        browses[topic] = self.cycle_count
        return {
            "target": topic,
            "text": f"Ответ: компас по '{topic}' не дал адреса",
        }

    try:
        page = searcher.open_page(destination)
    except Exception as exc:
        get_logger().log(f"[WEB] чтение страницы упало: {exc}")
        return {
            "target": topic,
            "text": f"Ответ: страница по '{topic}' не открылась",
        }

    browses[topic] = self.cycle_count
    if not page.get("found"):
        return {
            "target": topic,
            "text": (
                f"Ответ: страница про '{topic}' не читается "
                f"({page.get('error') or 'пусто'})"
            ),
        }

    title = str(page.get("title") or destination)
    extract = str(page.get("extract") or "")
    snippet = extract[:200]
    if len(extract) > 200:
        snippet = snippet.rsplit(" ", 1)[0] + "…"
    self._record_will(
        "web_browses", topic, f"погуляла по интернету: {title}"
    )
    return {
        "target": topic,
        "text": (
            f"Ответ: погуляла по интернету про '{topic}': «{title}». "
            f"{snippet}"
        ),
    }


def _act_hypothesis_impl(self) -> Dict:
    """Выдвинуть гипотезу о теме, в которой агент не уверена.

        Мотивация предлагает это действие («Понять: {concept}»), но
        раньше оно уходило в «default»: агент «выдвигал гипотезу» и
        ничего не происходило. Гипотеза — это запись в ментальной модели,
        то есть наблюдаемое изменение.
        """
    target = self._pick_exploration_target()
    if not target:
        return {"text": "Ответ: гипотезу выдвигать не о чем"}

    try:
        hypothesis = self._generate_hypothesis(target)
    except Exception as exc:
        get_logger().log(f"[HYPOTHESIS] ошибка для '{target}': {exc}")
        hypothesis = None

    if not hypothesis:
        return {
            "target": target,
            "text": f"Ответ: про '{target}' пока не из чего строить гипотезу",
        }

    text = str(hypothesis.get("text") or "")
    confidence = float(hypothesis.get("confidence") or 0.0)
    try:
        self.mental_models.encounter_concept(
            target,
            f"гипотеза_цикл_{self.cycle_count}",
            text[:80],
            evidence_kind="hypothesis", source="self:hypothesis",
        )
    except Exception as exc:
        get_logger().log(f"[HYPOTHESIS] не удалось записать: {exc}")

    return {
        "target": target,
        "text": (
            f"Ответ: гипотеза о '{target}' — {text[:70]} "
            f"(уверенность {confidence:.0%})"
        ),
    }


def _act_set_own_goal_impl(self) -> Dict:
    """Поставить себе цель по своей воле.

        Мотивация предлагает «Поставить свою цель» (autonomy). Раньше
        действие ничего не делало. Цель — наблюдаемое изменение: она
        появляется в списке и начинает влиять на жизнь.
        """
    motivation = getattr(self, "motivation_system", None)
    play_need = motivation.needs.get("play") if motivation is not None else None
    if play_need is not None and play_need.is_pressing():
        activity = random.choice(["play", "creative_act", "draw", "compose_music"])
        title = {"play": "Сыграть партию",
                 "creative_act": "Создать текстовую композицию",
                 "draw": "Нарисовать картину",
                 "compose_music": "Сочинить мелодию"}[activity]
        if any(g.get("title") == title and g.get("status") != "completed" for g in self.goals):
            return {"text": f"Ответ: дело '{title}' уже есть"}
        goal_id = self.set_goal(title, difficulty=1)
        from src.cognition.activity_goals import attach_activity

        attach_activity(self, goal_id, {"source": "self", "need": "play", "action_hint": activity})
        self._record_will("goals_set", title, f"своё дело #{goal_id}")
        return {"text": f"Ответ: выбрала дело '{title}' (#{goal_id})"}
    target = self._pick_exploration_target()
    if not target or not self._is_meaningful_topic(target):
        return {"text": "Ответ: свою цель ставить не из чего"}

    title = f"Понять: {target}"
    # Не дублируем уже существующую цель. TICKET-8: сравнение по
    # нормализованному тексту (нижний регистр, сжатые пробелы) —
    # «Понять:  истина» и «Понять: истина» — одна цель.
    normalized_title = " ".join(title.lower().split())
    for goal in getattr(self, "goals", []) or []:
        existing = " ".join(str(goal.get("title", "")).lower().split())
        if existing == normalized_title:
            return {
                "target": target,
                "text": f"Ответ: цель '{title}' уже есть",
            }

    try:
        goal_id = self.set_goal(title, difficulty=1)
    except Exception as exc:
        get_logger().log(f"[OWN_GOAL] не удалось поставить цель: {exc}")
        return {
            "target": target,
            "text": f"Ответ: хотела поставить цель '{title}', но не смогла",
        }

    self._record_will("goals_set", target, f"своя цель #{goal_id}")
    return {
        "target": target,
        "text": f"Ответ: поставила себе цель '{title}' (#{goal_id})",
    }


def _record_will_impl(self, will_type: str, topic: str, reason: str) -> None:
    """Записывает действие в журнал воли, если он есть.

        Журнал переживает перезапуск и служит доказательством эффекта:
        без записи дельта мира не увидела бы, что сообщение отправлено
        или вопрос задан.
        """
    registry = getattr(self, "will_registry", None)
    if registry is None:
        return
    try:
        registry.record(
            will_type, topic, reason,
            outcome="executed", cycle=self.cycle_count,
        )
    except Exception:
        pass
