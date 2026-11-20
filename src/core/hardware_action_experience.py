"""Раздельный shadow-опыт нагрузки после завершённых классов действий."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, Optional

from src.core.hardware_personal_profile import (
    HardwarePersonalProfile,
    validate_personal_experience,
)


_ALLOWED_ACTIONS = frozenset(
    {
        "ask_user",
        "browse_web",
        "communicate",
        "compose_music",
        "create_draft",
        "decomposition",
        "deep_rest",
        "draw",
        "explore",
        "hypothesis",
        "learn",
        "let_go",
        "listen_music",
        "play",
        "process_stimulus",
        "read_news",
        "reflection",
        "repair",
        "rest",
        "set_own_goal",
        "synthesis",
        "user_answer",
        "wait",
        "web_search",
    }
)


def _latest(
    *,
    action: Optional[str],
    sample_count: int,
    freshness: str,
    reason: str,
    risk: Optional[float] = None,
    expectedness: str = "unknown",
) -> Dict:
    return {
        "action": action,
        "sample_count": sample_count,
        "expectedness": expectedness,
        "freshness": freshness,
        "reason": reason,
        "risk": risk,
    }


class HardwareActionExperience:
    """Личный опыт одной жизни без входа в выбор или checkpoint latest."""

    def __init__(self):
        self.profiles: Dict[str, HardwarePersonalProfile] = {}
        self.latest = _latest(
            action=None,
            sample_count=0,
            freshness="no_observation",
            reason="no_previous_completed_action",
        )

    def observe(
        self,
        context: Optional[Dict],
        states: Dict,
        resource_status: Dict,
        *,
        cycle: int,
        events: list,
        strain_active: bool,
    ) -> Dict:
        if context is None:
            self.latest = _latest(
                action=None,
                sample_count=0,
                freshness="unavailable",
                reason="no_previous_completed_action",
            )
            return deepcopy(self.latest)

        action = context.get("action") if isinstance(context, dict) else None
        valid_action = isinstance(action, str) and action in _ALLOWED_ACTIONS
        previous_count = int(self.latest.get("sample_count") or 0)
        if (
            not isinstance(context, dict)
            or not valid_action
            or context.get("status") != "completed"
            or isinstance(context.get("cycle"), bool)
            or context.get("cycle") != cycle - 1
        ):
            invalid_count = previous_count
            if valid_action:
                invalid_count = (
                    self.profiles[action].observation_count
                    if action in self.profiles
                    else 0
                )
            self.latest = _latest(
                action=action if valid_action else None,
                sample_count=invalid_count,
                freshness="unavailable",
                reason="invalid_action_context",
            )
            return deepcopy(self.latest)

        if states.get("own_load", {}).get("value") is None:
            self.latest = _latest(
                action=action,
                sample_count=self.profiles[action].observation_count
                if action in self.profiles
                else 0,
                freshness="unavailable",
                reason="own_load_unavailable",
            )
            return deepcopy(self.latest)

        profile = self.profiles.setdefault(action, HardwarePersonalProfile())
        profile.observe(
            states,
            resource_status,
            cycle=cycle,
            events=events,
            strain_active=strain_active,
        )
        experience = profile.latest_experience["own_load"]
        self.latest = _latest(
            action=action,
            sample_count=profile.observation_count,
            freshness="fresh",
            reason="observed_after_completed_action",
            risk=experience["risk"],
            expectedness=experience["expectedness"],
        )
        return deepcopy(self.latest)

    def status(self) -> Dict:
        return {"latest": deepcopy(self.latest)}

    def to_checkpoint(self) -> Dict:
        return {
            action: {
                **profile.to_checkpoint(),
                "sample_count": profile.observation_count,
            }
            for action, profile in sorted(self.profiles.items())
        }

    @classmethod
    def from_checkpoint(cls, data: Dict) -> "HardwareActionExperience":
        validate_action_experience(data)
        restored = cls()
        for action, profile in data.items():
            restored_profile = HardwarePersonalProfile.from_checkpoint(profile)
            # Свежесть наружу задаёт restored.latest; сохранение последнего
            # внутреннего значения обеспечивает точный checkpoint round-trip.
            restored_profile.latest_experience = deepcopy(profile["latest_experience"])
            restored.profiles[action] = restored_profile
        restored.latest = _latest(
            action=None,
            sample_count=sum(
                profile.observation_count for profile in restored.profiles.values()
            ),
            freshness="stale",
            reason="waiting_for_fresh_observation_after_restart",
        )
        return restored


def validate_action_experience(state: Dict) -> None:
    if not isinstance(state, dict) or len(state) > len(_ALLOWED_ACTIONS):
        raise ValueError("hardware_interoception.action_experience: invalid profiles")
    for action, profile in state.items():
        if not isinstance(action, str) or action not in _ALLOWED_ACTIONS:
            raise ValueError(
                "hardware_interoception.action_experience: unknown action class"
            )
        if not isinstance(profile, dict):
            raise ValueError(
                "hardware_interoception.action_experience: invalid profile"
            )
        validate_personal_experience(profile)
        sample_count = profile.get("sample_count")
        if (
            isinstance(sample_count, bool)
            or not isinstance(sample_count, int)
            or sample_count != profile["personal_profile"]["observation_count"]
        ):
            raise ValueError(
                "hardware_interoception.action_experience: invalid sample count"
            )


__all__ = ["HardwareActionExperience", "validate_action_experience"]
