"""Личный опыт аппаратной интероцепции, привыкание и его валидация.

Объективный ``risk`` никогда не адаптируется. Личный опыт меняет только
``experienced`` и непрерывные shadow-величины. Отдельный advisor этапа 4A может
читать ``experienced`` для ограниченной поправки кандидатов; сам профиль поведением
не управляет и не создаёт действия, цели или награды.
"""

from __future__ import annotations

from copy import deepcopy
import math
from statistics import median
from typing import Dict, Optional


_BASELINE_STATES = ("own_load", "environmental_pressure", "memory_pressure")
_EXPERIENCE_STATES = _BASELINE_STATES
_LEGACY_EXPERIENCE_STATES = _EXPERIENCE_STATES + ("storage_risk",)
_DOMAIN_STATE_NAMES = {
    "physical": "physical_strain",
    "storage": "storage_risk",
}
_DOMAIN_EVENT_REASONS = {
    "physical": ("sustained_physical_strain", "confirmed_physical_recovery"),
    "storage": ("sustained_storage_risk", "confirmed_storage_recovery"),
}
_EPISODE_LIMIT = 50
_DOMAIN_EPISODE_LIMIT = 25
_MIN_BASELINE_SAMPLES = 50
_FAMILIARITY_AFTER_CYCLES = 20


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _neutral_baseline() -> Dict:
    return {
        "baseline": None,
        "deviation": None,
        "sample_count": 0,
        "last_update_cycle": None,
        "confidence": 0.0,
    }


def _neutral_experience() -> Dict:
    return {
        name: {"risk": None, "experienced": None, "expectedness": "unknown"}
        for name in _EXPERIENCE_STATES
    }


class HardwarePersonalProfile:
    """Медленный per-life опыт, получаемый только из свежих наблюдений."""

    def __init__(self):
        self.baseline = {name: _neutral_baseline() for name in _BASELINE_STATES}
        self.sensitivity = 1.0
        self.strain_half_life = 20.0
        self.recovery_rate = 1.0
        self.adaptation = 0.0
        self.confidence = 0.0
        self.observation_count = 0
        self.completed_episode_count = 0
        self.current_episode: Optional[Dict] = None
        self.episodes = []
        self.shadow_strain = 0.0
        self.shadow_recovery = 0.0
        self.latest_experience = _neutral_experience()

    def observe(
        self,
        states: Dict,
        resource_status: Dict,
        *,
        cycle: int,
        events: list,
        strain_active: bool,
    ) -> Dict:
        fresh = {
            name: float(states[name]["value"])
            for name in _EXPERIENCE_STATES
            if states.get(name, {}).get("value") is not None
        }
        if not fresh:
            return self._observation_report()

        self.observation_count += 1
        self.confidence = min(1.0, self.observation_count / 200.0)
        event_types = {event.get("type") for event in events}
        self._update_episode(
            fresh,
            states,
            resource_status,
            cycle=cycle,
            event_types=event_types,
        )
        self.latest_experience = self._personalize(fresh)
        self._update_shadow(fresh, event_types, strain_active)
        if not self.current_episode and not strain_active and not event_types:
            self._update_baselines(fresh, cycle)
        return self._observation_report()

    def _update_episode(
        self,
        fresh: Dict,
        states: Dict,
        resource_status: Dict,
        *,
        cycle: int,
        event_types: set,
    ) -> None:
        pressure = max(fresh.values())
        episode = self.current_episode
        if pressure >= 0.85:
            if episode is None:
                episode = {
                    "start_cycle": cycle,
                    "strain_cycle": None,
                    "end_cycle": None,
                    "max_pressure": pressure,
                    "origin": "unknown",
                    "evidence": [],
                    "slow_cycle": False,
                    "fresh_observations": 0,
                    "fresh_high_cycles": 0,
                    "recovery_duration_cycles": None,
                    "complete": False,
                }
                self.current_episode = episode
            strongest_name = max(fresh, key=fresh.get)
            strongest = states[strongest_name]
            episode["max_pressure"] = max(episode["max_pressure"], pressure)
            episode["origin"] = strongest["origin"]
            episode["evidence"] = list(strongest["evidence"])[:8]
            episode["slow_cycle"] = bool(
                episode["slow_cycle"] or resource_status.get("slow_cycle") is True
            )
            episode["fresh_high_cycles"] += 1
        elif episode is not None and episode["strain_cycle"] is None:
            # Короткий всплеск не становится личным опытом преодоления.
            self.current_episode = None
            episode = None

        if episode is not None:
            episode["fresh_observations"] += 1

        if "hardware_strain" in event_types and episode is not None:
            episode["strain_cycle"] = cycle

        if (
            episode is not None
            and episode["strain_cycle"] is not None
            and pressure >= 0.85
            and episode["fresh_high_cycles"] > _FAMILIARITY_AFTER_CYCLES
            and self.adaptation < 0.5
        ):
            # Можно привыкнуть к длящимся условиям, но это не опыт преодоления.
            self.adaptation = min(0.5, self.adaptation + 0.005)

        if "hardware_recovery" not in event_types:
            return
        if episode is None or episode["strain_cycle"] is None:
            return

        completed = deepcopy(episode)
        completed["end_cycle"] = cycle
        completed["recovery_duration_cycles"] = cycle - episode["strain_cycle"]
        completed["complete"] = True
        self.episodes.append(completed)
        self.episodes = self.episodes[-_EPISODE_LIMIT:]
        self.current_episode = None
        self.completed_episode_count += 1
        self.adaptation = min(1.0, self.adaptation + 0.02)
        self._learn_from_completed_episodes()

    def _learn_from_completed_episodes(self) -> None:
        if len(self.episodes) < 3:
            return
        latest = self.episodes[-1]
        self.sensitivity = _clamp(
            self.sensitivity + (0.01 if latest["slow_cycle"] else -0.005),
            0.8,
            1.2,
        )
        durations = [
            item["end_cycle"] - item["start_cycle"]
            for item in self.episodes
            if item["complete"]
        ]
        recoveries = [
            item["recovery_duration_cycles"]
            for item in self.episodes
            if item["complete"]
        ]
        if not durations or not recoveries:
            return
        target_half_life = _clamp(median(durations), 10.0, 80.0)
        difference = _clamp(target_half_life - self.strain_half_life, -2.0, 2.0)
        self.strain_half_life = _clamp(self.strain_half_life + difference, 10.0, 80.0)
        target_recovery = _clamp(20.0 / max(1.0, median(recoveries)), 0.75, 1.25)
        rate_difference = _clamp(target_recovery - self.recovery_rate, -0.01, 0.01)
        self.recovery_rate = _clamp(self.recovery_rate + rate_difference, 0.75, 1.25)

    def _personalize(self, fresh: Dict) -> Dict:
        experience = _neutral_experience()
        familiar = bool(
            self.adaptation >= 0.3
            and self.current_episode is not None
            and self.current_episode["fresh_high_cycles"] >= _FAMILIARITY_AFTER_CYCLES
        )
        for name, current in fresh.items():
            relative = 0.0
            baseline = self.baseline.get(name)
            if (
                baseline is not None
                and baseline["sample_count"] >= _MIN_BASELINE_SAMPLES
            ):
                center = float(baseline["baseline"])
                deviation = float(baseline["deviation"] or 0.0)
                relative = _clamp(
                    (current - center - 2.0 * deviation) / max(2.0 * deviation, 0.1)
                )
                relative = _clamp(relative * self.sensitivity)
            weight = min(0.2, 0.2 * self.adaptation * self.confidence)
            experienced = current * (1.0 - weight) + relative * weight
            experience[name] = {
                "risk": current,
                "experienced": _clamp(experienced),
                "expectedness": "familiar"
                if familiar and current >= 0.85
                else "unknown",
            }
        return experience

    def _update_shadow(
        self, fresh: Dict, event_types: set, strain_active: bool
    ) -> None:
        pressure = max(
            item["experienced"]
            for item in self.latest_experience.values()
            if item["experienced"] is not None
        )
        if strain_active or pressure >= 0.85:
            self.shadow_strain = pressure
        else:
            decay = 0.5 ** (1.0 / self.strain_half_life)
            self.shadow_strain = max(pressure, self.shadow_strain * decay)

        if "hardware_strain" in event_types:
            self.shadow_recovery = 0.0
        if "hardware_recovery" in event_types:
            self.shadow_recovery = _clamp(0.2 * self.recovery_rate)
        elif self.shadow_recovery > 0.0:
            core_complete = all(
                name in fresh for name in ("own_load", "environmental_pressure")
            )
            risk = max(fresh.values())
            if core_complete and risk <= 0.6:
                self.shadow_recovery = _clamp(
                    self.shadow_recovery + 0.2 * self.recovery_rate
                )
            elif core_complete and risk > 0.6:
                self.shadow_recovery = 0.0

    def _update_baselines(self, fresh: Dict, cycle: int) -> None:
        for name in _BASELINE_STATES:
            current = fresh.get(name)
            if current is None or current >= 0.85:
                continue
            entry = self.baseline[name]
            entry["sample_count"] += 1
            count = entry["sample_count"]
            alpha = min(0.02, 1.0 / count)
            if entry["baseline"] is None:
                entry["baseline"] = current
                entry["deviation"] = 0.0
            else:
                entry["baseline"] += alpha * (current - entry["baseline"])
                absolute = abs(current - entry["baseline"])
                entry["deviation"] += alpha * (absolute - entry["deviation"])
            entry["last_update_cycle"] = cycle
            entry["confidence"] = min(1.0, count / 200.0)

    def _observation_report(self) -> Dict:
        return {
            "latest_experience": deepcopy(self.latest_experience),
            "shadow_strain": self.shadow_strain,
            "shadow_recovery": self.shadow_recovery,
            "adaptation": self.adaptation,
            "confidence": self.confidence,
        }

    def status(self) -> Dict:
        return deepcopy(self.to_checkpoint())

    def to_checkpoint(self) -> Dict:
        return {
            "personal_profile": {
                "baseline": deepcopy(self.baseline),
                "sensitivity": self.sensitivity,
                "strain_half_life": self.strain_half_life,
                "recovery_rate": self.recovery_rate,
                "adaptation": self.adaptation,
                "confidence": self.confidence,
                "observation_count": self.observation_count,
                "completed_episode_count": self.completed_episode_count,
            },
            "current_episode": deepcopy(self.current_episode),
            "episodes": deepcopy(self.episodes),
            "shadow_strain": self.shadow_strain,
            "shadow_recovery": self.shadow_recovery,
            "latest_experience": deepcopy(self.latest_experience),
        }

    @classmethod
    def from_checkpoint(cls, data: Dict) -> "HardwarePersonalProfile":
        validate_personal_experience(data, legacy=data.get("schema_version", 4) < 4)
        restored = cls()
        profile = data["personal_profile"]
        restored.baseline = deepcopy(profile["baseline"])
        restored.sensitivity = profile["sensitivity"]
        restored.strain_half_life = profile["strain_half_life"]
        restored.recovery_rate = profile["recovery_rate"]
        restored.adaptation = profile["adaptation"]
        restored.confidence = profile["confidence"]
        restored.observation_count = profile["observation_count"]
        restored.completed_episode_count = profile["completed_episode_count"]
        restored.current_episode = deepcopy(data["current_episode"])
        restored.episodes = deepcopy(data["episodes"])
        restored.shadow_strain = data["shadow_strain"]
        restored.shadow_recovery = data["shadow_recovery"]
        # Прежнее переживание не выдаётся за свежее после перезапуска.
        restored.latest_experience = _neutral_experience()
        return restored


def _neutral_domain_latest(freshness="no_observation", reason="no_observation"):
    return {
        "risk": None,
        "experienced": None,
        "expectedness": "unknown",
        "freshness": freshness,
        "reason": reason,
    }


def _neutral_domain_experience() -> Dict:
    return {
        "baseline": _neutral_baseline(),
        "sensitivity": 1.0,
        "strain_half_life": 20.0,
        "recovery_rate": 1.0,
        "adaptation": 0.0,
        "confidence": 0.0,
        "observation_count": 0,
        "completed_episode_count": 0,
        "current_episode": None,
        "episodes": [],
        "latest": _neutral_domain_latest(),
    }


class HardwareDomainPersonalProfile:
    """Независимый per-life опыт physical и storage без поведенческих эффектов."""

    def __init__(self):
        self.domains = {
            name: _neutral_domain_experience() for name in _DOMAIN_STATE_NAMES
        }

    def observe(
        self, states: Dict, *, cycle: int, events: list, slow_states: Dict
    ) -> Dict:
        for name, state_name in _DOMAIN_STATE_NAMES.items():
            domain = self.domains[name]
            state = states[state_name]
            risk = state["value"]
            if risk is None:
                domain["latest"] = _neutral_domain_latest(
                    "unavailable", state["reason"]
                )
                continue
            risk = float(risk)
            strain_reason, recovery_reason = _DOMAIN_EVENT_REASONS[name]
            strain = any(
                event.get("type") == "hardware_strain"
                and event.get("reason") == strain_reason
                for event in events
            )
            recovery = any(
                event.get("type") == "hardware_recovery"
                and event.get("reason") == recovery_reason
                for event in events
            )
            domain["observation_count"] += 1
            domain["confidence"] = min(1.0, domain["observation_count"] / 200.0)
            self._update_episode(
                domain,
                risk,
                state,
                cycle=cycle,
                strain=strain,
                recovery=recovery,
            )
            domain["latest"] = self._personalize(domain, risk, state)
            if (
                domain["current_episode"] is None
                and not slow_states[name]["strain_active"]
                and not strain
                and not recovery
                and risk < 0.85
            ):
                self._update_baseline(domain, risk, cycle)
        return self.to_checkpoint()

    @staticmethod
    def _update_episode(
        domain: Dict,
        risk: float,
        state: Dict,
        *,
        cycle: int,
        strain: bool,
        recovery: bool,
    ) -> None:
        episode = domain["current_episode"]
        if risk >= 0.85:
            if episode is None:
                episode = {
                    "start_cycle": cycle,
                    "strain_cycle": None,
                    "end_cycle": None,
                    "max_pressure": risk,
                    "origin": "unknown",
                    "evidence": [],
                    "slow_cycle": False,
                    "fresh_observations": 0,
                    "fresh_high_cycles": 0,
                    "recovery_duration_cycles": None,
                    "complete": False,
                }
                domain["current_episode"] = episode
            episode["max_pressure"] = max(episode["max_pressure"], risk)
            episode["origin"] = state["origin"]
            episode["evidence"] = list(state["evidence"])[:8]
            episode["fresh_high_cycles"] += 1
        elif episode is not None and episode["strain_cycle"] is None:
            # Короткий всплеск не становится опытом преодоления.
            domain["current_episode"] = None
            episode = None

        if episode is not None:
            episode["fresh_observations"] += 1
        if strain and episode is not None:
            episode["strain_cycle"] = cycle
        if (
            episode is not None
            and episode["strain_cycle"] is not None
            and risk >= 0.85
            and episode["fresh_high_cycles"] > _FAMILIARITY_AFTER_CYCLES
            and domain["adaptation"] < 0.5
        ):
            domain["adaptation"] = min(0.5, domain["adaptation"] + 0.005)
        if not recovery or episode is None or episode["strain_cycle"] is None:
            return

        completed = deepcopy(episode)
        completed["end_cycle"] = cycle
        completed["recovery_duration_cycles"] = cycle - episode["strain_cycle"]
        completed["complete"] = True
        domain["episodes"].append(completed)
        domain["episodes"] = domain["episodes"][-_DOMAIN_EPISODE_LIMIT:]
        domain["current_episode"] = None
        domain["completed_episode_count"] += 1
        domain["adaptation"] = min(1.0, domain["adaptation"] + 0.02)
        HardwareDomainPersonalProfile._learn(domain)

    @staticmethod
    def _learn(domain: Dict) -> None:
        episodes = domain["episodes"]
        if len(episodes) < 3:
            return
        domain["sensitivity"] = _clamp(domain["sensitivity"] - 0.005, 0.8, 1.2)
        durations = [item["end_cycle"] - item["start_cycle"] for item in episodes]
        recoveries = [item["recovery_duration_cycles"] for item in episodes]
        target_half_life = _clamp(median(durations), 10.0, 80.0)
        difference = _clamp(target_half_life - domain["strain_half_life"], -2.0, 2.0)
        domain["strain_half_life"] = _clamp(
            domain["strain_half_life"] + difference, 10.0, 80.0
        )
        target_recovery = _clamp(20.0 / max(1.0, median(recoveries)), 0.75, 1.25)
        rate_difference = _clamp(target_recovery - domain["recovery_rate"], -0.01, 0.01)
        domain["recovery_rate"] = _clamp(
            domain["recovery_rate"] + rate_difference, 0.75, 1.25
        )

    @staticmethod
    def _personalize(domain: Dict, risk: float, state: Dict) -> Dict:
        relative = 0.0
        baseline = domain["baseline"]
        if baseline["sample_count"] >= _MIN_BASELINE_SAMPLES:
            center = float(baseline["baseline"])
            deviation = float(baseline["deviation"] or 0.0)
            relative = _clamp(
                (risk - center - 2.0 * deviation) / max(2.0 * deviation, 0.1)
            )
            relative = _clamp(relative * domain["sensitivity"])
        weight = min(0.2, 0.2 * domain["adaptation"] * domain["confidence"])
        experienced = risk * (1.0 - weight) + relative * weight
        episode = domain["current_episode"]
        familiar = bool(
            domain["adaptation"] >= 0.3
            and episode is not None
            and episode["fresh_high_cycles"] >= _FAMILIARITY_AFTER_CYCLES
        )
        return {
            "risk": risk,
            "experienced": _clamp(experienced),
            "expectedness": "familiar" if familiar and risk >= 0.85 else "unknown",
            "freshness": "fresh",
            "reason": state["reason"],
        }

    @staticmethod
    def _update_baseline(domain: Dict, risk: float, cycle: int) -> None:
        entry = domain["baseline"]
        entry["sample_count"] += 1
        count = entry["sample_count"]
        alpha = min(0.02, 1.0 / count)
        if entry["baseline"] is None:
            entry["baseline"] = risk
            entry["deviation"] = 0.0
        else:
            entry["baseline"] += alpha * (risk - entry["baseline"])
            absolute = abs(risk - entry["baseline"])
            entry["deviation"] += alpha * (absolute - entry["deviation"])
        entry["last_update_cycle"] = cycle
        entry["confidence"] = min(1.0, count / 200.0)

    def to_checkpoint(self) -> Dict:
        return deepcopy(self.domains)

    @classmethod
    def from_checkpoint(cls, data: Dict) -> "HardwareDomainPersonalProfile":
        validate_domain_experience(data)
        restored = cls()
        restored.domains = deepcopy(data["domain_experience"])
        for domain in restored.domains.values():
            domain["latest"] = _neutral_domain_latest(
                "stale", "waiting_for_fresh_observation_after_restart"
            )
        return restored


def _finite(value, path: str, low=0.0, high=1.0) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < low
        or (high is not None and float(value) > high)
    ):
        raise ValueError(f"{path}: expected a finite number in range")


def _cycle(value, path: str, *, optional=False) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path}: expected a nonnegative integer")


def _validate_episode(episode, path: str, *, current: bool) -> None:
    fields = {
        "start_cycle",
        "strain_cycle",
        "end_cycle",
        "max_pressure",
        "origin",
        "evidence",
        "slow_cycle",
        "fresh_observations",
        "fresh_high_cycles",
        "recovery_duration_cycles",
        "complete",
    }
    if not isinstance(episode, dict) or set(episode) != fields:
        raise ValueError(f"{path}: unknown or missing episode field")
    _cycle(episode["start_cycle"], f"{path}.start_cycle")
    _cycle(episode["strain_cycle"], f"{path}.strain_cycle", optional=current)
    _cycle(episode["end_cycle"], f"{path}.end_cycle", optional=current)
    _cycle(
        episode["recovery_duration_cycles"],
        f"{path}.recovery_duration_cycles",
        optional=current,
    )
    _finite(episode["max_pressure"], f"{path}.max_pressure")
    if episode["origin"] not in {"own", "external", "mixed", "unknown"}:
        raise ValueError(f"{path}.origin: unknown origin")
    evidence = episode["evidence"]
    if (
        not isinstance(evidence, list)
        or len(evidence) > 8
        or not all(isinstance(item, str) for item in evidence)
    ):
        raise ValueError(f"{path}.evidence: expected a bounded string list")
    if not isinstance(episode["slow_cycle"], bool):
        raise ValueError(f"{path}.slow_cycle: expected boolean")
    _cycle(episode["fresh_observations"], f"{path}.fresh_observations")
    _cycle(episode["fresh_high_cycles"], f"{path}.fresh_high_cycles")
    if not isinstance(episode["complete"], bool) or episode["complete"] is current:
        raise ValueError(f"{path}.complete: inconsistent episode state")


def validate_personal_experience(state: Dict, *, legacy: bool = False) -> None:
    profile = state.get("personal_profile")
    fields = {
        "baseline",
        "sensitivity",
        "strain_half_life",
        "recovery_rate",
        "adaptation",
        "confidence",
        "observation_count",
        "completed_episode_count",
    }
    if not isinstance(profile, dict) or set(profile) != fields:
        raise ValueError("hardware_interoception.personal_profile: invalid fields")
    baseline = profile["baseline"]
    if not isinstance(baseline, dict) or set(baseline) != set(_BASELINE_STATES):
        raise ValueError("hardware_interoception.personal_profile.baseline: invalid")
    for name, entry in baseline.items():
        path = f"hardware_interoception.personal_profile.baseline.{name}"
        entry_fields = {
            "baseline",
            "deviation",
            "sample_count",
            "last_update_cycle",
            "confidence",
        }
        if not isinstance(entry, dict) or set(entry) != entry_fields:
            raise ValueError(f"{path}: invalid fields")
        if entry["baseline"] is not None:
            _finite(entry["baseline"], f"{path}.baseline")
        if entry["deviation"] is not None:
            _finite(entry["deviation"], f"{path}.deviation")
        _cycle(entry["sample_count"], f"{path}.sample_count")
        _cycle(entry["last_update_cycle"], f"{path}.last_update_cycle", optional=True)
        _finite(entry["confidence"], f"{path}.confidence")
    _finite(profile["sensitivity"], "personal_profile.sensitivity", 0.8, 1.2)
    _finite(
        profile["strain_half_life"], "personal_profile.strain_half_life", 10.0, 80.0
    )
    _finite(profile["recovery_rate"], "personal_profile.recovery_rate", 0.75, 1.25)
    _finite(profile["adaptation"], "personal_profile.adaptation")
    _finite(profile["confidence"], "personal_profile.confidence")
    _cycle(profile["observation_count"], "personal_profile.observation_count")
    _cycle(
        profile["completed_episode_count"], "personal_profile.completed_episode_count"
    )

    current = state.get("current_episode")
    if current is not None:
        _validate_episode(
            current, "hardware_interoception.current_episode", current=True
        )
    episodes = state.get("episodes")
    if not isinstance(episodes, list) or len(episodes) > _EPISODE_LIMIT:
        raise ValueError("hardware_interoception.episodes: expected a bounded list")
    for index, episode in enumerate(episodes):
        _validate_episode(
            episode, f"hardware_interoception.episodes[{index}]", current=False
        )
    _finite(state.get("shadow_strain"), "hardware_interoception.shadow_strain")
    _finite(state.get("shadow_recovery"), "hardware_interoception.shadow_recovery")

    experience = state.get("latest_experience")
    expected = _LEGACY_EXPERIENCE_STATES if legacy else _EXPERIENCE_STATES
    if not isinstance(experience, dict) or set(experience) != set(expected):
        raise ValueError("hardware_interoception.latest_experience: invalid states")
    for name, entry in experience.items():
        path = f"hardware_interoception.latest_experience.{name}"
        if not isinstance(entry, dict) or set(entry) != {
            "risk",
            "experienced",
            "expectedness",
        }:
            raise ValueError(f"{path}: invalid fields")
        for field in ("risk", "experienced"):
            if entry[field] is not None:
                _finite(entry[field], f"{path}.{field}")
        if entry["expectedness"] not in {"unknown", "familiar"}:
            raise ValueError(f"{path}.expectedness: unknown value")


def validate_domain_experience(state: Dict) -> None:
    domains = state.get("domain_experience")
    if not isinstance(domains, dict) or set(domains) != set(_DOMAIN_STATE_NAMES):
        raise ValueError("hardware_interoception.domain_experience: invalid domains")
    fields = {
        "baseline",
        "sensitivity",
        "strain_half_life",
        "recovery_rate",
        "adaptation",
        "confidence",
        "observation_count",
        "completed_episode_count",
        "current_episode",
        "episodes",
        "latest",
    }
    for name, domain in domains.items():
        path = f"hardware_interoception.domain_experience.{name}"
        if not isinstance(domain, dict) or set(domain) != fields:
            raise ValueError(f"{path}: unknown or missing field")
        baseline = domain["baseline"]
        baseline_fields = {
            "baseline",
            "deviation",
            "sample_count",
            "last_update_cycle",
            "confidence",
        }
        if not isinstance(baseline, dict) or set(baseline) != baseline_fields:
            raise ValueError(f"{path}.baseline: invalid fields")
        if baseline["baseline"] is not None:
            _finite(baseline["baseline"], f"{path}.baseline.baseline")
        if baseline["deviation"] is not None:
            _finite(baseline["deviation"], f"{path}.baseline.deviation")
        _cycle(baseline["sample_count"], f"{path}.baseline.sample_count")
        _cycle(
            baseline["last_update_cycle"],
            f"{path}.baseline.last_update_cycle",
            optional=True,
        )
        _finite(baseline["confidence"], f"{path}.baseline.confidence")
        _finite(domain["sensitivity"], f"{path}.sensitivity", 0.8, 1.2)
        _finite(domain["strain_half_life"], f"{path}.strain_half_life", 10.0, 80.0)
        _finite(domain["recovery_rate"], f"{path}.recovery_rate", 0.75, 1.25)
        _finite(domain["adaptation"], f"{path}.adaptation")
        _finite(domain["confidence"], f"{path}.confidence")
        _cycle(domain["observation_count"], f"{path}.observation_count")
        _cycle(domain["completed_episode_count"], f"{path}.completed_episode_count")
        current = domain["current_episode"]
        if current is not None:
            _validate_episode(current, f"{path}.current_episode", current=True)
        episodes = domain["episodes"]
        if not isinstance(episodes, list) or len(episodes) > _DOMAIN_EPISODE_LIMIT:
            raise ValueError(f"{path}.episodes: expected a bounded list")
        for index, episode in enumerate(episodes):
            _validate_episode(episode, f"{path}.episodes[{index}]", current=False)
        latest = domain["latest"]
        if not isinstance(latest, dict) or set(latest) != {
            "risk",
            "experienced",
            "expectedness",
            "freshness",
            "reason",
        }:
            raise ValueError(f"{path}.latest: invalid fields")
        for field in ("risk", "experienced"):
            if latest[field] is not None:
                _finite(latest[field], f"{path}.latest.{field}")
        if latest["expectedness"] not in {"unknown", "familiar"}:
            raise ValueError(f"{path}.latest.expectedness: unknown value")
        if latest["freshness"] not in {
            "no_observation",
            "fresh",
            "stale",
            "unavailable",
        }:
            raise ValueError(f"{path}.latest.freshness: unknown value")
        if not isinstance(latest["reason"], str) or len(latest["reason"]) > 128:
            raise ValueError(f"{path}.latest.reason: invalid string")


__all__ = [
    "HardwareDomainPersonalProfile",
    "HardwarePersonalProfile",
    "validate_domain_experience",
    "validate_personal_experience",
]
