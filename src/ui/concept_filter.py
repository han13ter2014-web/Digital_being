"""Какие записи ментальной модели показывать человеку как знание.

В Core концепциями становятся не только понятия, но и служебные метки,
внутренние утверждения тела и целые фразы пользователя. Прятать их из
карты — не значит удалять: Core продолжает на них опираться. Модуль лишь
решает, что честно показывать как «то, что ядро знает».

Правило простое и объяснимое: скрываем запись, если по её имени видно, что
это не тема для разговора, а техническая метка или дословная реплика.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Tuple

# Служебные утверждения самого Core о теле и начальной загрузке.
_SERVICE_PREFIXES = (
    "телесный опыт:",
    "телесный опыт：",
)

# Метки вида «убеждение_1», «убеждение_12»: внутренние установки без темы.
_BELIEF_MARKER = re.compile(r"^убеждение_\d+$", re.IGNORECASE)

# С чего начинается дословная реплика человека, а не название темы.
_UTTERANCE_OPENERS = (
    "привет",
    "здравствуй",
    "здравствуйте",
    "давай",
    "получается",
    "как ",
    "что ",
    "почему ",
    "зачем ",
    "кто ",
    "где ",
    "когда ",
)

# Местоимения, с которых начинается обращённая к кому-то фраза.
_ADDRESS_PRONOUNS = ("ты ", "вы ", "я ", "мы ")

_WORD = re.compile(r"[^\s]+")


def _word_count(name: str) -> int:
    return len(_WORD.findall(name))


def is_service_concept(name: Any) -> bool:
    """Служебная ли запись. Неизвестное имя остаётся видимым."""
    if not isinstance(name, str):
        return False
    text = " ".join(name.strip().split())
    if not text:
        return True
    lowered = text.casefold()

    if lowered.startswith(_SERVICE_PREFIXES):
        return True
    if _BELIEF_MARKER.fullmatch(lowered):
        return True
    # Имена, начинающиеся с подчёркивания, — внутренние маркеры.
    if text.startswith("_"):
        return True

    words = _word_count(text)
    # Одиночное слово — это тема, даже если оно вопросительное.
    if words < 3:
        return False

    # Знак вопроса или целая реплика с обращением: это не название темы.
    if "?" in text or "？" in text:
        return True
    if '"' in text or "«" in text:
        return True
    if "," in text:
        return True
    if lowered.startswith(_UTTERANCE_OPENERS):
        return True
    if lowered.startswith(_ADDRESS_PRONOUNS):
        return True
    return False


def split_service_concepts(
    concepts: Iterable[Tuple[str, Any]],
) -> Tuple[List[Tuple[str, Any]], int]:
    """Разделить концепции на видимые и служебные.

    Returns:
        (видимые пары «имя — узел», сколько служебных скрыто).
        Порядок видимых не меняется: отбор по объёму остаётся за картой.
    """
    visible: List[Tuple[str, Any]] = []
    hidden = 0
    for name, node in concepts:
        if is_service_concept(name):
            hidden += 1
        else:
            visible.append((name, node))
    return visible, hidden


__all__ = ["is_service_concept", "split_service_concepts"]
