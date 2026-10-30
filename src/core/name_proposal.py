"""Ограниченный разбор предложения имени без языковой модели."""

import re


_PREFIXES = (
    r"(?:привет[,!]?\s*)?(?:давай\s+)?твоим именем будет\s+",
    r"(?:привет[,!]?\s*)?(?:давай\s+)?(?:я\s+)?буду звать тебя\s+",
    r"(?:привет[,!]?\s*)?(?:давай\s+)?тебя будут звать\s+",
    r"(?:привет[,!]?\s*)?(?:давай\s+)?пусть тебя зовут\s+",
)


def extract_name_proposal(text):
    """Вернуть имя из известных фраз или None при неоднозначном сообщении."""
    value = str(text or "").strip()
    matched = False
    for prefix in _PREFIXES:
        match = re.fullmatch(prefix + r"(.+)", value, flags=re.IGNORECASE)
        if match:
            value = match.group(1)
            matched = True
            break
    if not matched and ("?" in value or len(value.split()) > 2):
        return None
    value = value.strip().rstrip(".!?").strip().strip('"\'«»').strip()
    if not re.fullmatch(r"[^\W\d_]+(?:[- ][^\W\d_]+){0,2}", value, flags=re.UNICODE):
        return None
    if value.casefold() in {"привет", "не знаю", "да", "нет", "как дела", "не уверен"}:
        return None
    return value if len(value) <= 30 else None
