"""Детерминированные read-only мосты от вопроса к сохранённой памяти.

Запись знания и умение ответить о нём не должны быть разорваны.
Здесь нет генерации и новых вычислений смысла: только извлечение темы,
осторожное совпадение словоформ и цитирование уже существующих записей.
"""

from __future__ import annotations

import re
from typing import Optional

from src.core.dialogue_capabilities import capabilities_reply


_TOPIC_PATTERNS = (
    re.compile(
        r"^(?:что|чем)\s+(?:ты\s+)?(?:знаешь|помнишь)\s+"
        r"(?:про|о|об|обо)\s+(?P<topic>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^что\s+(?:такое|значит|означает)\s+(?P<topic>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:расскажи|объясни)(?:\s+мне)?\s+" r"(?:про|о|об|обо)\s+(?P<topic>.+)$",
        re.IGNORECASE,
    ),
)

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_NAME_FACT_MARKERS = (
    "помнишь",
    "выбрала",
    "выбрал",
    "когда",
    "почему",
    "зачем",
    "дата",
    "вчера",
    "сегодня",
    "назвала",
    "назвал",
)
_USER_FACT_MARKERS = ("обо мне", "про меня", "обо мне ты", "про меня ты")
_USER_FACT_VERBS = ("знаешь", "помнишь", "записала", "запомнила", "хранишь")


def _normalize(text) -> str:
    return " ".join(str(text or "").lower().replace("ё", "е").split())


def _clean_topic(text) -> str:
    topic = " ".join(str(text or "").strip().split())
    return topic.strip(" \t\r\n.!?,;:\"'«»„“”")


def question_topic(text) -> str:
    """Извлечь предмет вопроса из заранее ограниченных речевых форм."""
    normalized = " ".join(str(text or "").strip().split())
    normalized = re.sub(r"^(?:пожалуйста\s*,?\s*)", "", normalized, flags=re.IGNORECASE)
    for pattern in _TOPIC_PATTERNS:
        match = pattern.match(normalized)
        if match is not None:
            return _clean_topic(match.group("topic"))
    return ""


def _stem(word: str) -> str:
    """Небольшой детерминированный стеммер только для русских словоформ.

    Это не попытка понять смысл: короткие слова сравниваются целиком,
    а у длинных снимается один распространённый грамматический суффикс.
    """
    word = _normalize(word)
    if len(word) < 5:
        return word
    suffixes = (
        "ирования",
        "ированию",
        "ированием",
        "ировании",
        "ирование",
        "ениями",
        "ением",
        "ения",
        "ению",
        "ении",
        "ение",
        "овать",
        "ировать",
        "евать",
        "ывать",
        "ивать",
        "ать",
        "ять",
        "еть",
        "ить",
        "уть",
        "ыть",
        "ами",
        "ями",
        "ого",
        "его",
        "ому",
        "ему",
        "ыми",
        "ими",
        "ая",
        "яя",
        "ые",
        "ие",
        "ой",
        "ей",
        "ым",
        "им",
        "а",
        "я",
        "ы",
        "и",
        "у",
        "ю",
        "е",
        "о",
        "й",
        "ь",
    )
    for suffix in suffixes:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _roots(text) -> tuple:
    return tuple(_stem(word) for word in _WORD_RE.findall(_normalize(text)))


def _matched_name(topic: str, names) -> Optional[str]:
    names = [str(name) for name in names if str(name).strip()]
    normalized = _normalize(topic)
    exact = {_normalize(name): name for name in names}
    if normalized in exact:
        return exact[normalized]
    wanted = _roots(topic)
    if not wanted or any(len(root) < 4 for root in wanted):
        return None
    matches = [name for name in names if _roots(name) == wanted]
    if len(matches) == 1:
        return matches[0]
    # «Питон» и «питон» могут сосуществовать как разные ключи. После
    # нормализации это одна тема, а не неоднозначность.
    folded = {_normalize(name) for name in matches}
    if len(folded) == 1 and matches:
        return sorted(matches, key=lambda name: (len(name), name))[0]
    return None


def build_known_topic_reply(agent, text) -> Optional[str]:
    """Вернуть цитату сохранённого знания о спрошенной теме или None."""
    topic = question_topic(text)
    if not topic:
        return None
    definitions = getattr(agent, "_known_definitions", None)
    concepts = getattr(getattr(agent, "mental_models", None), "concepts", None)
    names = set(definitions) if isinstance(definitions, dict) else set()
    if isinstance(concepts, dict):
        names.update(concepts)
    matched = _matched_name(topic, names)
    if matched is None:
        return None

    node = concepts.get(matched) if isinstance(concepts, dict) else None
    if node is None and isinstance(concepts, dict):
        node = next(
            (
                value
                for key, value in concepts.items()
                if _normalize(key) == _normalize(matched)
            ),
            None,
        )
    if node is not None:
        testimony = next(
            (
                exp
                for exp in reversed(getattr(node, "experiences", []) or [])
                if isinstance(exp, dict)
                and exp.get("evidence_kind") == "testimony"
                and str(exp.get("outcome") or "").strip()
            ),
            None,
        )
        if testimony is not None:
            quote = " ".join(str(testimony["outcome"]).split())[:500]
            return f"Я помню запись про «{matched}» от тебя: «{quote}»."

    definition = ""
    if isinstance(definitions, dict):
        raw = definitions.get(matched)
        if raw is None:
            raw = next(
                (
                    value
                    for key, value in definitions.items()
                    if _normalize(key) == _normalize(matched)
                ),
                "",
            )
        definition = " ".join(str(raw or "").split())
    if definition:
        return f"По сохранённому определению про «{matched}»: {definition[:500]}"

    hypothesis = " ".join(str(getattr(node, "definition_hypothesis", "") or "").split())
    if hypothesis:
        return f"Моя сохранённая формулировка про «{matched}»: {hypothesis[:500]}"
    return None


def _capabilities_reply() -> str:
    return capabilities_reply()


def _name_fact_reply(agent, normalized: str) -> Optional[str]:
    if "имя" not in normalized or not any(
        marker in normalized for marker in _NAME_FACT_MARKERS
    ):
        return None
    name = str(getattr(agent, "name", "") or "").strip()
    if not name:
        return None
    naming = getattr(agent, "naming_dialogue", None)
    history = []
    if naming is not None and callable(getattr(naming, "get_name_history", None)):
        history = naming.get_name_history()
    latest = next(
        (
            entry
            for entry in reversed(history)
            if isinstance(entry, dict) and str(entry.get("new_name") or "") == name
        ),
        None,
    )
    parts = [f"Я помню: моё имя — {name}, оно сохранено в моём состоянии."]
    if latest is None:
        parts.append(
            "Записи о дате и причине выбора у меня нет — не буду их выдумывать."
        )
        return " ".join(parts)

    cycle = latest.get("cycle", latest.get("at_cycle"))
    source = str(latest.get("source") or "").strip()
    record_bits = []
    if isinstance(cycle, int) and not isinstance(cycle, bool):
        record_bits.append(f"цикл {cycle}")
    if source:
        record_bits.append(f"источник «{source}»")
    if record_bits:
        parts.append("В истории имени сохранены " + ", ".join(record_bits) + ".")

    date = next(
        (
            latest[key]
            for key in ("timestamp", "datetime", "date", "chosen_at")
            if latest.get(key)
        ),
        None,
    )
    reason = str(latest.get("reason") or "").strip()
    if date:
        parts.append(f"Дата в записи: {date}.")
    else:
        parts.append("Календарная дата выбора не сохранена.")
    if reason:
        parts.append(f"Причина в записи: {reason}.")
    else:
        parts.append("Причина выбора не сохранена — я не стану её придумывать.")
    return " ".join(parts)


def _user_fact_reply(agent, normalized: str) -> Optional[str]:
    if not any(marker in normalized for marker in _USER_FACT_MARKERS):
        return None
    if not any(marker in normalized for marker in _USER_FACT_VERBS):
        return None
    user_model = getattr(agent, "user_model", None)
    if user_model is None:
        return "У меня пока нет сохранённых записей о тебе."
    facts = []
    traits = getattr(user_model, "traits", None)
    if isinstance(traits, dict):
        facts.extend(
            str(value).strip() for value in traits.values() if str(value).strip()
        )
    promises = getattr(user_model, "promises", None)
    if isinstance(promises, dict):
        facts.extend(
            str(entry.get("text") or "").strip()
            for entry in promises.values()
            if isinstance(entry, dict) and str(entry.get("text") or "").strip()
        )
    facts = list(dict.fromkeys(facts))
    if not facts:
        return "У меня пока нет сохранённых записей о тебе."
    quoted = "; ".join(f"«{fact[:150]}»" for fact in facts[:5])
    return f"Я сохранила о тебе: {quoted}."


def build_persistent_fact_reply(agent, text) -> Optional[str]:
    """Ответить из персистентных фактов, ничего не реконструируя."""
    normalized = _normalize(text)
    if not normalized:
        return None
    if (
        "что ты умеешь" in normalized
        or "что ты можешь" in normalized
        or "какие просьбы" in normalized
        or "какие команды" in normalized
    ):
        return _capabilities_reply()
    name_reply = _name_fact_reply(agent, normalized)
    if name_reply is not None:
        return name_reply
    return _user_fact_reply(agent, normalized)


# Т5: рабочая память — не полная история чата, а несколько последних
# завершённых реплик с провенансом. Она позволяет разрешать только короткую
# анафору без собственного предмета и не порождает новых знаний о мире.
DIALOGUE_ACT_RING_SIZE = 5
DIALOGUE_ACT_TTL_CYCLES = 50

_ANAPHORA_RE = re.compile(
    r"^(?:а\s+)?(?P<marker>почему|зачем|кто)\s*[?!.…]*$",
    re.IGNORECASE,
)
_RESOLVABLE_ACT_KINDS = frozenset(
    {
        "about_self",
        "persistent_fact",
        "known_topic",
        "user_definition",
        "user_answer",
        "open_question_answer",
        "follow_up",
    }
)


def anaphora_marker(text) -> str:
    """Вернуть маркер короткой анафоры или пустую строку.

    «Почему небо голубое?» сюда не входит: у вопроса есть собственный
    предмет, и он должен пройти прежний путь классификации и обучения.
    """
    normalized = " ".join(str(text or "").strip().split())
    match = _ANAPHORA_RE.match(normalized)
    return match.group("marker").lower() if match is not None else ""


def _cycle_number(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _clean_text(value, limit=1000) -> str:
    return " ".join(str(value or "").split())[:limit]


class DialogueActRing:
    """Кольцо последних N актов с TTL и безопасным восстановлением."""

    def __init__(self, size=DIALOGUE_ACT_RING_SIZE, ttl=DIALOGUE_ACT_TTL_CYCLES):
        self.size = int(size)
        self.ttl = int(ttl)
        self._acts = []

    def record(
        self,
        kind,
        *,
        topic="",
        entities=(),
        cycle=0,
        user_text="",
        agent_text="",
        affect=None,
    ) -> None:
        kind = _clean_text(kind, 80)
        agent_text = _clean_text(agent_text)
        if not kind or not agent_text:
            return
        if not isinstance(entities, (list, tuple)):
            entities = ()
        clean_entities = list(
            dict.fromkeys(
                _clean_text(entity, 240)
                for entity in entities
                if _clean_text(entity, 240)
            )
        )[:10]
        if affect is not None:
            from src.core.human_affect import restore_affect

            affect = restore_affect(affect, include_metadata=True)
        entry = {
            "kind": kind,
            "topic": _clean_text(topic, 240),
            "entities": clean_entities,
            "cycle": _cycle_number(cycle),
            "user_text": _clean_text(user_text),
            "agent_text": agent_text,
        }
        if affect is not None:
            entry["affect"] = affect
        self._acts.append(entry)
        self._acts = self._acts[-self.size :]

    @staticmethod
    def _copy_entry(entry):
        copied = dict(entry, entities=list(entry["entities"]))
        if "affect" in entry:
            copied["affect"] = dict(
                entry["affect"], components=dict(entry["affect"]["components"])
            )
        return copied

    def snapshot(self) -> list:
        """Независимая копия для чтения и сериализации."""
        return [self._copy_entry(entry) for entry in self._acts]

    def restore(self, data) -> None:
        """Восстановить только валидные дескрипторы; старое поле → пусто."""
        self._acts = []
        if not isinstance(data, list):
            return
        for entry in data[-self.size :]:
            if not isinstance(entry, dict):
                continue
            kind = _clean_text(entry.get("kind"), 80)
            agent_text = _clean_text(entry.get("agent_text"))
            cycle = entry.get("cycle")
            if (
                not kind
                or not agent_text
                or isinstance(cycle, bool)
                or not isinstance(cycle, int)
                or cycle < 0
            ):
                continue
            self.record(
                kind,
                topic=entry.get("topic", ""),
                entities=entry.get("entities", ()),
                cycle=cycle,
                user_text=entry.get("user_text", ""),
                agent_text=agent_text,
                affect=entry.get("affect"),
            )

    def fresh_acts(self, cycle, limit=3) -> list:
        """Свежие акты newest-first с transient attention-весами."""
        from src.core.human_affect import AFFECT_ATTENTION_WEIGHTS

        current = _cycle_number(cycle)
        limit = max(0, int(limit))
        if limit == 0:
            return []
        fresh = []
        for entry in reversed(self._acts):
            age = current - entry["cycle"]
            if age < 0 or age > self.ttl:
                continue
            copied = self._copy_entry(entry)
            index = len(fresh)
            copied["attention"] = AFFECT_ATTENTION_WEIGHTS[
                min(index, len(AFFECT_ATTENTION_WEIGHTS) - 1)
            ]
            fresh.append(copied)
            if len(fresh) >= limit:
                break
        return fresh

    def _fresh_candidate(self, cycle):
        if not self._acts:
            return None
        candidate = self._acts[-1]
        age = _cycle_number(cycle) - candidate["cycle"]
        if age < 0 or age > self.ttl:
            return None
        return candidate

    def resolve(self, text, cycle):
        """Разрешить анафору только в поддержанный свежий акт."""
        if not anaphora_marker(text):
            return None
        candidate = self._fresh_candidate(cycle)
        if candidate is None or candidate["kind"] not in _RESOLVABLE_ACT_KINDS:
            return None
        return dict(candidate, entities=list(candidate["entities"]))

    def clarification_candidate(self, text, cycle):
        """Свежий кандидат для честного вопроса о референте, без разрешения."""
        if not anaphora_marker(text):
            return None
        candidate = self._fresh_candidate(cycle)
        if candidate is None:
            return None
        return dict(candidate, entities=list(candidate["entities"]))


def build_follow_up_reply(text, act) -> str:
    """Ответить только метаданными прошлого акта, без выдуманной причины."""
    marker = anaphora_marker(text) or "этот вопрос"
    topic = act.get("topic", "")
    previous = act.get("agent_text", "")
    if act.get("kind") == "user_definition" and topic:
        return (
            f"Вопрос «{marker}» относится к записи про «{topic}». "
            "Я сохранила её как твоё свидетельство, а не как безусловный факт. "
            f"Моя предыдущая реплика: «{previous}»."
        )
    subject = f" про «{topic}»" if topic else ""
    return (
        f"Ты спрашиваешь «{marker}» о моей предыдущей реплике{subject}: "
        f"«{previous}». Она построена только из записанного состояния и "
        "свидетельств; более глубокую причину я из неё не вывожу."
    )


def build_follow_up_clarification(text, candidate=None) -> str:
    """Уточнить референт, не превращая анафору в неизвестную фразу."""
    question = _clean_text(text, 80)
    if candidate is None:
        return (
            f"Я вижу короткий вопрос «{question}», но его референт не сохранён. "
            "О чём именно ты спрашиваешь?"
        )
    previous = candidate.get("agent_text", "")
    return (
        f"Я не могу однозначно связать «{question}». В предыдущей реплике "
        f"сказано: «{previous}». Уточни, что именно в ней объяснить?"
    )
