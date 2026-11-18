"""Ограниченный языковой контекст диалога и его offline-разрешение.

Resolver по умолчанию сохраняет совместимый ``response_language=ru``.
Этап 9A-2 меняет его на ``en`` только после успешного входа в ограниченный
английский dialogue/fallback контур, не переписывая профильное предпочтение.
Этап 9B-1 добавляет Han-детекцию и ``zh`` в dialogue-метаданные. Этап 9B-2
разрешает ``response_language=zh`` только вместе с проверенной китайской
realization; сама Han-детекция по-прежнему не меняет язык ответа.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

INPUT_LANGUAGES = frozenset({"ru", "en", "zh", "mixed", "unknown"})
DIALOGUE_LANGUAGES = frozenset({"ru", "en", "zh"})
RESPONSE_LANGUAGES = frozenset({"ru", "en", "zh"})
LANGUAGE_SOURCES = frozenset(
    {"profile_preference", "stable_dialogue", "limited_detector", "legacy_default"}
)
LANGUAGE_STATE_SCHEMA_VERSION = 1
_PROFILE_ID_MAX_LEN = 160
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _language(value, path: str, *, allowed) -> str:
    if not isinstance(value, str) or value not in allowed:
        _fail(path, "unsupported language")
    return value


def detect_language(text) -> tuple[str, float]:
    """Определить только письменность; смысл и языковая поддержка не оцениваются."""
    if not isinstance(text, str):
        _fail("text", "expected a string")
    cleaned = _URL_RE.sub(" ", text)
    counts = {
        "ru": len(_CYRILLIC_RE.findall(cleaned)),
        "en": len(_LATIN_RE.findall(cleaned)),
        "zh": len(_HAN_RE.findall(cleaned)),
    }
    total = sum(counts.values())
    if total == 0:
        return "unknown", 0.0
    present = [count for count in counts.values() if count]
    if len(present) > 1:
        return "mixed", round(min(present) / total, 6)
    return next(language for language, count in counts.items() if count), 1.0


@dataclass(frozen=True)
class LanguageContext:
    profile_id: str
    input_language: str
    dialogue_language: str
    response_language: str
    source: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.profile_id, str)
            or not self.profile_id
            or len(self.profile_id) > _PROFILE_ID_MAX_LEN
        ):
            _fail("language_context.profile_id", "expected a bounded nonempty string")
        _language(
            self.input_language,
            "language_context.input_language",
            allowed=INPUT_LANGUAGES,
        )
        _language(
            self.dialogue_language,
            "language_context.dialogue_language",
            allowed=DIALOGUE_LANGUAGES,
        )
        _language(
            self.response_language,
            "language_context.response_language",
            allowed=RESPONSE_LANGUAGES,
        )
        if self.source not in LANGUAGE_SOURCES:
            _fail("language_context.source", "unsupported language source")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(
                self.confidence, (int, float)
            ):
                _fail("language_context.confidence", "expected a number or null")
            if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
                _fail("language_context.confidence", "expected a number from 0 to 1")

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "input_language": self.input_language,
            "dialogue_language": self.dialogue_language,
            "response_language": self.response_language,
            "source": self.source,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data, path="language_context") -> LanguageContext:
        if not isinstance(data, dict):
            _fail(path, "expected a dictionary")
        required = {
            "profile_id",
            "input_language",
            "dialogue_language",
            "response_language",
            "source",
            "confidence",
        }
        if set(data) != required:
            _fail(path, "expected exactly the versioned language context fields")
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError(f"{path}: invalid language context") from error


def validate_language_context(data, path="language_context") -> None:
    LanguageContext.from_dict(data, path)


def legacy_language_context(profile_id: str, *, input_language="ru") -> LanguageContext:
    """Совместимый русский контур без повторного угадывания старого текста."""
    return LanguageContext(
        profile_id=profile_id,
        input_language=input_language,
        dialogue_language="ru",
        response_language="ru",
        source="legacy_default",
        confidence=None,
    )


def default_language_state(*, legacy: bool) -> dict:
    return {
        "schema_version": LANGUAGE_STATE_SCHEMA_VERSION,
        "stable_dialogue_language": "ru" if legacy else None,
        "last_context": None,
    }


def validate_language_state(data, path="language") -> None:
    if not isinstance(data, dict):
        _fail(path, "expected a dictionary")
    if set(data) != {"schema_version", "stable_dialogue_language", "last_context"}:
        _fail(path, "expected exactly the versioned language state fields")
    if data.get("schema_version") != LANGUAGE_STATE_SCHEMA_VERSION:
        _fail(f"{path}.schema_version", "unsupported schema version")
    stable = data.get("stable_dialogue_language")
    if stable is not None:
        _language(
            stable,
            f"{path}.stable_dialogue_language",
            allowed=DIALOGUE_LANGUAGES,
        )
    last = data.get("last_context")
    if last is not None:
        validate_language_context(last, f"{path}.last_context")
        if stable != last["dialogue_language"]:
            _fail(
                f"{path}.last_context", "dialogue language does not match stable state"
            )


def resolve_language_context(
    text,
    *,
    profile_id: str,
    preferred_language=None,
    stable_dialogue_language=None,
    response_language="ru",
    legacy_default=False,
) -> tuple[LanguageContext, str]:
    """Разрешить контекст и вернуть новое устойчивое значение языка диалога."""
    if preferred_language is not None:
        _language(
            preferred_language,
            "preferred_language",
            allowed=DIALOGUE_LANGUAGES,
        )
    if stable_dialogue_language is not None:
        _language(
            stable_dialogue_language,
            "stable_dialogue_language",
            allowed=DIALOGUE_LANGUAGES,
        )
    _language(
        response_language,
        "response_language",
        allowed=RESPONSE_LANGUAGES,
    )
    input_language, detection_confidence = detect_language(text)
    if preferred_language is not None:
        dialogue = preferred_language
        source = "profile_preference"
        confidence = None
    elif legacy_default:
        dialogue = "ru"
        source = "legacy_default"
        confidence = None
    elif stable_dialogue_language is not None:
        dialogue = stable_dialogue_language
        source = "stable_dialogue"
        confidence = None
    elif input_language in DIALOGUE_LANGUAGES:
        dialogue = input_language
        source = "limited_detector"
        confidence = detection_confidence
    else:
        dialogue = "ru"
        source = "legacy_default"
        confidence = None
    context = LanguageContext(
        profile_id=profile_id,
        input_language=input_language,
        dialogue_language=dialogue,
        response_language=response_language,
        source=source,
        confidence=confidence,
    )
    return context, dialogue
