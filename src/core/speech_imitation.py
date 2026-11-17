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

SCHEMA_VERSION = 1
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
    }
)


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _cycle(value, path="cycle"):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a nonnegative integer")


def normalize_expression(text) -> str:
    return " ".join(str(text or "").lower().split()).strip(" .!…")


def is_safe_expression(text, context) -> bool:
    """Допустить только короткую социальную формулу без утверждений."""
    expression = normalize_expression(text)
    if (
        context not in IMITATION_CONTEXTS
        or not expression
        or len(expression) > EXPRESSION_MAX_LEN
        or _SAFE_RE.fullmatch(expression) is None
        or social_reply_kind(expression) != context
        or expression not in _SAFE_EXPRESSIONS[context]
    ):
        return False
    return not _PRIVATE_OR_FACTUAL_MARKERS.intersection(expression.split())


def validate_speech_imitation(data) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        _fail("speech_imitation", "unsupported snapshot")
    expressions = data.get("expressions")
    if not isinstance(expressions, list) or len(expressions) > MAX_EXPRESSIONS:
        _fail("speech_imitation.expressions", "expected a bounded list")
    keys = set()
    for index, record in enumerate(expressions):
        path = f"speech_imitation.expressions[{index}]"
        if not isinstance(record, dict):
            _fail(path, "expected a dictionary")
        expression = record.get("expression")
        context = record.get("context")
        if not is_safe_expression(
            expression, context
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
        key = (expression, context, profile_id)
        if key in keys:
            _fail(path, "duplicate expression")
        keys.add(key)
    links = data.get("response_links")
    if not isinstance(links, dict) or len(links) > MAX_RESPONSE_LINKS:
        _fail("speech_imitation.response_links", "expected a bounded dictionary")
    known_expressions = {record["expression"] for record in expressions}
    for response_id, expression in links.items():
        if (
            not isinstance(response_id, str)
            or not response_id.strip()
            or len(response_id) > 160
            or expression not in known_expressions
        ):
            _fail("speech_imitation.response_links", "invalid response link")


class SpeechImitation:
    """Персональные речевые стратегии с отзываемыми переходами."""

    def __init__(self) -> None:
        self.expressions = {}
        self.response_links = {}

    @staticmethod
    def _key(expression, context, profile_id):
        return expression, context, profile_id

    def observe(self, text, *, context, profile_id, cycle) -> dict | None:
        expression = normalize_expression(text)
        _cycle(cycle)
        if not is_safe_expression(expression, context) or not profile_id:
            return None
        key = self._key(expression, context, profile_id)
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

    def candidate(self, *, context, profile_id, cycle) -> dict | None:
        """Вернуть доступный оборот без отметки использования."""
        _cycle(cycle)
        candidates = []
        for record in self.expressions.values():
            if (
                record["context"] != context
                or record["profile_id"] != profile_id
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

    def mark_used(self, expression, *, context, profile_id, response_id, cycle) -> dict:
        key = self._key(normalize_expression(expression), context, profile_id)
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
        self.response_links[response_id] = record["expression"]
        if len(self.response_links) > MAX_RESPONSE_LINKS:
            oldest = next(iter(self.response_links))
            del self.response_links[oldest]
        return deepcopy(record)

    def apply_feedback(
        self, response_id, feedback, *, profile_id, cycle
    ) -> dict | None:
        """Закрепить или отклонить только по явному отзыву на показанный ответ."""
        expression = self.response_links.pop(response_id, None)
        if expression is None or feedback not in {"support", "opposition"}:
            return None
        _cycle(cycle)
        matches = [
            record
            for record in self.expressions.values()
            if record["expression"] == expression and record["profile_id"] == profile_id
        ]
        if not matches:
            return None
        record = matches[0]
        self._add_evidence(record, {"kind": feedback, "cycle": cycle})
        if feedback == "opposition":
            record["status"] = "rejected"
        else:
            record["successful_uses"] += 1
            if record["successful_uses"] >= HABIT_MIN_SUCCESSES:
                record["level"] = "habit"
        return deepcopy(record)

    def reject(self, expression, *, context, profile_id, cycle) -> bool:
        key = self._key(normalize_expression(expression), context, profile_id)
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
            "response_links": dict(self.response_links),
        }

    def load_from(self, data) -> None:
        validate_speech_imitation(data)
        self.expressions = {
            self._key(
                record["expression"], record["context"], record["profile_id"]
            ): deepcopy(record)
            for record in data["expressions"]
        }
        self.response_links = dict(data["response_links"])
