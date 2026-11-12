"""Candidate-selection helpers and shared selection tables from ``agent.py``.

Cross-contour calls stay on the facade object. Emotional bias is deliberately
not imported here; it continues to call ``self._normalize_action`` from the core.
"""

from typing import Dict, List, Optional

from config.simulation_config import LR_CONFIG


_META_TOPIC_WORDS = frozenset(
    {
        "вопрос",
        "вопросы",
        "тема",
        "темы",
        "ответ",
        "ответы",
        "сообщение",
        "сообщения",
        "диалог",
        "диалоги",
        "разговор",
        "разговоры",
    }
)

_NOISE_TOPIC_WORDS = frozenset(
    {
        "я",
        "ты",
        "мы",
        "вы",
        "он",
        "она",
        "оно",
        "они",
        "это",
    }
)

_METHOD_VALUE_MAP = {
    "explore": "Исследование",
    "decomposition": "Анализ",
    "synthesis": "Синтез",
    "know_answer": "Знание",
    "ask_user": "Диалог",
    "create_draft": "Творчество",
    "draw": "Творчество",
    "compose_music": "Творчество",
    "play": "Игра",
    "read_news": "Исследование",
    "browse_web": "Исследование",
}


def _social_candidates_impl(self, cycle: int) -> List[Dict]:
    """Кандидаты на общение: спросить, рассказать, поискать.

    Почему это отдельный источник, а не только мотивация: у общения
    есть собственные наблюдаемые признаки, не сводимые к уровню
    потребности. Потребность «связь» может быть удовлетворена
    недавним разговором, но незакрытый вопрос всё равно стоит того,
    чтобы попросить помощи. Здесь общение встроено в выбор напрямую —
    по реальным признакам, а не по декларации.

    Признаки честные и проверяемые:
    * есть открытый вопрос, который агент давно не может закрыть сам;
    * агент давно ничего не говорил человеку;
    * есть тема без собственной формулировки, а поиск доступен.
    """
    candidates: List[Dict] = []
    interaction = getattr(self, "user_interaction", None)

    # 1. Незакрытый вопрос — попросить помощи у человека.
    # Предлагаем только если вопрос РАЗРЕШЕНО задать: иначе кандидат
    # выигрывает арбитраж, упирается в кулдаун и сжигает цикл впустую.
    questions = getattr(self, "_open_questions", None)
    if (
        interaction is not None
        and isinstance(questions, list)
        and self._can_ask_now(cycle)
    ):
        for item in questions:
            if not isinstance(item, dict) or item.get("answered"):
                continue
            explored = len(item.get("explorations") or [])
            limit = int(item.get("max_explorations") or 5)
            # Агент уже пробовала сама и не смогла — время спросить.
            if explored >= max(1, limit - 1):
                candidates.append(
                    {
                        "source": "social",
                        "action": "ask_user",
                        "strength": self._dampen("ask_user", 0.78),
                        "params": {"topic": item.get("text", "")},
                    }
                )
                break

    # 2. Давно молчал — рассказать, что узнал.
    if interaction is not None:
        silence = int(getattr(LR_CONFIG, "SOCIAL_SILENCE_CYCLES", 40) or 40)
        last = getattr(self, "_last_share_cycle", None)
        if last is None:
            last = 0
        if cycle - int(last) >= silence and self._compose_share_message():
            candidates.append(
                {
                    "source": "social",
                    "action": "communicate",
                    "strength": self._dampen("communicate", 0.72),
                    "params": {},
                }
            )

    # 3. Тема без своей формулировки — поискать в сети.
    searcher = getattr(self, "web_searcher", None)
    if searcher is not None and getattr(searcher, "is_enabled", False):
        concepts = getattr(self.mental_models, "concepts", None)
        if isinstance(concepts, dict):
            for name, node in concepts.items():
                if not self._is_learnable(name):
                    continue
                if len(str(getattr(node, "definition_hypothesis", "") or "")) > 10:
                    continue
                if len(getattr(node, "experiences", []) or []) < 1:
                    continue
                candidates.append(
                    {
                        "source": "social",
                        "action": "web_search",
                        "strength": self._dampen("web_search", 0.6),
                        "params": {"topic": name},
                    }
                )
                break

    return candidates


def _is_action_available_impl(self, action: Optional[str]) -> bool:
    """Можно ли выполнить действие прямо сейчас.

    Проверяются только те ограничения, которые заведомо откажут:
    кулдаун вопроса, выключенный поиск и нехватка энергии. Остальное
    решается в ``act()`` и записывается как исход.

    Нехватка энергии добавлена потому, что отказ — это не выбор, а
    пустой цикл. Замер до правки: 243 отказа «too_tired» на 400
    попыток, при этом арбитр каждый раз выбирал действие, которое
    тело выполнить не могло. Дешевле не предлагать невозможное.
    """
    normalized = self._normalize_action(action)
    if normalized == "let_go":
        return True
    if normalized == "create_draft":
        from src.cognition.creative_draft import draft_available

        return self._is_action_affordable(normalized) and draft_available(
            getattr(self, "_creative_draft", None)
        )
    if normalized == "draw":
        from src.cognition.local_art import art_available

        return self._is_action_affordable(normalized) and art_available(
            getattr(self, "_art_work", None)
        )
    if normalized == "compose_music":
        from src.cognition.local_music import music_available

        return self._is_action_affordable(normalized) and music_available(
            getattr(self, "_music_work", None)
        )
    if normalized == "ask_user":
        return self._can_ask_now(self.cycle_count) and self._has_question_target()
    if normalized == "web_search":
        searcher = getattr(self, "web_searcher", None)
        if searcher is None:
            return False
        return bool(getattr(searcher, "is_enabled", False))
    if normalized == "read_news":
        searcher = getattr(self, "web_searcher", None)
        if searcher is None or not getattr(searcher, "is_enabled", False):
            return False
        # Нет темы — нечего читать; кулдаун по теме не отсекаем
        # здесь: честный «уже читал» информативнее тихого отказа.
        return self._pick_news_topic() is not None
    if normalized == "browse_web":
        searcher = getattr(self, "web_searcher", None)
        if searcher is None or not getattr(searcher, "is_enabled", False):
            return False
        return self._pick_news_topic() is not None
    if normalized == "decomposition":
        # Декомпозиция полезна только пока есть что разложить и куда
        # положить результат: под-вопросы идут в очередь, а она не
        # резиновая. Раньше действие предлагалось всегда и в
        # большинстве случаев заканчивалось «не разбивается на части» —
        # гарантированный пустой цикл.
        return (
            self._decomposition_has_room()
            and self._pick_decomposable_target(remember=False) is not None
        )
    return self._is_action_affordable(normalized)


def _is_candidate_available_impl(self, candidate) -> bool:
    from src.cognition.intention_payload import intention_target

    try:
        target = intention_target(candidate)
        if self._normalize_action(candidate.get("action")) == "create_draft":
            from src.cognition.creative_catalog import creative_request, catalog_for
            from src.cognition.creative_draft import LIMIT, MAX_DRAFTS, draft_available

            mode, identifier, _ = creative_request(candidate)
            catalog = catalog_for(self)
            if identifier is not None and identifier not in catalog:
                return False
            if mode == "leave":
                selected = (
                    catalog.get(identifier)
                    if identifier
                    else getattr(self, "_creative_draft", None)
                )
                return bool(
                    selected
                    and selected.get("status", "active") == "active"
                    and self._is_action_affordable("create_draft")
                )
            if mode == "new":
                return (
                    len(catalog) < MAX_DRAFTS
                    and draft_available(None)
                    and self._is_action_affordable("create_draft")
                )
            if identifier is not None and mode == "continue":
                selected = catalog[identifier]
                return (
                    selected.get("status", "active") == "active"
                    and selected["revision"] < LIMIT
                    and self._is_action_affordable("create_draft")
                )
    except ValueError:
        return False
    action = self._normalize_action(candidate.get("action"))
    if target is not None:
        if not self._is_learnable(target):
            return False
        if action == "decomposition":
            if not self._decomposition_has_room():
                return False
            parts = self._decompose_query(target) or []
            if len(parts) < 2:
                return False
            return self._is_action_affordable(action)
        if action == "ask_user":
            return self._can_ask_now(self.cycle_count) and self._is_action_affordable(
                action
            )
    return self._is_action_available(candidate.get("action"))


def _decomposition_has_room_impl(self) -> bool:
    """Есть ли место в очереди открытых вопросов для под-вопросов."""
    limit = int(getattr(LR_CONFIG, "OPEN_QUESTIONS_MAX_UNANSWERED", 3) or 0)
    if limit <= 0:
        return False
    try:
        questions = self.get_open_questions()
    except Exception:
        return False
    unanswered = sum(1 for q in questions if not q.get("answered"))
    return unanswered < limit


def _stuck_fallback_impl(self) -> str:
    """Что делать, когда все кандидаты оказались тупиковыми.

    Раньше здесь всегда был ``think_decompose`` — причём это же
    действие чаще всего и было тупиковым. То есть запасной выход вёл
    обратно в тот же тупик.

    Порядок: отдых, если тело требует; иначе продуктивное действие с
    доказанной историей эффекта, которое сейчас выполнимо и не в
    тупике. Если такого нет — отдых: он хотя бы восстанавливает тело,
    вместо того чтобы делать вид, что агент работает.
    """
    if self._body_needs_rest() or self._is_resting():
        return "deep_rest"

    closer = getattr(self, "loop_closer", None)
    if closer is not None:
        proven = sorted(
            closer.effective_actions(),
            key=lambda name: -closer.effect_count(name),
        )
        for name in proven:
            if not closer.is_productive(name):
                continue
            if closer.is_stuck(name):
                continue
            if not self._is_action_available(name):
                continue
            return name
    return "deep_rest"


def _release_recovered_denials_impl(self) -> None:
    """Снимает пометку «тупик» с действий, которые снова по карману.

    Отказ по усталости — факт о теле, а не о действии. Пока энергия не
    вернулась, повторять бессмысленно; когда вернулась — запрет должен
    исчезнуть сам, иначе отдых не возвращает агента к работе.
    """
    closer = getattr(self, "loop_closer", None)
    if closer is None:
        return
    for action in closer.stuck_actions():
        if not closer.denied_streak(action):
            continue
        if self._is_action_affordable(action):
            closer.reset_denial(action)


def _has_question_target_impl(self) -> bool:
    """Есть ли о чём спросить человека прямо сейчас.

    Проверка без побочных эффектов (в отличие от
    ``_pick_exploration_target``, который запоминает тему). Нужна,
    чтобы не предлагать арбитру вопрос, который заведомо закончится
    «не о чем спрашивать»: иначе действие выбирается каждый цикл,
    ничего не меняет и не запускает кулдаун, потому что вопрос так и
    не был задан.
    """
    questions = getattr(self, "_open_questions", None)
    if isinstance(questions, list):
        for item in questions:
            if not isinstance(item, dict) or item.get("answered"):
                continue
            if str(item.get("text") or "").strip():
                return True

    history = getattr(self, "_exploration_history", None)
    recently = set(history) if isinstance(history, list) else set()

    concepts = getattr(self.mental_models, "concepts", None)
    if isinstance(concepts, dict):
        for name, node in concepts.items():
            if not self._is_learnable(name):
                continue
            if float(getattr(node, "confidence", 0.0) or 0.0) < 0.9:
                return True
        known = set(concepts)
    else:
        known = set()

    for topic in self._stimulus_topics():
        if topic not in known and topic not in recently:
            return True
    return False


def _can_ask_now_impl(self, cycle: int) -> bool:
    """Можно ли сейчас задать вопрос человеку (кулдаун и лимиты)."""
    interaction = getattr(self, "user_interaction", None)
    checker = getattr(interaction, "can_ask_question", None)
    if checker is None:
        return False
    try:
        return bool(checker(cycle))
    except Exception:
        return False


def _dampen_impl(self, action: str, strength: float) -> float:
    """Снижает силу кандидата, если действие подряд не давало эффекта.

    Иначе действие, которое сейчас невозможно (кулдаун, нет сети),
    выигрывает арбитраж каждый цикл и сжигает жизнь впустую. Каждая
    неудача вдвое снижает шанс: 0.78 → 0.39 → 0.20 → …
    """
    closer = getattr(self, "loop_closer", None)
    if closer is None:
        return strength
    try:
        streak = closer.no_effect_streak(action)
    except Exception:
        return strength
    return strength * (0.5 ** max(0, streak))


def _record_denied_impl(
    self, action_type: str, world_before, reason: str, *, record_denied_outcome
) -> None:
    """Совместимость: см. модульную ``record_denied_outcome``."""
    record_denied_outcome(self, action_type, world_before, reason)


def _normalize_action_impl(self, action: Optional[str]) -> str:
    """Приводит имя действия к типу (как в ``act()``).

    Мотивация и Active Inference называют одно и то же действие
    по-разному: «exploration» / «explore», «reflection» / «reflect».
    Счётчики петель должны видеть один тип, иначе проверка тупика
    смотрит не на то имя.
    """
    key = str(action or "").strip().lower()
    if not key:
        return ""
    return self.ACTION_ALIASES.get(key, key)
