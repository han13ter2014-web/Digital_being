"""12C: раздельный per-root storage risk, личный опыт и persistence."""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Dict, Optional

from src.core.hardware_personal_profile import (
    HardwareDomainPersonalProfile,
    _neutral_domain_experience,
    _neutral_domain_latest,
    validate_domain_experience,
)


_ROOT_ID = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_MAX_EXTRA_ROOTS = 7
_STRAIN_THRESHOLD = 0.85
_RECOVERY_THRESHOLD = 0.6
_STRAIN_AFTER_CYCLES = 5
_RECOVERY_AFTER_CYCLES = 5


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _unknown_risk(reason: str) -> Dict:
    return {
        "value": None,
        "confidence": 0.0,
        "reason": reason,
        "origin": "unknown",
        "expectedness": "unknown",
        "evidence": [],
    }


def _neutral_slow_state() -> Dict:
    return {
        "sustained_cycles": 0,
        "low_cycles": 0,
        "strain_active": False,
    }


class HardwareRelevantRootExperience:
    """Опыт одного дополнительного root без внешних событий и поведения."""

    def __init__(self):
        self.channel: Dict = {}
        self.risk = _unknown_risk("no_observation")
        self.profile = _neutral_domain_experience()
        self.slow_state = _neutral_slow_state()
        self.last_cycle: Optional[int] = None

    @property
    def has_observation(self) -> bool:
        return self.last_cycle is not None or bool(self.channel)

    def observe(self, channel: Dict, trend: Dict, cycle: int) -> Dict:
        self.channel = deepcopy(channel)
        if self.last_cycle is not None and cycle != self.last_cycle + 1:
            self.slow_state.update(_neutral_slow_state())
        self.last_cycle = cycle

        if channel.get("status") != "available":
            self.slow_state.update(_neutral_slow_state())
            self.risk = _unknown_risk("channel_unavailable")
            self.profile["latest"] = _neutral_domain_latest(
                "unavailable", "channel_unavailable"
            )
            return self.status()

        free_ratio = float(channel["value"])
        risk = _clamp((0.25 - free_ratio) / 0.25)
        evidence = [f"root_free_ratio={free_ratio:.3f}"]
        confidence = 1.0 if trend["window_size"] >= 2 else 0.8
        drop = trend["drop"]
        if drop is not None:
            risk = max(risk, _clamp(drop * 2.0))
            evidence.append(f"root_free_ratio_sustained_drop_v1={drop:.3f}")
        state = {
            "value": risk,
            "confidence": confidence,
            "reason": "observed_relevant_root_storage",
            "origin": "unknown",
            "expectedness": "unknown",
            "evidence": evidence,
        }
        strain, recovery = self._advance_slow_state(risk)

        self.profile["observation_count"] += 1
        self.profile["confidence"] = min(1.0, self.profile["observation_count"] / 200.0)
        HardwareDomainPersonalProfile._update_episode(
            self.profile,
            risk,
            state,
            cycle=cycle,
            strain=strain,
            recovery=recovery,
        )
        self.profile["latest"] = HardwareDomainPersonalProfile._personalize(
            self.profile, risk, state
        )
        if (
            self.profile["current_episode"] is None
            and not self.slow_state["strain_active"]
            and not strain
            and not recovery
            and risk < _STRAIN_THRESHOLD
        ):
            HardwareDomainPersonalProfile._update_baseline(self.profile, risk, cycle)
        state["expectedness"] = self.profile["latest"]["expectedness"]
        self.risk = state
        return self.status()

    def _advance_slow_state(self, risk: float):
        slow = self.slow_state
        if risk >= _STRAIN_THRESHOLD:
            slow["sustained_cycles"] += 1
            slow["low_cycles"] = 0
            if (
                slow["sustained_cycles"] >= _STRAIN_AFTER_CYCLES
                and not slow["strain_active"]
            ):
                slow["strain_active"] = True
                return True, False
            return False, False

        slow["sustained_cycles"] = 0
        if risk > _RECOVERY_THRESHOLD:
            slow["low_cycles"] = 0
            return False, False
        if not slow["strain_active"]:
            slow["low_cycles"] = 0
            return False, False

        slow["low_cycles"] += 1
        if slow["low_cycles"] < _RECOVERY_AFTER_CYCLES:
            return False, False
        slow["strain_active"] = False
        slow["low_cycles"] = 0
        return False, True

    def status(self) -> Dict:
        return {
            "channel": deepcopy(self.channel),
            "risk": deepcopy(self.risk),
            "experience": deepcopy(self.profile),
        }

    def to_checkpoint(self) -> Dict:
        return {
            "channel": deepcopy(self.channel),
            "risk": deepcopy(self.risk),
            "profile": deepcopy(self.profile),
            "slow_state": deepcopy(self.slow_state),
            "last_cycle": self.last_cycle,
        }

    @classmethod
    def from_checkpoint(cls, data: Dict) -> "HardwareRelevantRootExperience":
        validate_relevant_root_experience(data)
        restored = cls()
        restored.channel = deepcopy(data["channel"])
        if restored.channel.get("status") == "available":
            restored.channel["status"] = "stale"
            restored.channel["reason"] = "waiting_for_fresh_observation_after_restart"
        restored.risk = _unknown_risk("waiting_for_fresh_observation_after_restart")
        restored.profile = deepcopy(data["profile"])
        restored.profile["latest"] = _neutral_domain_latest(
            "stale", "waiting_for_fresh_observation_after_restart"
        )
        restored.slow_state = deepcopy(data["slow_state"])
        restored.last_cycle = data["last_cycle"]
        return restored


def _finite_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _validate_cycle(value, path: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path}: expected a nonnegative integer")


def _validate_channel(channel: Dict, path: str) -> None:
    if not isinstance(channel, dict):
        raise ValueError(f"{path}: expected dictionary")
    if not channel:
        return
    required = {"status", "value", "reason", "source"}
    if not required <= set(channel) or not set(channel) <= required | {"unit"}:
        raise ValueError(f"{path}: unknown or missing channel field")
    if channel["status"] not in {"available", "unavailable", "stale"}:
        raise ValueError(f"{path}.status: unknown status")
    value = channel["value"]
    if value is not None and (
        not _finite_number(value) or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{path}.value: expected a free ratio")
    if channel["status"] == "available" and value is None:
        raise ValueError(f"{path}.value: available channel requires a measurement")
    if "unit" in channel and channel["unit"] != "free_ratio":
        raise ValueError(f"{path}.unit: unknown unit")
    for field in ("reason", "source"):
        if not isinstance(channel[field], str) or len(channel[field]) > 128:
            raise ValueError(f"{path}.{field}: invalid string")


def _validate_risk(risk: Dict, path: str) -> None:
    fields = {"value", "confidence", "reason", "origin", "expectedness", "evidence"}
    if not isinstance(risk, dict) or set(risk) != fields:
        raise ValueError(f"{path}: unknown or missing risk field")
    if risk["value"] is not None and (
        not _finite_number(risk["value"]) or not 0.0 <= float(risk["value"]) <= 1.0
    ):
        raise ValueError(f"{path}.value: expected a risk ratio")
    if (
        not _finite_number(risk["confidence"])
        or not 0.0 <= float(risk["confidence"]) <= 1.0
    ):
        raise ValueError(f"{path}.confidence: expected a confidence ratio")
    if risk["origin"] not in {"own", "external", "mixed", "unknown"}:
        raise ValueError(f"{path}.origin: unknown origin")
    if risk["expectedness"] not in {"unknown", "familiar"}:
        raise ValueError(f"{path}.expectedness: unknown value")
    if not isinstance(risk["reason"], str) or len(risk["reason"]) > 128:
        raise ValueError(f"{path}.reason: invalid string")
    evidence = risk["evidence"]
    if (
        not isinstance(evidence, list)
        or len(evidence) > 8
        or not all(isinstance(item, str) and len(item) <= 128 for item in evidence)
    ):
        raise ValueError(f"{path}.evidence: expected a bounded string list")


def validate_relevant_root_experience(entry: Dict) -> None:
    fields = {"channel", "risk", "profile", "slow_state", "last_cycle"}
    if not isinstance(entry, dict) or set(entry) != fields:
        raise ValueError("relevant_root_experience: unknown or missing field")
    _validate_channel(entry["channel"], "relevant_root_experience.channel")
    _validate_risk(entry["risk"], "relevant_root_experience.risk")
    validate_domain_experience(
        {
            "domain_experience": {
                "storage": entry["profile"],
                "physical": _neutral_domain_experience(),
            }
        }
    )
    slow = entry["slow_state"]
    if not isinstance(slow, dict) or set(slow) != {
        "sustained_cycles",
        "low_cycles",
        "strain_active",
    }:
        raise ValueError("relevant_root_experience.slow_state: invalid fields")
    for field in ("sustained_cycles", "low_cycles"):
        _validate_cycle(slow[field], f"relevant_root_experience.slow_state.{field}")
    if not isinstance(slow["strain_active"], bool):
        raise ValueError("relevant_root_experience.slow_state.strain_active: invalid")
    _validate_cycle(
        entry["last_cycle"], "relevant_root_experience.last_cycle", optional=True
    )


def validate_relevant_root_experience_map(state: Dict) -> None:
    if not isinstance(state, dict) or len(state) > _MAX_EXTRA_ROOTS:
        raise ValueError("relevant_root_experience: expected a bounded root map")
    for root_id, entry in state.items():
        if (
            not isinstance(root_id, str)
            or _ROOT_ID.fullmatch(root_id) is None
            or root_id == "data"
        ):
            raise ValueError("relevant_root_experience: invalid logical root ID")
        validate_relevant_root_experience(entry)


__all__ = [
    "HardwareRelevantRootExperience",
    "validate_relevant_root_experience_map",
]
