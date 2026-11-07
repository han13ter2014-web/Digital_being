"""
DialogueLearning — саморазвитие диалоговых таблиц («Собеседник-7»).

До этой ступени таблицы маркеров в dialogue_acts.py расширял только
разработчик: живая речь богаче любой рукописной таблицы, и каждая
нераспознанная фраза («Не нашел файл для…» → честный отклик) оставалась
мертвой зоной навсегда. В user_model.py и dialogue_acts.py это будущее
было прямо зафиксировано: «включая возможное саморазвитие таблиц самой
сущностью».

Граница субъектности: сущность НЕ выдумывает маркеры сама. Человек —
учитель: фраза становится маркером только после явного подтверждения
пользователя через вопрос-уточнение. Детерминизм сохранён: обученные
маркеры — литеральные подстроки, ведущие только на существующие акты
(social / about_self / request) с их детерминированными честными
ответами. ACT_ANSWER сознательно исключён: выученный «ответ» смог бы
закрывать настоящие вопросы сущности мусором — это единственный акт,
который пишет в знания, а обучение не должно создавать новых
генераторов поведения. Слова пользователя пишутся только в таблицы
распознавания речи (факт о речи человека), не в ценности и мотивацию.

Приоритет: статические рукописные таблицы всегда сильнее обученных —
обученное заполняет пробелы, а не перекрывает решения разработчика.

Сериализуется в чекпоинт (секция dialogue_learning): после рестарта
выученное не забывается.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.core.dialogue_acts import (
    ACT_ASK_ABOUT_SELF,
    ACT_REQUEST,
    ACT_SOCIAL,
    is_noise_input,
)

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

# Префикс контекста pending-вопроса: по нему runner узнаёт, что ответ
# пользователя — обучающий, а не обычный.
PROPOSAL_CONTEXT_PREFIX = "dialogue_learning: "

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
        # нормализованная фраза → {"count", "first_cycle", "last_cycle"}
        self.buffer: Dict[str, dict] = {}
        # нормализованная фраза → {"act": kind, "cycle": int}
        self.learned: Dict[str, dict] = {}
        # нормализованная фраза → cycle запрета («4 — не учить»).
        # Запрет навсегда: coping с отказом без бесконечного переспроса.
        self.suppressed: Dict[str, int] = {}
        self.last_proposal_cycle: int = -PROPOSAL_COOLDOWN_CYCLES

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
        """Фраза для уточнения с первого входа (K13), без автообучения.

        Порог повторов в ``observe`` остаётся прежним и нужен старому
        контуру. Здесь проверяются только запреты и кулдаун: категорию
        спрашиваем сразу, но маркер по-прежнему возникает лишь после
        явного ответа человека в ``resolve``.
        """
        phrase = normalize_phrase(text)
        if (
            not phrase
            or is_noise_input(phrase)
            or phrase in self.learned
            or phrase in self.suppressed
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
        if phrase in self.learned or phrase in self.suppressed:
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
        displayed = phrase if len(phrase) <= PHRASE_MAX_LEN else phrase[: PHRASE_MAX_LEN - 1] + "…"
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

    # === Забвение ===

    def forget(self, phrase) -> bool:
        """Забыть выученную фразу («забудь фразу X»). True, если была."""
        normalized = normalize_phrase(phrase)
        if normalized in self.learned:
            del self.learned[normalized]
            self.suppressed[normalized] = 0
            return True
        return False

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
        }

    # === Сериализация ===

    def to_dict(self) -> dict:
        return {
            "buffer": {phrase: dict(entry) for phrase, entry in self.buffer.items()},
            "learned": {phrase: dict(entry) for phrase, entry in self.learned.items()},
            "suppressed": dict(self.suppressed),
            "last_proposal_cycle": self.last_proposal_cycle,
        }

    def load_from(self, data) -> None:
        """Восстановиться из чекпоинта. Повреждённые поля → дефолты."""
        if not isinstance(data, dict):
            return
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
        last = data.get("last_proposal_cycle")
        if isinstance(last, (int, float)) and not isinstance(last, bool):
            self.last_proposal_cycle = int(last)

    # === Внутреннее ===

    def _debug_snapshot(self) -> List[str]:
        """Фразы буфера для журналов (без содержания ответов)."""
        return sorted(self.buffer)
