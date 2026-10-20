"""Фильтр качества записей базы знаний.

Отсекает то, что не является знанием:

* ключи-заглушки (``s_1``, ``test``, ``42``);
* служебные слова (``что``, ``такое``, ``меня``, ``ты``, ``?``);
* определения-заглушки Wikipedia («… may refer to:»);
* слишком короткие определения;
* нерелевантные результаты поиска.

Модуль намеренно не зависит от других частей проекта: его импортируют
и ``ThinkingPipeline``, и ``WebSearcher``, и подсистема знаний.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple


# Служебные слова: не могут быть отдельной «концепцией».
# «такое» — причина бага «что такое такое» (см. docs/BASELINE.md).
STOP_WORDS = frozenset({
    # местоимения
    'меня', 'тебя', 'себя', 'нас', 'вас', 'их', 'его', 'ее', 'мне', 'тебе',
    'себе', 'нам', 'вам', 'им', 'мной', 'тобой', 'собой', 'нами', 'вами', 'ими',
    'которой', 'которого', 'который', 'которые', 'которым', 'которую',
    'ты', 'я', 'он', 'она', 'оно', 'мы', 'вы', 'они',
    # вопрос и указатели
    'что', 'кто', 'где', 'когда', 'как', 'почему', 'зачем', 'какой', 'какая',
    'какие', 'каких', 'сколько', 'куда', 'откуда', 'чей', 'чья',
    'такое', 'такой', 'такая', 'такие', 'такого', 'таком', 'это', 'этот',
    'эта', 'эти', 'этого', 'этом', 'самый', 'самая', 'самое', 'самые',
    # частицы / наречия / предлоги
    'тут', 'там', 'здесь', 'сейчас', 'тогда', 'потом', 'всегда', 'никогда',
    'очень', 'можно', 'нужно', 'надо', 'есть', 'быть', 'был', 'была', 'было',
    'были', 'будет', 'чем', 'для', 'про', 'при', 'над', 'под', 'без', 'или',
    'либо', 'тоже', 'также', 'вообще', 'просто', 'уже', 'ещё', 'еще',
})

# Вопросительные обёртки, которые не являются частью имени концепции.
CONCEPT_PREFIXES = (
    "что такое ", "что значит ", "что означает ",
    "объясни ", "расскажи про ", "расскажи о ",
    "как работает ", "почему ",
)

# Признаки страницы-неоднозначности Wikipedia.
DISAMBIGUATION_MARKERS = (
    "may refer to",
    "может означать",
    "может относиться к",
)

# Ключи-заглушки: s_1, q42, test, tmp, 123.
PLACEHOLDER_RE = re.compile(
    r"^(?:[a-zа-я]?[_\-]?\d+|test\d*|tmp\d*|untitled|n/?a|none|null)$",
    re.IGNORECASE,
)

MIN_KEY_LEN = 2
MIN_DEFINITION_LEN = 15

# Коды причин отказа (для логов и tools/clean_kb.py).
REASON_TITLES = {
    "empty_key": "пустой ключ",
    "key_too_short": "слишком короткий ключ",
    "stop_word": "служебное слово",
    "no_letters": "в ключе нет букв",
    "placeholder": "заглушка",
    "empty_definition": "пустое определение",
    "definition_too_short": "слишком короткое определение",
    "disambiguation": "страница-неоднозначность",
}


def normalize_concept_name(raw: str) -> str:
    """Приводит запрос к имени концепции: «что такое счастье» → «счастье».

    Без этого в графе ментальных моделей появляются узлы-фразы
    («что такое счастье»), которые дублируют друг друга и не связываются
    с уже известными понятиями.
    """
    text = str(raw).strip().lower().rstrip("?.!,")
    for prefix in CONCEPT_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def check_entry(key: str, definition: str) -> Optional[str]:
    """Проверяет запись KB.

    Returns:
        ``None``, если запись осмысленная, иначе код причины
        (см. ``REASON_TITLES``).
    """
    text = str(key or "").strip().lower()
    if not text:
        return "empty_key"
    if text in STOP_WORDS:
        return "stop_word"
    if not any(ch.isalpha() for ch in text):
        return "no_letters"
    if len(text) < MIN_KEY_LEN:
        return "key_too_short"
    if PLACEHOLDER_RE.match(text):
        return "placeholder"

    body = str(definition or "").strip()
    if not body:
        return "empty_definition"
    if len(body) < MIN_DEFINITION_LEN:
        return "definition_too_short"
    if any(marker in body.lower() for marker in DISAMBIGUATION_MARKERS):
        return "disambiguation"
    return None


def is_valid_entry(key: str, definition: str) -> bool:
    return check_entry(key, definition) is None


def clean_knowledge_base(kb: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Возвращает ``(чистая_kb, {удалённый_ключ: причина})``."""
    clean: Dict[str, str] = {}
    removed: Dict[str, str] = {}
    for key, definition in (kb or {}).items():
        reason = check_entry(key, definition)
        if reason:
            removed[key] = reason
        else:
            clean[key] = definition
    return clean, removed


def meaningful_tokens(text: str) -> list[str]:
    """Слова запроса, которые могут быть содержательным понятием."""
    normalized = normalize_concept_name(text)
    tokens = [t for t in re.split(r"[^\wё-]+", normalized) if len(t) >= 2]
    return [t for t in tokens if t not in STOP_WORDS]


def is_worth_searching(query: str) -> bool:
    """Стоит ли вообще идти с этим запросом в интернет."""
    normalized = normalize_concept_name(query)
    if not normalized or len(normalized) < MIN_KEY_LEN:
        return False
    if PLACEHOLDER_RE.match(normalized):
        return False
    return bool(meaningful_tokens(normalized))


def is_valid_definition(definition: str) -> bool:
    body = str(definition or "").strip()
    if len(body) < MIN_DEFINITION_LEN:
        return False
    return not any(marker in body.lower() for marker in DISAMBIGUATION_MARKERS)


def is_relevant(query: str, title: str, extract: str) -> bool:
    """Есть ли в статье хоть одно содержательное слово запроса.

    Защита от случаев, когда Wikipedia на «?» или «s 1» отдаёт
    случайную статью.
    """
    tokens = meaningful_tokens(query)
    if not tokens:
        return False
    haystack = f"{title or ''} {extract or ''}".lower()
    return any(token in haystack for token in tokens)


__all__ = [
    "STOP_WORDS",
    "CONCEPT_PREFIXES",
    "DISAMBIGUATION_MARKERS",
    "MIN_KEY_LEN",
    "MIN_DEFINITION_LEN",
    "REASON_TITLES",
    "normalize_concept_name",
    "check_entry",
    "is_valid_entry",
    "clean_knowledge_base",
    "meaningful_tokens",
    "is_worth_searching",
    "is_valid_definition",
    "is_relevant",
]
