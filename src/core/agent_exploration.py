"""Exploration-target helpers extracted from ``agent.py``.

The ``DigitalBeing`` facade remains the stable public surface. Cross-contour
calls stay on that facade so existing monkeypatches and late binding keep working.
"""

import random
from typing import Dict, List, Optional

from config.simulation_config import LR_CONFIG


def _is_learnable_impl(self, name: str) -> bool:
    """Годится ли концепция как тема для изучения и вопросов.

        Служебные узлы (``_bootstrap_loaded``) и врождённые убеждения
        (``убеждение_1``) — не темы для исследования: спрашивать человека
        про «_bootstrap_loaded» бессмысленно, а «изучать» собственный
        маркер загрузки — имитация работы.
        """
    text = str(name or "").strip()
    if not text:
        return False
    if text.startswith("_"):
        return False
    if text.startswith("убеждение_"):
        return False
    return True


def _is_meta_topic_impl(self, name: str) -> bool:
    """Тема состоит из метаслов диалога, а не из содержания мира?

        Проверка по целым словам: «ответственный» — обычная тема,
        «вопрос» и «открытый вопрос» — метаслово.
        """
    text = str(name or "").strip().lower()
    if not text:
        return True
    return any(word in text.split() for word in self._META_TOPIC_WORDS)


def _is_meaningful_topic_impl(self, name: str) -> bool:
    """Тема — содержание мира, а не шум диалога?

        TICKET-8: среди живых целей всплыли «Понять: 🙂🙂🙂» и
        «Понять: ты». Минимум две буквы; строка из одних местоимений —
        не тема. Честное ограничение: осмысленный на вид мусор
        («теминг тест») фильтр не отличит — источник такого мусора
        закрыт «Собеседником-6», здесь добиваем буквенный шум.
        """
    text = str(name or "").strip()
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 2:
        return False
    words = [
        word
        for word in text.lower().split()
        if any(ch.isalpha() for ch in word)
    ]
    if words and all(word in self._NOISE_TOPIC_WORDS for word in words):
        return False
    return True


def _recently_explained_by_user_impl(self, topic: str) -> bool:
    """Тема, объяснённая человеком недавно, не переспрашивается.

        Ответ пользователя записан как свидетельство — знание уже есть.
        «Ты же спрашивал про это» после собственного объяснения — то, что
        живой прогон 2026-11-01 показал на сущности Тэсс.
        """
    stamps = getattr(self, "_user_explained_topics", None)
    if not isinstance(stamps, dict) or not stamps:
        return False
    stamped = stamps.get(str(topic or "").strip())
    if stamped is None:
        return False
    cooldown = float(
        getattr(LR_CONFIG, "USER_EXPLAINED_COOLDOWN_CYCLES", 200) or 0
    )
    return cooldown > 0 and (self.cycle_count - stamped) < cooldown


def _pick_shallow_concept_impl(self, concepts: Dict) -> Optional[str]:
    """Неуверенная тема вне текущего круга: формулировка ещё не знание.

        Это только кандидат на исследование, не обязательство закрыть
        пробел. Доля углубления и арбитр по-прежнему допускают иной выбор.
        """
    if not isinstance(concepts, dict):
        return None
    recently = set(getattr(self, "_exploration_history", []) or [])
    candidates = []
    for name, node in concepts.items():
        if (
            not self._is_learnable(name)
            or self._is_meta_topic(name)
            or not self._is_meaningful_topic(name)
        ):
            continue
        if name in recently:
            continue
        if self._recently_explained_by_user(name):
            continue
        experiences = len(getattr(node, "experiences", []) or [])
        confidence = float(getattr(node, "confidence", 0.0))
        if experiences < 1 or confidence > 0.4:
            continue
        candidates.append((experiences, name))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -len(item[1])))
    return candidates[0][1]


def _pick_exploration_target_impl(self) -> Optional[str]:
    """Выбирает, что исследовать: то, чего агент ещё не изучал.

        Порядок приоритетов:
        1. Открытый вопрос без ответа — человек его задал, это важно.
        2. Иногда — возврат к уже встреченной теме (углубление): без этого
           агент только расширял охват, а собственная формулировка требует
           вернуться к теме минимум дважды.
        3. Неизвестная тема из пула стимулов: агент идёт в неизвестное,
           а не пережёвывает известное.
        4. Концепция с наименьшей уверенностью, ещё не изученная в этом
           круге.

        Важно: цель не повторяется, пока не исчерпан круг. Иначе агент
        «изучает» одну и ту же концепцию, ничего не узнаёт (уверенность не
        растёт без новой информации) и застревает — именно это и
        происходило до замыкания петли.

        Returns:
            Название темы или ``None``, если исследовать нечего.
        """
    history = getattr(self, "_exploration_history", None)
    if not isinstance(history, list):
        history = []
        self._exploration_history = history
    recently = set(history)
    concepts = getattr(self.mental_models, "concepts", None)

    # 1. Открытые вопросы
    questions = getattr(self, "_open_questions", None)
    if isinstance(questions, list):
        for item in questions:
            if not isinstance(item, dict):
                continue
            if item.get("answered"):
                continue
            text = str(item.get("text") or "").strip()
            if text and text not in recently:
                self._remember_exploration(text)
                return text

    # 2. Иногда возвращаемся к теме, чтобы углубить её.
    # Проверяем ДО поиска новых тем: иначе при непустом пуле стимулов
    # глубина не наступала бы никогда — агент только расширял охват,
    # у каждой концепции оставалась одна встреча, а собственная
    # формулировка требует минимум двух.
    depth_ratio = float(
        getattr(LR_CONFIG, "EXPLORATION_DEPTH_RATIO", 0.35) or 0.0
    )
    if depth_ratio > 0 and random.random() < depth_ratio:
        shallow = self._pick_shallow_concept(concepts)
        if shallow is not None:
            self._remember_exploration(shallow)
            return shallow

    # 3. Неизвестная тема из пула стимулов
    known = set(concepts) if isinstance(concepts, dict) else set()
    for topic in self._stimulus_topics():
        if topic in known or topic in recently:
            continue
        if not self._is_meaningful_topic(topic):
            continue
        self._remember_exploration(topic)
        return topic

    # 4. Слабая концепция, ещё не тронутая в этом круге
    if not isinstance(concepts, dict) or not concepts:
        return None

    def weakness(node) -> tuple:
        confidence = float(getattr(node, "confidence", 0.0) or 0.0)
        experiences = len(getattr(node, "experiences", []) or [])
        return (confidence, experiences)

    fresh = [
        name
        for name in concepts
        if name not in recently
        and self._is_learnable(name)
        and self._is_meaningful_topic(name)
        and not self._is_meta_topic(name)
        and not self._recently_explained_by_user(name)
        and float(getattr(concepts[name], "confidence", 0.0) or 0.0) < 0.9
    ]
    if not fresh:
        # Круг исчерпан: начинаем заново, но теперь это осознанный
        # повторный визит, а не топтание на месте.
        history.clear()
        fresh = [
            name
            for name in concepts
            if self._is_learnable(name)
            and self._is_meaningful_topic(name)
            and not self._is_meta_topic(name)
            and not self._recently_explained_by_user(name)
            and float(getattr(concepts[name], "confidence", 0.0) or 0.0) < 0.9
        ]
    if not fresh:
        return None

    target = min(fresh, key=lambda name: weakness(concepts[name]))
    self._remember_exploration(target)
    return target


def _decomposable_targets_impl(self) -> List[str]:
    """Кандидаты на декомпозицию в порядке приоритета, без побочных эффектов.

        Отдельный список, потому что у декомпозиции другое требование, чем
        у исследования: ей нужно не «что угодно неизученное», а «то, что
        делится на части». Раньше она брала первую попавшуюся цель и в
        большинстве случаев возвращала «не разбивается на части» — цикл
        потрачен, мир не изменился.
        """
    targets: List[str] = []

    questions = getattr(self, "_open_questions", None)
    if isinstance(questions, list):
        for item in questions:
            if not isinstance(item, dict) or item.get("answered"):
                continue
            text = str(item.get("text") or "").strip()
            if text:
                targets.append(text)

    concepts = getattr(self.mental_models, "concepts", None)
    known = set(concepts) if isinstance(concepts, dict) else set()
    for topic in self._stimulus_topics():
        if topic not in known:
            targets.append(topic)

    if isinstance(concepts, dict):
        for name in concepts:
            if not self._is_learnable(name):
                continue
            confidence = float(
                getattr(concepts[name], "confidence", 0.0) or 0.0
            )
            if confidence < 0.9:
                targets.append(name)

    # Порядок важен: первый разложимый — самый приоритетный.
    return list(dict.fromkeys(targets))


def _pick_decomposable_target_impl(self, remember: bool = True) -> Optional[str]:
    """Первая тема, которую действительно есть на что разложить."""
    for target in self._decomposable_targets():
        try:
            parts = self._decompose_query(target)
        except Exception:
            continue
        if not parts:
            continue
        if remember:
            self._remember_exploration(target)
        return target
    return None


def _stimulus_topics_impl(self) -> List[str]:
    """Темы из пула стимулов, приведённые к виду концепций."""
    pool = getattr(LR_CONFIG, "STIMULI_POOL", None) or []
    topics = []
    for raw in pool:
        text = str(raw).strip()
        if not text:
            continue
        # «вопрос: что такое время» → «что такое время»
        if ":" in text:
            text = text.split(":", 1)[1].strip()
        if text:
            topics.append(text)
    return topics


def _remember_exploration_impl(self, target: str) -> None:
    """Запоминает изученную тему, чтобы не брать её снова подряд."""
    history = getattr(self, "_exploration_history", None)
    if not isinstance(history, list):
        history = []
        self._exploration_history = history
    if target in history:
        history.remove(target)
    history.append(target)
    # Ограничиваем память: помним только последний круг.
    limit = max(10, int(getattr(LR_CONFIG, "EXPLORATION_HISTORY_SIZE", 200)))
    if len(history) > limit:
        del history[: len(history) - limit]
