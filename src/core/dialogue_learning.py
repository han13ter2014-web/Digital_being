"""
DialogueLearning — саморазвитие диалоговых таблиц («Собеседник-7»).

До этой ступени таблицы маркеров в dialogue_acts.py расширял только
разработчик: живая речь богаче любой рукописной таблицы, и каждая
нераспознанная фраза («Не нашел файл для…» → честный отклик) оставалась
мертвой зоной навсегда. В user_model.py и dialogue_acts.py это будущее
было прямо зафиксировано: «включая возможное саморазвитие таблиц самой
сущностью».

Граница субъектности: сущность НЕ выдумывает маркеры сама. Человек —
источник свидетельства, а не безусловной истины: фраза становится маркером
только после явного подтверждения через вопрос-уточнение. Детерминизм
сохранён: обученные маркеры — литеральные подстроки, ведущие только на
существующие акты (social / about_self / request) с детерминированными
честными ответами. ACT_ANSWER сознательно исключён: выученный «ответ» смог
бы закрывать настоящие вопросы сущности мусором — это единственный акт,
который пишет в знания, а обучение не должно создавать новых генераторов
поведения. Слова пользователя пишутся только в таблицы распознавания речи
(свидетельство о речи человека), не в ценности и мотивацию. Отдельные
эмоциональные ассоциации тоже остаются user_taught-свидетельствами: их
поведенческий вес зависит от доверия и близости, но не становится фактом.

Приоритет: статические рукописные таблицы всегда сильнее обученных —
обученное заполняет пробелы, а не перекрывает решения разработчика.

Сериализуется в чекпоинт (секция dialogue_learning): после рестарта
выученное не забывается.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional

from src.core.dialogue_acts import (
    ACT_ASK_ABOUT_SELF,
    ACT_REQUEST,
    ACT_SOCIAL,
    is_noise_input,
)
from src.core.human_affect import (
    AFFECT_COMPONENTS,
    AFFECT_LABELS,
    AFFECT_PHRASE_MAX_LEN,
    BASE_AFFECT_ACTIVATION,
    normalize_affect_phrase,
    restore_learned_affect,
)
from src.core.dialogue_strategies import DialogueStrategyMemory

# Обучаемые акты — только те, что ведут на существующие
# детерминированные ответы и не пишут в знания.
LEARNABLE_ACTS = (ACT_SOCIAL, ACT_ASK_ABOUT_SELF, ACT_REQUEST)

# Порог повторов: однажды сказанное поведение не меняет (научение
# устойчивое, не мгновенное).
REPEAT_THRESHOLD = 2

# Кулдаун между предложениями-уточнениями, по образцу
# USER_EXPLAINED_COOLDOWN_CYCLES (1200 ≈ 10 минут живого хода).
PROPOSAL_COOLDOWN_CYCLES = 1200

# Лимиты буфера и фраз: долгоживущий процесс не должен копить очереди
# без границ; фраза длиннее лимита — не маркер, а рассказ.
BUFFER_MAX = 50
PHRASE_MIN_LEN = 3
PHRASE_MAX_LEN = 80

# Префиксы разных протоколов. Старые ответы 1–4 никогда не становятся
# эмоциональным обучением; user_taught требует отдельного подтверждения.
PROPOSAL_CONTEXT_PREFIX = "dialogue_learning: "
AFFECT_PROPOSAL_CONTEXT_PREFIX = "affect_learning: "
LEARNED_AFFECT_MAX = 200

_AFFECT_CONFIRM_ANSWERS = frozenset(
    {"да", "подтверждаю", "запомни", "верно", "согласен", "согласна"}
)
_AFFECT_REJECT_ANSWERS = frozenset(
    {"нет", "не надо", "не учи", "не учить", "не запоминай", "отмена", "неверно"}
)

# Команда забвения: «забудь фразу X».
FORGET_PREFIX = "забудь фразу"

# Детерминированный разбор обучающего ответа. Проверяются в порядке
# приоритета: явное число, затем слова. «Не учить» сильнее остальных:
# фраза с запретом не должна учиться, даже если рядом слово «вопрос».
_SUPPRESS_MARKERS = (
    "4",
    "не учи",
    "не учить",
    "не надо учить",
    "неважно",
    "не важно",
    "забудь",
    "оставь",
)
_SOCIAL_ANSWER_MARKERS = (
    "1",
    "разговор",
    "приветствие",
    "социальн",
    "болтовн",
    "smalltalk",
)
_ABOUT_SELF_ANSWER_MARKERS = (
    "2",
    "вопрос",
    "спрашиваю",
)
_REQUEST_ANSWER_MARKERS = (
    "3",
    "просьб",
    "приказ",
    "команда",
)


def normalize_phrase(text) -> str:
    """Нормализация как в classify_user_text: нижний регистр, сжатые
    пробелы. Совпадение маркеров — по этой форме."""
    return " ".join(str(text or "").lower().split())


class DialogueLearning:
    """Контур саморазвития диалоговых таблиц.

    Собирает нераспознанные реплики, предлагает повторные фразы
    человеку на уточнение и хранит подтверждённые маркеры. Только
    факты о речи пользователя; субъектность Core не затрагивается.
    """

    def __init__(self) -> None:
        self.buffer: Dict[str, dict] = {}
        self.learned: Dict[str, dict] = {}
        self.suppressed: Dict[str, int] = {}
        # Точная фраза → пользовательское свидетельство о значении. Это не
        # факт и не оценка личности; вес доверия вычисляется при чтении.
        self.learned_affect: Dict[str, dict] = {}
        self.suppressed_affect: Dict[str, int] = {}
        # Отдельно от автономных method_preferences: отзыв о реплике не
        # меняет действия, знания или ценности сущности.
        self.strategy_memory = DialogueStrategyMemory()
        self.last_proposal_cycle: int = -PROPOSAL_COOLDOWN_CYCLES
        # Публичные поля выше описывают активный язык. Неактивный язык хранится
        # отдельным полным снапшотом, включая cooldown и strategy memory.
        self.active_language = "ru"
        self._language_states: Dict[str, dict] = {}

    def _language_state(self) -> dict:
        return {
            "buffer": {phrase: dict(entry) for phrase, entry in self.buffer.items()},
            "learned": {phrase: dict(entry) for phrase, entry in self.learned.items()},
            "suppressed": dict(self.suppressed),
            "learned_affect": {
                phrase: dict(entry, components=dict(entry.get("components") or {}))
                for phrase, entry in self.learned_affect.items()
            },
            "suppressed_affect": dict(self.suppressed_affect),
            "dialogue_strategies": self.strategy_memory.to_dict(),
            "last_proposal_cycle": self.last_proposal_cycle,
        }

    def set_language(self, language_id: str) -> None:
        """Активировать независимый опыт RU/EN без потери прежнего языка."""
        if language_id not in {"ru", "en"}:
            raise ValueError("language_id: expected ru or en")
        if language_id == self.active_language:
            return
        self._language_states[self.active_language] = self._language_state()
        saved = self._language_states.pop(language_id, None)
        self.active_language = language_id
        if saved is not None:
            self._restore_language_state(saved)
            return
        self.buffer = {}
        self.learned = {}
        self.suppressed = {}
        self.learned_affect = {}
        self.suppressed_affect = {}
        self.strategy_memory = DialogueStrategyMemory()
        self.last_proposal_cycle = -PROPOSAL_COOLDOWN_CYCLES

    def _restore_language_state(self, state: dict) -> None:
        restored = DialogueLearning()
        restored.load_from(state)
        self.buffer = restored.buffer
        self.learned = restored.learned
        self.suppressed = restored.suppressed
        self.learned_affect = restored.learned_affect
        self.suppressed_affect = restored.suppressed_affect
        self.strategy_memory = restored.strategy_memory
        self.last_proposal_cycle = restored.last_proposal_cycle

    # === Сбор ===

    def observe(self, text, cycle: int = 0) -> Optional[str]:
        """Запомнить нераспознанную реплику; вернуть фразу-кандидата.

        Кандидат возвращается, когда фраза повторилась REPEAT_THRESHOLD
        раз, не выучена, не запрещена и кулдаун предложений истёк.
        None — предлагать нечего (шум, длинный текст, уже известное).
        """
        phrase = normalize_phrase(text)
        if not self._is_collectable(phrase):
            return None

        entry = self.buffer.get(phrase)
        if entry is None:
            if len(self.buffer) >= BUFFER_MAX:
                self._trim_buffer()
            entry = {"count": 0, "first_cycle": int(cycle), "last_cycle": 0}
            self.buffer[phrase] = entry
        entry["count"] += 1
        entry["last_cycle"] = int(cycle)

        if entry["count"] < REPEAT_THRESHOLD:
            return None
        if cycle - self.last_proposal_cycle < PROPOSAL_COOLDOWN_CYCLES:
            return None
        return phrase

    def immediate_candidate(self, text, cycle: int = 0) -> Optional[str]:
        """Фраза для уточнения с первого входа, без автообучения.

        Порог повторов в ``observe`` остаётся прежним и нужен старому
        контуру. Здесь проверяются только запреты и кулдаун: категорию
        спрашиваем сразу, но маркер по-прежнему возникает лишь после
        явного ответа человека в ``resolve``.
        """
        phrase = normalize_phrase(text)
        affect_phrase = normalize_affect_phrase(phrase)
        if (
            not phrase
            or is_noise_input(phrase)
            or phrase in self.learned
            or phrase in self.suppressed
            or affect_phrase in self.learned_affect
            or affect_phrase in self.suppressed_affect
            or cycle - self.last_proposal_cycle < PROPOSAL_COOLDOWN_CYCLES
        ):
            return None
        return phrase

    def _is_collectable(self, phrase: str) -> bool:
        if not phrase or len(phrase) < PHRASE_MIN_LEN:
            return False
        if len(phrase) > PHRASE_MAX_LEN:
            return False
        if is_noise_input(phrase):
            return False
        affect_phrase = normalize_affect_phrase(phrase)
        if phrase in self.learned or phrase in self.suppressed:
            return False
        if (
            affect_phrase in self.learned_affect
            or affect_phrase in self.suppressed_affect
        ):
            return False
        return True

    def _trim_buffer(self) -> None:
        """Вытеснение старейших записей: буфер не растёт бесконечно."""
        oldest = sorted(self.buffer, key=lambda p: self.buffer[p]["first_cycle"])
        for phrase in oldest[: max(1, len(self.buffer) - BUFFER_MAX + 1)]:
            del self.buffer[phrase]

    # === Предложение ===

    def build_proposal(self, phrase: str, cycle: int = 0) -> dict:
        """Собрать вопрос-уточнение для user_interaction.ask_user.

        Контекст несёт саму фразу (PROPOSAL_CONTEXT_PREFIX): по нему
        runner сопоставляет обучающий ответ с фразой без дополнительного
        состояния — pending-вопросы переживают рестарт вместе с
        контекстом, поэтому сопоставление не теряется.

        Кулдаун здесь НЕ выставляется: ask_user может отказать (свой
        cooldown вопросов), и тогда фраза должна получить следующую
        попытку, а не молча уйти на 1200 циклов. Отметку ставит runner
        через mark_proposed после фактической постановки вопроса.
        """
        entry = self.buffer.get(phrase, {})
        count = int(entry.get("count", 1))
        displayed = (
            phrase
            if len(phrase) <= PHRASE_MAX_LEN
            else phrase[: PHRASE_MAX_LEN - 1] + "…"
        )
        return {
            "question": (
                f"Ты уже {count} раз(а) говоришь «{displayed}», а я этого "
                "не понимаю. Как мне это воспринимать? Ответь числом: "
                "1 — обычный разговор, 2 — вопрос ко мне, "
                "3 — просьба, которой я не умею, 4 — неважно, не учить."
            ),
            "context": PROPOSAL_CONTEXT_PREFIX + phrase,
        }

    def mark_proposed(self, cycle: int = 0) -> None:
        """Отметить, что вопрос-уточнение фактически задан человеку.

        Вызывается runner'ом только после успешной постановки вопроса
        (ask_user → queued/duplicate): кулдаун защищает от переспроса,
        а не от попыток, которые до человека не дошли.
        """
        self.last_proposal_cycle = int(cycle)

    @staticmethod
    def is_proposal_context(context) -> bool:
        """True, если контекст pending-вопроса — обучающее предложение."""
        return str(context or "").startswith(PROPOSAL_CONTEXT_PREFIX)

    @staticmethod
    def phrase_from_context(context) -> str:
        """Фраза из контекста обучающего предложения."""
        text = str(context or "")
        if not text.startswith(PROPOSAL_CONTEXT_PREFIX):
            return ""
        return text[len(PROPOSAL_CONTEXT_PREFIX) :].strip()

    # === Обучающий ответ ===

    def resolve(self, phrase: str, answer, cycle: int = 0) -> dict:
        """Применить обучающий ответ пользователя к фразе.

        Возвращает {"status": "learned"|"suppressed"|"unclear", ...}.
        Непонятный ответ ничему не учит и не запрещает: фраза остаётся
        в буфере, кулдаун не даёт спросить снова сразу.
        """
        phrase = normalize_phrase(phrase)
        kind = self._classify_teaching_answer(answer)
        if kind is None:
            return {"status": "unclear", "phrase": phrase}
        if kind == "suppress":
            self.suppressed[phrase] = int(cycle)
            self.buffer.pop(phrase, None)
            return {"status": "suppressed", "phrase": phrase}
        self.learned[phrase] = {"act": kind, "cycle": int(cycle)}
        self.buffer.pop(phrase, None)
        return {"status": "learned", "phrase": phrase, "act": kind}

    @staticmethod
    def _classify_teaching_answer(answer) -> Optional[str]:
        """Детерминированный разбор ответа на вопрос-уточнение."""
        normalized = normalize_phrase(answer)
        if not normalized:
            return None
        for marker in _SUPPRESS_MARKERS:
            if marker in normalized:
                return "suppress"
        for marker in _ABOUT_SELF_ANSWER_MARKERS:
            if marker in normalized:
                return ACT_ASK_ABOUT_SELF
        for marker in _REQUEST_ANSWER_MARKERS:
            if marker in normalized:
                return ACT_REQUEST
        for marker in _SOCIAL_ANSWER_MARKERS:
            if marker in normalized:
                return ACT_SOCIAL
        return None

    # === Классификатор ===

    def classifier_entries(self) -> Dict[str, str]:
        """{нормализованная фраза: акт} для classify_user_text.

        Проверяются ПОСЛЕ статических таблиц: рукописное сильнее
        обученного. Подстроки длиннее — раньше: «добрый вечер друг»
        не должна проигрывать своей подстроке «добрый вечер».
        """
        entries = {
            phrase: entry["act"]
            for phrase, entry in self.learned.items()
            if entry.get("act") in LEARNABLE_ACTS
        }
        return dict(sorted(entries.items(), key=lambda kv: len(kv[0]), reverse=True))

    def affect_classifier_entries(self) -> Dict[str, dict]:
        """Точные user_taught-записи, без нечёткого recall и без фактов."""
        restored = {}
        for phrase, entry in self.learned_affect.items():
            clean = restore_learned_affect(entry)
            if clean is not None:
                restored[phrase] = clean
        return restored

    # === Отдельное аффективное обучение ===

    @staticmethod
    def build_affect_proposal(phrase: str, component: str) -> dict:
        phrase = normalize_affect_phrase(phrase)
        label = AFFECT_LABELS.get(component, component)
        return {
            "question": (
                f"Запомнить «{phrase}» как твоё выражение: «{label}»? "
                "Я сохраню именно твоё объяснение, а не безусловный факт. "
                "Ответь «да» или «нет»."
            ),
            "context": AFFECT_PROPOSAL_CONTEXT_PREFIX + component + ":" + phrase,
        }

    @staticmethod
    def is_affect_proposal_context(context) -> bool:
        return str(context or "").startswith(AFFECT_PROPOSAL_CONTEXT_PREFIX)

    @staticmethod
    def affect_from_context(context) -> tuple:
        text = str(context or "")
        if not text.startswith(AFFECT_PROPOSAL_CONTEXT_PREFIX):
            return "", ""
        payload = text[len(AFFECT_PROPOSAL_CONTEXT_PREFIX) :]
        component, separator, phrase = payload.partition(":")
        if not separator or component not in AFFECT_COMPONENTS:
            return "", ""
        return normalize_affect_phrase(phrase), component

    def resolve_affect(self, phrase, component, answer, cycle: int = 0) -> dict:
        """Записать только явно подтверждённое свидетельство человека."""
        phrase = normalize_affect_phrase(phrase)
        if (
            len(phrase) < PHRASE_MIN_LEN
            or len(phrase) > AFFECT_PHRASE_MAX_LEN
            or component not in AFFECT_COMPONENTS
        ):
            return {"status": "unclear", "phrase": phrase}
        normalized_answer = normalize_affect_phrase(answer)
        if normalized_answer in _AFFECT_REJECT_ANSWERS:
            self.suppressed_affect[phrase] = int(cycle)
            self.buffer.pop(phrase, None)
            return {"status": "suppressed", "phrase": phrase}
        if normalized_answer not in _AFFECT_CONFIRM_ANSWERS:
            return {"status": "unclear", "phrase": phrase}
        if (
            phrase not in self.learned_affect
            and len(self.learned_affect) >= LEARNED_AFFECT_MAX
        ):
            return {"status": "limit", "phrase": phrase}
        self.learned_affect[phrase] = {
            "components": {component: 1.0},
            "weight": BASE_AFFECT_ACTIVATION,
            "evidence": "user_taught",
            "cycle": int(cycle),
        }
        self.suppressed_affect.pop(phrase, None)
        self.buffer.pop(phrase, None)
        return {
            "status": "learned",
            "phrase": phrase,
            "component": component,
        }

    # === Забвение ===

    def forget(self, phrase) -> bool:
        """Забыть общую и аффективную связь фразы, если они были."""
        normalized = normalize_phrase(phrase)
        removed = False
        if normalized in self.learned:
            del self.learned[normalized]
            self.suppressed[normalized] = 0
            removed = True
        affect_phrase = normalize_affect_phrase(phrase)
        if affect_phrase in self.learned_affect:
            del self.learned_affect[affect_phrase]
            self.suppressed_affect[affect_phrase] = 0
            removed = True
        return removed

    @staticmethod
    def parse_forget_command(text) -> Optional[str]:
        """«забудь фразу X» → X; иначе None."""
        normalized = normalize_phrase(text)
        if not normalized.startswith(FORGET_PREFIX):
            return None
        phrase = normalized[len(FORGET_PREFIX) :].strip(' .!?:;"«»')
        return phrase or None

    # === Статус ===

    def get_status(self) -> dict:
        return {
            "buffered": len(self.buffer),
            "learned": len(self.learned),
            "suppressed": len(self.suppressed),
            "learned_affect": len(self.learned_affect),
            "suppressed_affect": len(self.suppressed_affect),
            "dialogue_strategies": self.strategy_memory.get_status(),
        }

    # === Сериализация ===

    def to_dict(self) -> dict:
        # Верхнеуровневые поля сохраняют старый формат активного языка.
        # Неактивные состояния добавляются отдельно и никогда не смешиваются.
        return {
            "schema_version": 2,
            "active_language": self.active_language,
            "language_states": deepcopy(self._language_states),
            **self._language_state(),
        }

    def load_from(self, data) -> None:
        """Восстановиться из чекпоинта. Повреждённые поля → дефолты."""
        if not isinstance(data, dict):
            return
        self.active_language = data.get("active_language", "ru")
        if self.active_language not in {"ru", "en"}:
            self.active_language = "ru"
        self._language_states = {}
        # Старый checkpoint без подсекции означает пустую strategy-память,
        # а не сохранение случайного состояния прежней жизни.
        self.strategy_memory = DialogueStrategyMemory()
        buffer = data.get("buffer")
        if isinstance(buffer, dict):
            restored: Dict[str, dict] = {}
            for phrase, entry in list(buffer.items())[:BUFFER_MAX]:
                if not isinstance(entry, dict):
                    continue
                count = entry.get("count")
                if not isinstance(count, (int, float)) or isinstance(count, bool):
                    continue
                restored[str(phrase)] = {
                    "count": int(count),
                    "first_cycle": int(entry.get("first_cycle") or 0),
                    "last_cycle": int(entry.get("last_cycle") or 0),
                }
            self.buffer = restored
        learned = data.get("learned")
        if isinstance(learned, dict):
            restored_learned: Dict[str, dict] = {}
            for phrase, entry in learned.items():
                if not isinstance(entry, dict):
                    continue
                act = entry.get("act")
                if act not in LEARNABLE_ACTS:
                    continue
                restored_learned[str(phrase)] = {
                    "act": act,
                    "cycle": int(entry.get("cycle") or 0),
                }
            self.learned = restored_learned
        suppressed = data.get("suppressed")
        if isinstance(suppressed, dict):
            self.suppressed = {
                str(phrase): int(cycle)
                for phrase, cycle in suppressed.items()
                if isinstance(cycle, (int, float)) and not isinstance(cycle, bool)
            }
        learned_affect = data.get("learned_affect")
        if isinstance(learned_affect, dict):
            restored_affect: Dict[str, dict] = {}
            for raw_phrase, entry in list(learned_affect.items())[:LEARNED_AFFECT_MAX]:
                phrase = normalize_affect_phrase(raw_phrase)
                clean = restore_learned_affect(entry)
                if not phrase or len(phrase) > AFFECT_PHRASE_MAX_LEN or clean is None:
                    continue
                restored_affect[phrase] = clean
            self.learned_affect = restored_affect
        suppressed_affect = data.get("suppressed_affect")
        if isinstance(suppressed_affect, dict):
            restored_suppressed: Dict[str, int] = {}
            for raw_phrase, cycle in suppressed_affect.items():
                phrase = normalize_affect_phrase(raw_phrase)
                if (
                    not phrase
                    or isinstance(cycle, bool)
                    or not isinstance(cycle, (int, float))
                ):
                    continue
                try:
                    clean_cycle = int(cycle)
                except (TypeError, ValueError, OverflowError):
                    continue
                if clean_cycle >= 0:
                    restored_suppressed[phrase] = clean_cycle
            self.suppressed_affect = restored_suppressed
        strategies = data.get("dialogue_strategies")
        if isinstance(strategies, dict):
            self.strategy_memory.load_from(strategies)
        last = data.get("last_proposal_cycle")
        if isinstance(last, (int, float)) and not isinstance(last, bool):
            self.last_proposal_cycle = int(last)
        states = data.get("language_states")
        if isinstance(states, dict):
            for language_id, state in states.items():
                if (
                    language_id not in {"ru", "en"}
                    or language_id == self.active_language
                    or not isinstance(state, dict)
                ):
                    continue
                restored_state = DialogueLearning()
                restored_state.load_from(state)
                self._language_states[language_id] = restored_state._language_state()

    # === Внутреннее ===

    def _debug_snapshot(self) -> List[str]:
        """Фразы буфера для журналов (без содержания ответов)."""
        return sorted(self.buffer)
