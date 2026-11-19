"""Медленный per-life профиль теневой эндокринной проекции.

Профиль обучается только на завершённых событиях с provenance. Он меняет
чувствительность и затухание уровней, но не исходные события и не поведение Core.
"""

from __future__ import annotations

from copy import deepcopy
import math


_SOURCES = ("action_outcome", "social_message", "hardware")
_EPISODE_LIMIT = 50
_MIN_SOURCE_EPISODES = 20
_SAMPLE_LIMIT = 1_000_000


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _number(value, path: str, *, low: float, high: float | None = None) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < low
        or (high is not None and float(value) > high)
    ):
        raise ValueError(f"{path}: expected a finite number in range")


def _count(value, path: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _SAMPLE_LIMIT
    ):
        raise ValueError(f"{path}: expected a bounded nonnegative integer")


class HormonalProfile:
    """Ограниченные параметры и эпизоды, принадлежащие одной жизни."""

    def __init__(self, specs: dict):
        self._specs = specs
        self.values = {
            name: {
                "baseline": spec.base_level,
                "sensitivity": 1.0,
                "half_life_scale": 1.0,
                "confidence": 0.0,
                "sample_count": 0,
                "source_sample_counts": {},
            }
            for name, spec in specs.items()
        }
        self.episodes = []

    def observe(
        self,
        *,
        event: str,
        time: float,
        intensity: float,
        changes: dict,
        provenance: dict,
    ) -> None:
        """Записать один завершённый эпизод и пересчитать затронутые уровни."""
        if not provenance or not changes:
            return
        source = provenance["source"]
        episode = {
            "time": time,
            "event": event,
            "source": source,
            "intensity": intensity,
            "changes": deepcopy(changes),
        }
        for field in ("cycle", "reason", "action", "origin"):
            if field in provenance:
                episode[field] = deepcopy(provenance[field])
        self.episodes.append(episode)
        self.episodes = self.episodes[-_EPISODE_LIMIT:]

        for name, change in changes.items():
            if name not in self.values or change == 0.0:
                continue
            values = self.values[name]
            values["sample_count"] = min(_SAMPLE_LIMIT, values["sample_count"] + 1)
            counts = values["source_sample_counts"]
            counts[source] = min(_SAMPLE_LIMIT, counts.get(source, 0) + 1)
            self._recalculate(name)

    def _recalculate(self, name: str) -> None:
        values = self.values[name]
        spec = self._specs[name]
        counts = values["source_sample_counts"]
        baseline_shift = 0.0
        sensitivity_shift = 0.0
        half_life_shift = 0.0

        for source, count in counts.items():
            if count < _MIN_SOURCE_EPISODES:
                continue
            recent = [
                episode
                for episode in reversed(self.episodes)
                if episode["source"] == source and name in episode["changes"]
            ][:_MIN_SOURCE_EPISODES]
            if len(recent) < _MIN_SOURCE_EPISODES:
                continue
            changes = [float(episode["changes"][name]) for episode in recent]
            familiarity = _clamp((count - _MIN_SOURCE_EPISODES) / 80.0, 0.0, 1.0)
            consistency = abs(
                sum((change > 0.0) - (change < 0.0) for change in changes)
                / _MIN_SOURCE_EPISODES
            )
            mean_change = sum(changes) / _MIN_SOURCE_EPISODES
            baseline_shift += mean_change * 0.25 * familiarity
            sensitivity_shift -= 0.25 * familiarity * consistency
            half_life_shift += 0.5 * familiarity * consistency

        values["baseline"] = _clamp(
            spec.base_level + baseline_shift,
            spec.base_level - 0.05,
            spec.base_level + 0.05,
        )
        values["sensitivity"] = _clamp(1.0 + sensitivity_shift, 0.75, 1.25)
        values["half_life_scale"] = _clamp(1.0 + half_life_shift, 0.75, 1.5)
        values["confidence"] = min(1.0, max(counts.values(), default=0) / 200.0)

    def to_checkpoint(self) -> dict:
        return deepcopy(self.values)

    @classmethod
    def from_checkpoint(cls, data: dict, specs: dict) -> "HormonalProfile":
        validate_hormonal_profile(data, specs)
        restored = cls(specs)
        restored.values = deepcopy(data)
        return restored


def validate_hormonal_profile(
    data, specs: dict, path: str = "hormones.profile"
) -> None:
    if not isinstance(data, dict) or set(data) != set(specs):
        raise ValueError(f"{path}: unknown or missing hormone")
    fields = {
        "baseline",
        "sensitivity",
        "half_life_scale",
        "confidence",
        "sample_count",
        "source_sample_counts",
    }
    for name, values in data.items():
        item_path = f"{path}.{name}"
        if not isinstance(values, dict) or set(values) != fields:
            raise ValueError(f"{item_path}: unknown or missing profile field")
        spec = specs[name]
        _number(
            values["baseline"],
            f"{item_path}.baseline",
            low=spec.base_level - 0.05,
            high=spec.base_level + 0.05,
        )
        _number(
            values["sensitivity"],
            f"{item_path}.sensitivity",
            low=0.75,
            high=1.25,
        )
        _number(
            values["half_life_scale"],
            f"{item_path}.half_life_scale",
            low=0.75,
            high=1.5,
        )
        _number(values["confidence"], f"{item_path}.confidence", low=0.0, high=1.0)
        _count(values["sample_count"], f"{item_path}.sample_count")
        counts = values["source_sample_counts"]
        if not isinstance(counts, dict) or set(counts) - set(_SOURCES):
            raise ValueError(f"{item_path}.source_sample_counts: unknown source")
        for source, count in counts.items():
            _count(count, f"{item_path}.source_sample_counts.{source}")


__all__ = ["HormonalProfile", "validate_hormonal_profile"]
