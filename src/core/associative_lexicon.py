"""Ограниченный ассоциативный лексикон речевого опыта.

Лексикон связывает нормализованные слова и обороты с уже существующими
актами, понятиями, контекстами и реальными эпизодами. Он только предлагает
кандидатов распознавания: ``classify_user_text`` и Core choice его не читают.

Личные записи принадлежат конкретному профилю и переключаются через
``SocialAttribution``. Общие записи создаются только отдельным явным вызовом;
наблюдение одного человека никогда не попадает в общий лексикон автоматически.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Callable, Optional

from src.core.dialogue_acts import (
    ACT_ANSWER,
    ACT_ASK_ABOUT_SELF,
    ACT_FOLLOW_UP,
    ACT_HUMAN_AFFECT,
    ACT_REQUEST,
    ACT_SOCIAL,
    ACT_UNKNOWN,
)

SCHEMA_VERSION = 1
TARGET_KINDS = frozenset({"act", "concept", "context", "episode"})
ASSOCIATION_SCOPES = frozenset({"personal", "shared"})
PROVENANCE_SOURCES = frozenset({"observed_act", "user_taught", "explicit"})
ASSOCIABLE_ACTS = frozenset(
    {
        ACT_ANSWER,
        ACT_ASK_ABOUT_SELF,
        ACT_FOLLOW_UP,
        ACT_HUMAN_AFFECT,
        ACT_REQUEST,
        ACT_SOCIAL,
    }
)

MAX_RECORDS = 400
MAX_PROVENANCE = 8
EXPRESSION_MAX_LEN = 120
TARGET_ID_MAX_LEN = 160
PROFILE_ID_MAX_LEN = 160
MAX_OBSERVED_TOKENS = 8
DECAY_PER_CYCLE = 0.002
MIN_CONFIDENCE = 0.05

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_OBSERVED_STOPWORDS = frozenset(
    {"это", "что", "как", "для", "или", "мне", "тебе", "тебя", "меня"}
)


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _cycle(value, path: str = "cycle") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a nonnegative integer")
    return value


def _confidence(value, path: str = "confidence") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "expected a finite number")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        _fail(path, "expected a number in [0, 1]")
    return value


def normalize_expression(text) -> str:
    """Сопоставимая форма выражения без изменения смысловых слов."""
    return " ".join(str(text or "").lower().split())


def _words(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(normalize_expression(text)))


def _observed_tokens(text: str) -> tuple[str, ...]:
    result = []
    for token in _WORD_RE.findall(normalize_expression(text)):
        if len(token) < 4 or token in _OBSERVED_STOPWORDS or token in result:
            continue
        result.append(token)
        if len(result) >= MAX_OBSERVED_TOKENS:
            break
    return tuple(result)


def _record_key(record: dict) -> tuple[str, str, str]:
    return record["expression"], record["target_kind"], record["target_id"]


def validate_associative_lexicon(data, *, expected_scope: Optional[str] = None) -> None:
    """Проверить весь снапшот до изменения живого лексикона."""
    if not isinstance(data, dict):
        _fail("associative_lexicon", "expected a dictionary")
    if data.get("schema_version") != SCHEMA_VERSION:
        _fail("associative_lexicon.schema_version", "unsupported schema version")
    records = data.get("records")
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        _fail("associative_lexicon.records", "expected a bounded list")
    keys = set()
    for index, record in enumerate(records):
        path = f"associative_lexicon.records[{index}]"
        if not isinstance(record, dict):
            _fail(path, "expected a dictionary")
        expression = record.get("expression")
        if (
            not isinstance(expression, str)
            or normalize_expression(expression) != expression
            or not expression
            or len(expression) > EXPRESSION_MAX_LEN
        ):
            _fail(f"{path}.expression", "expected a normalized bounded string")
        target_kind = record.get("target_kind")
        if target_kind not in TARGET_KINDS:
            _fail(f"{path}.target_kind", "unknown target kind")
        target_id = record.get("target_id")
        if (
            not isinstance(target_id, str)
            or not target_id.strip()
            or target_id != target_id.strip()
            or len(target_id) > TARGET_ID_MAX_LEN
        ):
            _fail(f"{path}.target_id", "expected a bounded nonempty string")
        if target_kind == "act" and target_id not in ASSOCIABLE_ACTS:
            _fail(f"{path}.target_id", "unknown or non-associable act")
        if target_kind == "context" and normalize_expression(target_id) != target_id:
            _fail(f"{path}.target_id", "expected a normalized context")
        scope = record.get("scope")
        if scope not in ASSOCIATION_SCOPES:
            _fail(f"{path}.scope", "unknown scope")
        if expected_scope is not None and scope != expected_scope:
            _fail(f"{path}.scope", f"expected {expected_scope}")
        profile_id = record.get("profile_id")
        if not isinstance(profile_id, str) or len(profile_id) > PROFILE_ID_MAX_LEN:
            _fail(f"{path}.profile_id", "expected a bounded string")
        if scope == "personal" and not profile_id:
            _fail(f"{path}.profile_id", "personal association requires a profile")
        if scope == "shared" and profile_id:
            _fail(f"{path}.profile_id", "shared record cannot belong to a profile")
        _confidence(record.get("confidence"), f"{path}.confidence")
        confirmations = record.get("confirmations")
        if (
            isinstance(confirmations, bool)
            or not isinstance(confirmations, int)
            or not 1 <= confirmations <= MAX_PROVENANCE
        ):
            _fail(f"{path}.confirmations", "invalid confirmation count")
        confirmed = record.get("confirmed")
        if not isinstance(confirmed, bool):
            _fail(f"{path}.confirmed", "expected a boolean")
        _cycle(record.get("last_cycle"), f"{path}.last_cycle")
        _cycle(record.get("last_decay_cycle"), f"{path}.last_decay_cycle")
        last_confirmed = record.get("last_confirmed_cycle")
        if confirmed:
            _cycle(last_confirmed, f"{path}.last_confirmed_cycle")
        elif last_confirmed is not None:
            _fail(f"{path}.last_confirmed_cycle", "unconfirmed record cannot have one")
        provenance = record.get("provenance")
        if (
            not isinstance(provenance, list)
            or not 1 <= len(provenance) <= MAX_PROVENANCE
            or confirmations != len(provenance)
        ):
            _fail(f"{path}.provenance", "inconsistent bounded provenance")
        seen_provenance = set()
        for source_index, source in enumerate(provenance):
            source_path = f"{path}.provenance[{source_index}]"
            if not isinstance(source, dict):
                _fail(source_path, "expected a dictionary")
            if source.get("source") not in PROVENANCE_SOURCES:
                _fail(f"{source_path}.source", "unknown provenance source")
            source_profile = source.get("profile_id")
            if (
                not isinstance(source_profile, str)
                or len(source_profile) > PROFILE_ID_MAX_LEN
            ):
                _fail(f"{source_path}.profile_id", "expected a bounded string")
            if scope == "personal" and source_profile != profile_id:
                _fail(f"{source_path}.profile_id", "profile mismatch")
            _cycle(source.get("cycle"), f"{source_path}.cycle")
            identity = (
                source["source"],
                source_profile,
                source["cycle"],
            )
            if identity in seen_provenance:
                _fail(source_path, "duplicate provenance")
            seen_provenance.add(identity)
        key = _record_key(record)
        if key in keys:
            _fail(path, "duplicate association")
        keys.add(key)


class AssociativeLexicon:
    """Хранить личные и общие связи, не участвуя в выборе действий."""

    def __init__(self) -> None:
        self._personal: dict[tuple[str, str, str], dict] = {}
        self._shared: dict[tuple[str, str, str], dict] = {}

    def _store(self, scope: str) -> dict[tuple[str, str, str], dict]:
        return self._personal if scope == "personal" else self._shared

    @staticmethod
    def _initial_confidence(source: str) -> float:
        return {"observed_act": 0.25, "user_taught": 0.7, "explicit": 0.55}[source]

    @staticmethod
    def effective_confidence(record: dict, cycle: int) -> float:
        """Уверенность с учётом ленивого затухания, без мутации записи."""
        confidence = float(record["confidence"])
        if record["confirmed"]:
            return confidence
        elapsed = max(0, int(cycle) - int(record["last_decay_cycle"]))
        return max(0.0, confidence - elapsed * DECAY_PER_CYCLE)

    def associate(
        self,
        expression,
        target_kind: str,
        target_id,
        *,
        cycle: int,
        scope: str = "personal",
        profile_id: str = "",
        source: str = "explicit",
        confirmed: Optional[bool] = None,
        target_exists: Optional[Callable[[str], bool]] = None,
    ) -> dict:
        """Добавить свидетельство связи; concept/episode требуют проверки."""
        expression = normalize_expression(expression)
        target_id = str(target_id or "").strip()
        profile_id = str(profile_id or "").strip()
        _cycle(cycle)
        if not expression or len(expression) > EXPRESSION_MAX_LEN:
            raise ValueError("expression: expected a normalized bounded string")
        if target_kind not in TARGET_KINDS:
            raise ValueError("target_kind: unknown target kind")
        if not target_id or len(target_id) > TARGET_ID_MAX_LEN:
            raise ValueError("target_id: expected a bounded nonempty string")
        if target_kind == "act":
            if target_id not in ASSOCIABLE_ACTS:
                raise ValueError("target_id: unknown or non-associable act")
        elif target_kind == "context":
            target_id = normalize_expression(target_id)
        elif target_exists is None or not target_exists(target_id):
            raise ValueError(f"target_id: real {target_kind} target is required")
        if scope not in ASSOCIATION_SCOPES:
            raise ValueError("scope: unknown scope")
        if scope == "personal" and not profile_id:
            raise ValueError("profile_id: personal association requires a profile")
        if len(profile_id) > PROFILE_ID_MAX_LEN:
            raise ValueError("profile_id: too long")
        if scope == "shared":
            record_profile = ""
        else:
            record_profile = profile_id
        if source not in PROVENANCE_SOURCES:
            raise ValueError("source: unknown provenance source")
        if confirmed is None:
            confirmed = source != "observed_act"

        store = self._store(scope)
        key = (expression, target_kind, target_id)
        evidence = {"source": source, "profile_id": profile_id, "cycle": cycle}
        record = store.get(key)
        is_new = record is None
        if record is None:
            if len(store) >= MAX_RECORDS:
                self._evict_one(store, cycle)
            record = {
                "expression": expression,
                "target_kind": target_kind,
                "target_id": target_id,
                "scope": scope,
                "profile_id": record_profile,
                "confidence": self._initial_confidence(source),
                "confirmations": 0,
                "confirmed": False,
                "last_cycle": cycle,
                "last_decay_cycle": cycle,
                "last_confirmed_cycle": None,
                "provenance": [],
            }
            store[key] = record

        duplicate = evidence in record["provenance"]
        if not duplicate and len(record["provenance"]) < MAX_PROVENANCE:
            record["provenance"].append(evidence)
            record["confirmations"] += 1
            if not is_new:
                increment = 0.1 if source == "observed_act" else 0.2
                record["confidence"] = min(0.95, record["confidence"] + increment)
        record["last_cycle"] = max(record["last_cycle"], cycle)
        record["last_decay_cycle"] = max(record["last_decay_cycle"], cycle)
        if confirmed:
            record["confirmed"] = True
            record["last_confirmed_cycle"] = max(
                record["last_confirmed_cycle"] or 0, cycle
            )
        return deepcopy(record)

    def observe_act(
        self,
        text,
        act: str,
        *,
        cycle: int,
        profile_id: str,
        source: str = "observed_act",
        confirmed: bool = False,
    ) -> list[dict]:
        """Связать реальную реплику и отдельные значимые слова с актом."""
        if act not in ASSOCIABLE_ACTS or act == ACT_UNKNOWN:
            return []
        expression = normalize_expression(text)
        if not expression or len(expression) > EXPRESSION_MAX_LEN:
            return []
        expressions = (expression,) + tuple(
            token for token in _observed_tokens(expression) if token != expression
        )
        return [
            self.associate(
                item,
                "act",
                act,
                cycle=cycle,
                scope="personal",
                profile_id=profile_id,
                source=source,
                confirmed=confirmed,
            )
            for item in expressions
        ]

    def _evict_one(self, store: dict, cycle: int) -> None:
        """Ограничить память: сначала слабые неподтверждённые и старые."""
        key = min(
            store,
            key=lambda item: (
                store[item]["confirmed"],
                self.effective_confidence(store[item], cycle),
                store[item]["last_cycle"],
                item,
            ),
        )
        del store[key]

    def decay_unconfirmed(self, cycle: int) -> int:
        """Ослабить только неподтверждённые связи; вернуть число забытых."""
        _cycle(cycle)
        forgotten = 0
        for store in (self._personal, self._shared):
            for key, record in list(store.items()):
                if record["confirmed"]:
                    continue
                record["confidence"] = self.effective_confidence(record, cycle)
                record["last_decay_cycle"] = cycle
                if record["confidence"] < MIN_CONFIDENCE:
                    del store[key]
                    forgotten += 1
        return forgotten

    def consolidate(self, cycle: int) -> dict:
        """Ослабить шум без создания новых свидетельств или обобщений."""
        return {"forgotten_associations": self.decay_unconfirmed(cycle)}

    def recall(
        self,
        text,
        *,
        cycle: int,
        profile_id: str = "",
        target_kind: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict]:
        """Предложить кандидатов для новой формулировки, не меняя акт."""
        _cycle(cycle)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 20
        ):
            raise ValueError("limit: expected an integer in [1, 20]")
        if target_kind is not None and target_kind not in TARGET_KINDS:
            raise ValueError("target_kind: unknown target kind")
        normalized = normalize_expression(text)
        query_words = _words(normalized)
        candidates: dict[tuple[str, str], dict] = {}
        stores = [self._shared]
        if profile_id:
            stores.append(self._personal)
        for store in stores:
            for record in store.values():
                if target_kind is not None and record["target_kind"] != target_kind:
                    continue
                if profile_id and record["scope"] == "personal":
                    if record["profile_id"] != profile_id:
                        continue
                confidence = self.effective_confidence(record, cycle)
                if confidence < MIN_CONFIDENCE:
                    continue
                expression_words = _words(record["expression"])
                if record["expression"] == normalized:
                    match = 1.0
                elif expression_words and expression_words <= query_words:
                    match = 0.9 if len(expression_words) > 1 else 0.7
                else:
                    continue
                score = confidence * match
                target = (record["target_kind"], record["target_id"])
                candidate = {
                    "target_kind": record["target_kind"],
                    "target_id": record["target_id"],
                    "scope": record["scope"],
                    "profile_id": record["profile_id"],
                    "expression": record["expression"],
                    "confidence": confidence,
                    "score": score,
                    "provenance": deepcopy(record["provenance"]),
                }
                previous = candidates.get(target)
                if previous is None or (score, record["scope"] == "personal") > (
                    previous["score"],
                    previous["scope"] == "personal",
                ):
                    candidates[target] = candidate
        return sorted(
            candidates.values(),
            key=lambda item: (
                -item["score"],
                item["target_kind"],
                item["target_id"],
                item["scope"] != "personal",
            ),
        )[:limit]

    def get_status(self) -> dict:
        return {
            "personal": len(self._personal),
            "shared": len(self._shared),
            "confirmed": sum(
                record["confirmed"]
                for record in list(self._personal.values())
                + list(self._shared.values())
            ),
        }

    def to_personal_dict(self) -> dict:
        return self._to_dict(self._personal)

    def to_shared_dict(self) -> dict:
        return self._to_dict(self._shared)

    @staticmethod
    def _to_dict(store: dict) -> dict:
        records = [deepcopy(store[key]) for key in sorted(store)]
        return {"schema_version": SCHEMA_VERSION, "records": records}

    def load_personal_from(self, data) -> None:
        self._personal = self._restore(data, expected_scope="personal")

    def load_shared_from(self, data) -> None:
        self._shared = self._restore(data, expected_scope="shared")

    @staticmethod
    def _restore(data, *, expected_scope: str) -> dict:
        validate_associative_lexicon(data, expected_scope=expected_scope)
        return {_record_key(record): deepcopy(record) for record in data["records"]}
