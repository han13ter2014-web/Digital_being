"""Три проверяемых уровня заимствования безопасных социальных оборотов.

Распознавание не даёт права использовать оборот. Повторные наблюдения
переводят его в ситуативное пробование, а несколько явных положительных
отзывов на фактически показанные ответы — в собственную привычку. Явное
отклонение отзывает оборот. Факты, ценности, разрешения и чужие переживания
не копируются.
"""

from __future__ import annotations

import re
from copy import deepcopy

from src.core.dialogue_acts import social_reply_kind

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
LANGUAGES = frozenset({"ru", "en"})
LEVELS = frozenset({"recognized", "situational", "habit"})
STATUSES = frozenset({"active", "rejected"})
IMITATION_CONTEXTS = frozenset({"greeting", "state", "other"})
MAX_EXPRESSIONS = 80
MAX_PROVENANCE = 12
MAX_RESPONSE_LINKS = 20
EXPRESSION_MAX_LEN = 60
PROFILE_ID_MAX_LEN = 160
SITUATIONAL_MIN_OBSERVATIONS = 2
HABIT_MIN_SUCCESSES = 2
USE_COOLDOWN_CYCLES = 20

_SAFE_RE = re.compile(r"^[^\W\d_]+(?:\s+[^\W\d_]+)*$", re.UNICODE)
# Только формулы без утверждений о фактах, личности или переживаниях.
# Распознавание других социальных реплик остаётся возможным, но их текст
# не становится материалом для повторения от имени сущности.
_SAFE_EXPRESSIONS = {
    "greeting": frozenset(
        {
            "привет",
            "здравствуй",
            "здравствуйте",
            "доброе утро",
            "добрый день",
            "добрый вечер",
            "доброй ночи",
        }
    ),
    "state": frozenset({"как дела", "как настроение"}),
    "other": frozenset({"не переживай", "не волнуйся", "молодец"}),
}
_SAFE_EXPRESSIONS_EN = {
    "greeting": frozenset({"hello", "hi", "good morning", "good evening"}),
    "state": frozenset({"how are you"}),
    "other": frozenset({"thank you", "well done"}),
}
_PRIVATE_OR_FACTUAL_MARKERS = frozenset(
    {
        "я",
        "мне",
        "меня",
        "мой",
        "моя",
        "моё",
        "мы",
        "нас",
        "ты",
        "тебе",
        "тебя",
        "твой",
        "твоя",
        "знаю",
        "помню",
        "чувствую",
        "люблю",
        "ненавижу",
        "i",
        "me",
        "my",
        "mine",
        "we",
        "our",
        "you",
        "your",
        "yours",
        "know",
        "remember",
        "feel",
        "love",
        "hate",
    }
)


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _cycle(value, path="cycle"):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a nonnegative integer")


def normalize_expression(text) -> str:
    return " ".join(str(text or "").lower().split()).strip(" .!…")


def is_safe_expression(text, context, language_id="ru") -> bool:
    """Допустить только короткую социальную формулу активного языка."""
    expression = normalize_expression(text)
    if language_id not in LANGUAGES:
        return False
    safe_expressions = (
        _SAFE_EXPRESSIONS_EN if language_id == "en" else _SAFE_EXPRESSIONS
    )
    if (
        context not in IMITATION_CONTEXTS
        or not expression
        or len(expression) > EXPRESSION_MAX_LEN
        or _SAFE_RE.fullmatch(expression) is None
        or expression not in safe_expressions[context]
    ):
        return False
    if language_id == "ru" and social_reply_kind(expression) != context:
        return False
    return not _PRIVATE_OR_FACTUAL_MARKERS.intersection(expression.split())


def validate_speech_imitation(data) -> None:
    if not isinstance(data, dict):
        _fail("speech_imitation", "unsupported snapshot")
    schema_version = data.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        _fail("speech_imitation", "unsupported snapshot")
    expressions = data.get("expressions")
    if not isinstance(expressions, list) or len(expressions) > MAX_EXPRESSIONS:
        _fail("speech_imitation.expressions", "expected a bounded list")
    keys = set()
    known_pairs = set()
    known_triples = set()
    for index, record in enumerate(expressions):
        path = f"speech_imitation.expressions[{index}]"
        if not isinstance(record, dict):
            _fail(path, "expected a dictionary")
        language_id = record.get("language_id", "ru")
        if schema_version >= 2 and "language_id" not in record:
            _fail(f"{path}.language_id", "required in schema version 2")
        if language_id not in LANGUAGES:
            _fail(f"{path}.language_id", "unsupported language")
        expression = record.get("expression")
        context = record.get("context")
        if not is_safe_expression(
            expression, context, language_id
        ) or expression != normalize_expression(expression):
            _fail(f"{path}.expression", "unsafe or non-normalized expression")
        profile_id = record.get("profile_id")
        if (
            not isinstance(profile_id, str)
            or not profile_id
            or len(profile_id) > PROFILE_ID_MAX_LEN
        ):
            _fail(f"{path}.profile_id", "expected a bounded nonempty string")
        if record.get("level") not in LEVELS or record.get("status") not in STATUSES:
            _fail(path, "unknown level or status")
        for field in ("observations", "uses", "successful_uses"):
            value = record.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _fail(f"{path}.{field}", "expected a nonnegative integer")
        for field in ("created_cycle", "last_observed_cycle"):
            _cycle(record.get(field), f"{path}.{field}")
        last_used = record.get("last_used_cycle")
        if last_used is not None:
            _cycle(last_used, f"{path}.last_used_cycle")
        provenance = record.get("provenance")
        if (
            not isinstance(provenance, list)
            or not 1 <= len(provenance) <= MAX_PROVENANCE
        ):
            _fail(f"{path}.provenance", "expected bounded provenance")
        for source_index, source in enumerate(provenance):
            source_path = f"{path}.provenance[{source_index}]"
            if not isinstance(source, dict) or source.get("kind") not in {
                "observation",
                "support",
                "opposition",
                "rejected",
            }:
                _fail(source_path, "unknown evidence")
            _cycle(source.get("cycle"), f"{source_path}.cycle")
        key = (expression, context, profile_id, language_id)
        if key in keys:
            _fail(path, "duplicate expression")
        keys.add(key)
        known_pairs.add((expression, language_id))
        known_triples.add((expression, context, language_id))
    links = data.get("response_links")
    if not isinstance(links, dict) or len(links) > MAX_RESPONSE_LINKS:
        _fail("speech_imitation.response_links", "expected a bounded dictionary")
    for response_id, link in links.items():
        if (
            not isinstance(response_id, str)
            or not response_id.strip()
            or len(response_id) > 160
        ):
            _fail("speech_imitation.response_links", "invalid response link")
        if isinstance(link, str):
            pair = (link, "ru")
            if pair not in known_pairs:
                _fail("speech_imitation.response_links", "invalid response link")
            continue
        if not isinstance(link, dict) or set(link) - {
            "expression",
            "context",
            "language_id",
        }:
            _fail("speech_imitation.response_links", "invalid response link")
        pair = (link.get("expression"), link.get("language_id"))
        triple = (link.get("expression"), link.get("context"), link.get("language_id"))
        if pair not in known_pairs or (
            "context" in link and triple not in known_triples
        ):
            _fail("speech_imitation.response_links", "invalid response link")


class SpeechImitation:
    """Персональные речевые стратегии с отзываемыми переходами."""

    def __init__(self) -> None:
        self.expressions = {}
        self.response_links = {}

    @staticmethod
    def _key(expression, context, profile_id, language_id="ru"):
        # Трёхчастный русский ключ сохранён для обратной совместимости API.
        if language_id == "ru":
            return expression, context, profile_id
        return expression, context, profile_id, language_id

    def observe(
        self, text, *, context, profile_id, cycle, language_id="ru"
    ) -> dict | None:
        expression = normalize_expression(text)
        _cycle(cycle)
        if not is_safe_expression(expression, context, language_id) or not profile_id:
            return None
        key = self._key(expression, context, profile_id, language_id)
        record = self.expressions.get(key)
        if record is None:
            if len(self.expressions) >= MAX_EXPRESSIONS:
                oldest = min(
                    self.expressions,
                    key=lambda item: (
                        self.expressions[item]["status"] == "active",
                        self.expressions[item]["last_observed_cycle"],
                        item,
                    ),
                )
                del self.expressions[oldest]
            record = {
                "expression": expression,
                "context": context,
                "profile_id": profile_id,
                "language_id": language_id,
                "level": "recognized",
                "status": "active",
                "observations": 0,
                "uses": 0,
                "successful_uses": 0,
                "created_cycle": cycle,
                "last_observed_cycle": cycle,
                "last_used_cycle": None,
                "provenance": [],
            }
            self.expressions[key] = record
        evidence = {"kind": "observation", "cycle": cycle}
        if evidence not in record["provenance"]:
            record["observations"] += 1
            self._add_evidence(record, evidence)
        record["last_observed_cycle"] = max(record["last_observed_cycle"], cycle)
        if (
            record["status"] == "active"
            and record["level"] == "recognized"
            and record["observations"] >= SITUATIONAL_MIN_OBSERVATIONS
        ):
            record["level"] = "situational"
        return deepcopy(record)

    @staticmethod
    def _add_evidence(record, evidence) -> None:
        record["provenance"] = (record["provenance"] + [evidence])[-MAX_PROVENANCE:]

    def candidate(self, *, context, profile_id, cycle, language_id="ru") -> dict | None:
        """Вернуть доступный оборот только запрошенного языка."""
        _cycle(cycle)
        candidates = []
        for record in self.expressions.values():
            if (
                record["context"] != context
                or record["profile_id"] != profile_id
                or record.get("language_id", "ru") != language_id
                or record["status"] != "active"
                or record["level"] == "recognized"
            ):
                continue
            last_used = record["last_used_cycle"]
            if last_used is not None and 0 <= cycle - last_used < USE_COOLDOWN_CYCLES:
                continue
            candidates.append(record)
        if not candidates:
            return None
        selected = min(
            candidates,
            key=lambda record: (
                record["level"] != "habit",
                -record["successful_uses"],
                record["expression"],
            ),
        )
        return deepcopy(selected)

    def mark_used(
        self,
        expression,
        *,
        context,
        profile_id,
        response_id,
        cycle,
        language_id="ru",
    ) -> dict:
        key = self._key(
            normalize_expression(expression), context, profile_id, language_id
        )
        record = self.expressions.get(key)
        if (
            record is None
            or record["status"] != "active"
            or record["level"] == "recognized"
        ):
            raise ValueError("expression is not available for use")
        if not isinstance(response_id, str) or not response_id.strip():
            raise ValueError("response_id")
        _cycle(cycle)
        record["uses"] += 1
        record["last_used_cycle"] = cycle
        if language_id == "ru":
            self.response_links[response_id] = record["expression"]
        else:
            self.response_links[response_id] = {
                "expression": record["expression"],
                "context": context,
                "language_id": language_id,
            }
        if len(self.response_links) > MAX_RESPONSE_LINKS:
            oldest = next(iter(self.response_links))
            del self.response_links[oldest]
        return deepcopy(record)

    def apply_feedback(
        self, response_id, feedback, *, profile_id, cycle, language_id=None
    ) -> dict | None:
        """Закрепить или отклонить только отзыв на ответ того же языка."""
        link = self.response_links.get(response_id)
        if link is None or feedback not in {"support", "opposition"}:
            return None
        if isinstance(link, str):
            expression = link
            link_language = "ru"
            link_context = None
        else:
            expression = link["expression"]
            link_language = link["language_id"]
            link_context = link.get("context")
        if language_id is not None and link_language != language_id:
            return None
        _cycle(cycle)
        matches = [
            record
            for record in self.expressions.values()
            if record["expression"] == expression
            and record["profile_id"] == profile_id
            and record.get("language_id", "ru") == link_language
            and (link_context is None or record["context"] == link_context)
        ]
        if not matches:
            return None
        del self.response_links[response_id]
        record = matches[0]
        self._add_evidence(record, {"kind": feedback, "cycle": cycle})
        if feedback == "opposition":
            record["status"] = "rejected"
        else:
            record["successful_uses"] += 1
            if record["successful_uses"] >= HABIT_MIN_SUCCESSES:
                record["level"] = "habit"
        return deepcopy(record)

    def reject(
        self, expression, *, context, profile_id, cycle, language_id="ru"
    ) -> bool:
        key = self._key(
            normalize_expression(expression), context, profile_id, language_id
        )
        record = self.expressions.get(key)
        if record is None:
            return False
        _cycle(cycle)
        record["status"] = "rejected"
        self._add_evidence(record, {"kind": "rejected", "cycle": cycle})
        return True

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "expressions": [
                deepcopy(self.expressions[key]) for key in sorted(self.expressions)
            ],
            "response_links": deepcopy(self.response_links),
        }

    def load_from(self, data) -> None:
        validate_speech_imitation(data)
        self.expressions = {}
        for original in data["expressions"]:
            record = deepcopy(original)
            record.setdefault("language_id", "ru")
            key = self._key(
                record["expression"],
                record["context"],
                record["profile_id"],
                record["language_id"],
            )
            self.expressions[key] = record
        self.response_links = deepcopy(data["response_links"])
