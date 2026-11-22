"""Read-only DTO shadow-предсказания с проверяемым provenance.

Схема не содержит writer, исход наблюдения, сырой текст или baseline-ответ. Она
только описывает уже вычисленное распределение либо явный abstention.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from src.core.life_identity import validate_life_id

SCHEMA_VERSION = 1
OUTCOME_COUNT = 6
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _text(value, path: str, limit: int = 160) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{path}: expected a bounded nonempty string")


def _sequence(value, path: str, *, zero=False) -> None:
    minimum = 0 if zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{path}: expected an integer >= {minimum}")


@dataclass(frozen=True)
class PredictionProvenance:
    source_delivery_event_hash: str
    training_response_ids: tuple[str, ...]
    training_cutoff_sequence: int
    training_sample_count: int
    # None означает ту же жизнь; другое значение проверяется внешним DTO.
    training_life_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_delivery_event_hash, str) or not _HASH.fullmatch(
            self.source_delivery_event_hash
        ):
            raise ValueError("source_delivery_event_hash: expected SHA-256 hex")
        if not isinstance(self.training_response_ids, tuple):
            raise ValueError("training_response_ids: expected a tuple")
        if len(set(self.training_response_ids)) != len(self.training_response_ids):
            raise ValueError("training_response_ids: duplicates")
        for response_id in self.training_response_ids:
            _text(response_id, "training_response_ids")
        _sequence(self.training_cutoff_sequence, "training_cutoff_sequence", zero=True)
        _sequence(self.training_sample_count, "training_sample_count", zero=True)
        if self.training_sample_count != len(self.training_response_ids):
            raise ValueError("training_sample_count: does not match response IDs")
        if self.training_life_id is not None:
            validate_life_id(self.training_life_id)

    def to_dict(self) -> dict:
        return {
            "source_delivery_event_hash": self.source_delivery_event_hash,
            "training_response_ids": list(self.training_response_ids),
            "training_cutoff_sequence": self.training_cutoff_sequence,
            "training_sample_count": self.training_sample_count,
            "training_life_id": self.training_life_id,
        }


@dataclass(frozen=True)
class ShadowPrediction:
    prediction_id: str
    life_id: str
    profile_id: str
    response_id: str
    episode_id: str
    delivery_sequence: int
    prediction_sequence: int
    feature_contract_version: str
    architecture_version: str
    weights_version: str
    training_contract_version: str
    probabilities: tuple[float, ...] | None
    abstain_reason: str | None
    provenance: PredictionProvenance
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("schema_version: unsupported")
        validate_life_id(self.life_id)
        for field, value in (
            ("prediction_id", self.prediction_id),
            ("profile_id", self.profile_id),
            ("response_id", self.response_id),
            ("episode_id", self.episode_id),
            ("feature_contract_version", self.feature_contract_version),
            ("architecture_version", self.architecture_version),
            ("weights_version", self.weights_version),
            ("training_contract_version", self.training_contract_version),
        ):
            _text(value, field)
        _sequence(self.delivery_sequence, "delivery_sequence")
        _sequence(self.prediction_sequence, "prediction_sequence")
        if self.prediction_sequence <= self.delivery_sequence:
            raise ValueError("prediction_sequence: must follow delivery")
        if self.abstain_reason is not None:
            _text(self.abstain_reason, "abstain_reason", 80)
        if (self.probabilities is None) == (self.abstain_reason is None):
            raise ValueError("prediction: require probabilities XOR abstain_reason")
        if self.probabilities is not None:
            if (
                not isinstance(self.probabilities, tuple)
                or len(self.probabilities) != OUTCOME_COUNT
            ):
                raise ValueError("probabilities: expected exactly six values")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0.0 <= value <= 1.0
                for value in self.probabilities
            ):
                raise ValueError("probabilities: expected finite values in [0, 1]")
            if not math.isclose(sum(self.probabilities), 1.0, abs_tol=1e-9):
                raise ValueError("probabilities: sum must equal one")
        if not isinstance(self.provenance, PredictionProvenance):
            raise ValueError("provenance: expected PredictionProvenance")
        if (
            self.provenance.training_life_id is not None
            and self.provenance.training_life_id != self.life_id
        ):
            raise ValueError("provenance: training life cannot cross lives")
        if self.provenance.training_cutoff_sequence > self.delivery_sequence:
            raise ValueError("provenance: training cutoff cannot be in the future")
        if self.response_id in self.provenance.training_response_ids:
            raise ValueError("provenance: response cannot train on itself")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "prediction_id": self.prediction_id,
            "life_id": self.life_id,
            "profile_id": self.profile_id,
            "response_id": self.response_id,
            "episode_id": self.episode_id,
            "delivery_sequence": self.delivery_sequence,
            "prediction_sequence": self.prediction_sequence,
            "feature_contract_version": self.feature_contract_version,
            "architecture_version": self.architecture_version,
            "weights_version": self.weights_version,
            "training_contract_version": self.training_contract_version,
            "probabilities": (
                list(self.probabilities) if self.probabilities is not None else None
            ),
            "abstain_reason": self.abstain_reason,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ShadowPrediction:
        if not isinstance(data, dict):
            raise ValueError("shadow_prediction: expected a dictionary")
        fields = {
            "schema_version",
            "prediction_id",
            "life_id",
            "profile_id",
            "response_id",
            "episode_id",
            "delivery_sequence",
            "prediction_sequence",
            "feature_contract_version",
            "architecture_version",
            "weights_version",
            "training_contract_version",
            "probabilities",
            "abstain_reason",
            "provenance",
        }
        unknown = set(data) - fields
        if unknown:
            raise ValueError(f"shadow_prediction: unknown fields {sorted(unknown)}")
        provenance = data.get("provenance")
        probabilities = data.get("probabilities")
        if not isinstance(provenance, dict):
            raise ValueError("provenance: expected a dictionary")
        if probabilities is not None and not isinstance(probabilities, list):
            raise ValueError("probabilities: expected a list or None")
        try:
            clean_provenance = dict(provenance)
            clean_provenance["training_response_ids"] = tuple(
                clean_provenance.get("training_response_ids", ())
            )
            return cls(
                schema_version=data.get("schema_version"),
                prediction_id=data.get("prediction_id"),
                life_id=data.get("life_id"),
                profile_id=data.get("profile_id"),
                response_id=data.get("response_id"),
                episode_id=data.get("episode_id"),
                delivery_sequence=data.get("delivery_sequence"),
                prediction_sequence=data.get("prediction_sequence"),
                feature_contract_version=data.get("feature_contract_version"),
                architecture_version=data.get("architecture_version"),
                weights_version=data.get("weights_version"),
                training_contract_version=data.get("training_contract_version"),
                probabilities=(
                    tuple(probabilities) if probabilities is not None else None
                ),
                abstain_reason=data.get("abstain_reason"),
                provenance=PredictionProvenance(**clean_provenance),
            )
        except TypeError as error:
            raise ValueError(
                f"shadow_prediction: invalid nested data: {error}"
            ) from error
