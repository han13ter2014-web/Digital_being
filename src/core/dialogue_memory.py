"""Детерминированные read-only мосты от вопроса к сохранённой памяти.

K13: запись знания и умение ответить о нём не должны быть разорваны.
Здесь нет генерации и новых вычислений смысла: только извлечение темы,
осторожное совпадение словоформ и цитирование уже существующих записей.
"""
from __future__ import annotations

import re
from typing import Optional


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
        r"^(?:расскажи|объясни)(?:\s+мне)?\s+"
        r"(?:про|о|об|обо)\s+(?P<topic>.+)$",
        re.IGNORECASE,
    ),
)

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_NAME_FACT_MARKERS = (
    "помнишь", "выбрала", "выбрал", "когда", "почему", "зачем",
    "дата", "вчера", "сегодня", "назвала", "назвал",
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
        "ирования", "ированию", "ированием", "ировании", "ирование",
        "ениями", "ением", "ения", "ению", "ении", "ение",
        "овать", "ировать", "евать", "ывать", "ивать",
        "ать", "ять", "еть", "ить", "уть", "ыть",
        "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими",
        "ая", "яя", "ые", "ие", "ой", "ей", "ым", "им",
        "а", "я", "ы", "и", "у", "ю", "е", "о", "й", "ь",
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
    exact = { _normalize(name): name for name in names }
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
            (value for key, value in concepts.items() if _normalize(key) == _normalize(matched)),
            None,
        )
    if node is not None:
        testimony = next(
            (
                exp for exp in reversed(getattr(node, "experiences", []) or [])
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
                (value for key, value in definitions.items() if _normalize(key) == _normalize(matched)),
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
    return (
        "Из просьб я умею: рассказать о себе; процитировать сохранённое знание "
        "о теме; запомнить твоё объяснение в форме «X — это Y»; принять ответ "
        "на свой вопрос и уточнить непонятную реплику. Если просьба мне "
        "недоступна, я честно скажу об этом, а не стану выдумывать результат."
    )


def _name_fact_reply(agent, normalized: str) -> Optional[str]:
    if "имя" not in normalized or not any(marker in normalized for marker in _NAME_FACT_MARKERS):
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
            entry for entry in reversed(history)
            if isinstance(entry, dict) and str(entry.get("new_name") or "") == name
        ),
        None,
    )
    parts = [f"Я помню: моё имя — {name}, оно сохранено в моём состоянии."]
    if latest is None:
        parts.append("Записи о дате и причине выбора у меня нет — не буду их выдумывать.")
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
        (latest[key] for key in ("timestamp", "datetime", "date", "chosen_at") if latest.get(key)),
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
        facts.extend(str(value).strip() for value in traits.values() if str(value).strip())
    promises = getattr(user_model, "promises", None)
    if isinstance(promises, dict):
        facts.extend(
            str(entry.get("text") or "").strip()
            for entry in promises.values() if isinstance(entry, dict)
            and str(entry.get("text") or "").strip()
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
