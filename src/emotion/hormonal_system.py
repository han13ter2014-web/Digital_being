"""Теневая эндокринная проекция фактических событий Core.

Уровни вычисляются детерминированно и затухают к базовым значениям. Эта
модель не управляет мотивацией, эмоциями, энергией или выбором действий.
"""

from __future__ import annotations

from copy import deepcopy
import math

from src.emotion.hormonal_profile import HormonalProfile, validate_hormonal_profile


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
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path}: expected a nonnegative integer")


class HormoneLevel:
    def __init__(
        self, name: str, base_level: float = 0.5, half_life_seconds: int = None
    ):
        self.name = name
        self.current_level = float(base_level)
        self.base_level = float(base_level)
        self.max_level = 1.0
        self.min_level = 0.0
        self.half_life = half_life_seconds

    def __repr__(self):
        return f"{self.name}: {self.current_level:.2f}"


class HormonalSystem:
    HORMONE_SPECS = {
        "dopamine": ("Дофамин", 0.4, 300),
        "serotonin": ("Серотонин", 0.5, 600),
        "oxytocin": ("Окситоцин", 0.3, 900),
        "cortisol": ("Кортизол", 0.15, 60),
        "prolactin": ("Пролактин", 0.2, 450),
    }
    HORMONES = {key: HormoneLevel(*spec) for key, spec in HORMONE_SPECS.items()}

    def __init__(self):
        self.hormones = {name: spec.base_level for name, spec in self.HORMONES.items()}
        self.profile = HormonalProfile(self.HORMONES)
        self.history = []
        self.cycle_time = 0.0
        self.legacy_mixed_time = False

    def _update_cycle(self, delta_seconds: float):
        if (
            isinstance(delta_seconds, bool)
            or not isinstance(delta_seconds, (int, float))
            or not math.isfinite(float(delta_seconds))
            or float(delta_seconds) < 0.0
        ):
            raise ValueError("hormone tick: expected finite nonnegative seconds")
        delta = float(delta_seconds)
        self.cycle_time += delta
        for name, spec in self.HORMONES.items():
            if not spec.half_life:
                continue
            profile = self.profile.values[name]
            baseline = profile["baseline"]
            half_life = spec.half_life * profile["half_life_scale"]
            decay = 2 ** (-delta / half_life)
            level = (self.hormones[name] - baseline) * decay + baseline
            self.hormones[name] = max(spec.min_level, min(spec.max_level, level))

    def tick(self, delta_seconds: float = 1.0):
        self._update_cycle(delta_seconds)
        return dict(self.hormones)

    @staticmethod
    def _validated_provenance(data: dict | None) -> dict:
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("hormone provenance: expected dictionary")
        allowed = {
            "source",
            "cycle",
            "action",
            "reason",
            "origin",
            "confidence",
            "duration_cycles",
            "evidence",
        }
        if set(data) - allowed:
            raise ValueError("hormone provenance: unknown field")
        if data.get("source") not in {"action_outcome", "social_message", "hardware"}:
            raise ValueError("hormone provenance: unknown source")

        result = {}
        for name in ("source", "action", "reason", "origin"):
            value = data.get(name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f"hormone provenance.{name}: invalid string")
            result[name] = value
        if "origin" in result and result["origin"] not in {
            "own",
            "external",
            "mixed",
            "unknown",
        }:
            raise ValueError("hormone provenance.origin: unknown origin")
        for name in ("cycle", "duration_cycles"):
            value = data.get(name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"hormone provenance.{name}: invalid integer")
            result[name] = value
        confidence = data.get("confidence")
        if confidence is not None:
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0.0 <= float(confidence) <= 1.0
            ):
                raise ValueError("hormone provenance.confidence: invalid number")
            result["confidence"] = float(confidence)
        evidence = data.get("evidence")
        if evidence is not None:
            if (
                not isinstance(evidence, list)
                or len(evidence) > 8
                or any(
                    not isinstance(item, str) or not item.strip() or len(item) > 128
                    for item in evidence
                )
            ):
                raise ValueError("hormone provenance.evidence: invalid string list")
            result["evidence"] = list(evidence)
        return result

    def process_event(
        self,
        event_type: str,
        intensity: float,
        quality: str = "neutral",
        *,
        provenance: dict | None = None,
    ) -> dict:
        event_type = str(event_type)
        intensity = max(0.0, min(2.0, float(intensity)))
        provenance = self._validated_provenance(provenance)
        # Событие мгновенно меняет уровни, но не продвигает время и не вызывает
        # затухание: время принадлежит только явному tick(delta_seconds).
        before = dict(self.hormones)
        if event_type in {"reward", "success", "achievement"}:
            self._change("dopamine", min(0.4, intensity * 0.15))
            self._change("serotonin", min(0.2, intensity * 0.08))
        elif event_type in {"stress", "threat", "failure", "overload"}:
            self._change("cortisol", min(0.5, intensity * 0.25))
            self._change("dopamine", -intensity * 0.05)
        elif event_type == "hardware_strain":
            # Только длительное давление с доказательствами от наблюдателя.
            # Низкий CPU не является наградой, а всплеск сюда не попадает.
            self._change("cortisol", min(0.3, intensity * 0.12))
        elif event_type == "hardware_recovery":
            # Восстановление подтверждено свежими продолжительными показаниями.
            self._change("serotonin", min(0.1, intensity * 0.06))
            self._change("cortisol", -intensity * 0.06)
        elif event_type in {"connection", "empathy", "trust", "care"}:
            self._change("oxytocin", min(0.35, intensity * 0.12))
            self._change("cortisol", -intensity * 0.04)
        elif event_type == "complement":
            self._change("dopamine", min(0.3, intensity * 0.10))
            self._change("serotonin", min(0.15, intensity * 0.06))
        elif event_type in {"apology", "forgiveness"}:
            self._change("oxytocin", min(0.3, intensity * 0.10))
        elif event_type == "learning":
            self._change("dopamine", min(0.15, intensity * 0.05))
            self._change("serotonin", min(0.1, intensity * 0.03))
        changes = {
            name: round(self.hormones[name] - before[name], 6)
            for name in self.hormones
            if abs(self.hormones[name] - before[name]) > 1e-12
        }
        entry = {
            "time": self.cycle_time,
            "event": event_type,
            "quality": str(quality),
            "intensity": intensity,
            "changes": changes,
        }
        if provenance:
            entry["provenance"] = deepcopy(provenance)
        self.history.append(entry)
        self.history = self.history[-200:]
        self.profile.observe(
            event=event_type,
            time=self.cycle_time,
            intensity=intensity,
            changes=changes,
            provenance=provenance,
        )
        report = {
            "event": event_type,
            "intensity": intensity,
            "quality": quality,
            "changes": changes,
        }
        if provenance:
            report["provenance"] = deepcopy(provenance)
        return report

    def _change(self, name: str, delta: float):
        spec = self.HORMONES[name]
        sensitivity = self.profile.values[name]["sensitivity"]
        self.hormones[name] = max(
            spec.min_level,
            min(spec.max_level, self.hormones[name] + delta * sensitivity),
        )

    def get_emotional_state(self) -> dict:
        dopamine = self.hormones["dopamine"]
        serotonin = self.hormones["serotonin"]
        oxytocin = self.hormones["oxytocin"]
        cortisol = self.hormones["cortisol"]
        mood_score = serotonin - cortisol * 2
        return {
            "mode": "shadow_interoception",
            "motivation": "высокая"
            if dopamine > 0.6
            else "умеренная"
            if dopamine > 0.4
            else "низкая",
            "mood": "спокойное"
            if mood_score > 0.3
            else "встревоженное"
            if mood_score < -0.2
            else "нейтральное",
            "connection": "глубокая"
            if oxytocin > 0.6
            else "умеренная"
            if oxytocin > 0.4
            else "поверхностная",
            "hormone_levels": dict(self.hormones),
            "risk_factors": [risk["type"] for risk in self.risk_assessment()],
        }

    def risk_assessment(self) -> list[dict]:
        risks = []
        if self.hormones["cortisol"] > 0.35:
            risks.append(
                {
                    "type": "хронический стресс",
                    "severity": "высокий"
                    if self.hormones["cortisol"] > 0.45
                    else "средний",
                }
            )
        if self.hormones["dopamine"] < 0.25:
            risks.append(
                {
                    "type": "низкий тонус награды",
                    "severity": "высокий"
                    if self.hormones["dopamine"] < 0.2
                    else "средний",
                }
            )
        if self.hormones["oxytocin"] < 0.25:
            risks.append(
                {"type": "мало наблюдаемых социальных контактов", "severity": "средний"}
            )
        return risks

    def get_homeostasis_goal(self) -> dict:
        return {"dopamine": 0.5, "serotonin": 0.6, "oxytocin": 0.4, "cortisol": 0.15}

    def get_current_state_summary(self) -> str:
        state = self.get_emotional_state()
        return "\n".join(
            [
                "Гормональная теневая модель (не управляет поведением)",
                *(f"{name}: {level:.3f}" for name, level in self.hormones.items()),
                f"Состояние: {state['mood']}",
            ]
        )

    def to_checkpoint(self) -> dict:
        return {
            "schema_version": 2,
            "time_model": "tick_only",
            "legacy_mixed_time": self.legacy_mixed_time,
            "hormones": dict(self.hormones),
            "history": deepcopy(self.history),
            "episodes": deepcopy(self.profile.episodes),
            "profile": self.profile.to_checkpoint(),
            "cycle_time": self.cycle_time,
        }

    @staticmethod
    def _validate_changes(changes, names: set, path: str, *, nonempty=False) -> None:
        if (
            not isinstance(changes, dict)
            or set(changes) - names
            or (nonempty and not changes)
        ):
            raise ValueError(f"{path}: unknown or missing hormone change")
        for name, value in changes.items():
            _number(value, f"{path}.{name}", low=-1.0, high=1.0)

    @classmethod
    def _validate_history(cls, history, path: str) -> None:
        if not isinstance(history, list) or len(history) > 200:
            raise ValueError(f"{path}: expected a bounded list")
        required = {"time", "event", "quality", "intensity", "changes"}
        allowed = required | {"provenance", "provenance_status"}
        for index, entry in enumerate(history):
            item_path = f"{path}[{index}]"
            if (
                not isinstance(entry, dict)
                or not required <= set(entry)
                or set(entry) - allowed
            ):
                raise ValueError(f"{item_path}: unknown or missing history field")
            _number(entry["time"], f"{item_path}.time", low=0.0)
            _number(entry["intensity"], f"{item_path}.intensity", low=0.0, high=2.0)
            for field in ("event", "quality"):
                if not isinstance(entry[field], str) or len(entry[field]) > 256:
                    raise ValueError(f"{item_path}.{field}: expected a bounded string")
            cls._validate_changes(
                entry["changes"], set(cls.HORMONES), f"{item_path}.changes"
            )
            if "provenance" in entry:
                cls._validated_provenance(entry["provenance"])
            status = entry.get("provenance_status")
            if status is not None and (status != "legacy" or "provenance" in entry):
                raise ValueError(f"{item_path}.provenance_status: invalid")

    @classmethod
    def _validate_episodes(cls, episodes, path: str) -> None:
        if not isinstance(episodes, list) or len(episodes) > 50:
            raise ValueError(f"{path}: expected a bounded list")
        required = {"time", "event", "source", "intensity", "changes"}
        allowed = required | {"cycle", "reason", "action", "origin"}
        sources = {"action_outcome", "social_message", "hardware"}
        for index, entry in enumerate(episodes):
            item_path = f"{path}[{index}]"
            if (
                not isinstance(entry, dict)
                or not required <= set(entry)
                or set(entry) - allowed
            ):
                raise ValueError(f"{item_path}: unknown or missing episode field")
            _number(entry["time"], f"{item_path}.time", low=0.0)
            _number(entry["intensity"], f"{item_path}.intensity", low=0.0, high=2.0)
            if not isinstance(entry["event"], str) or len(entry["event"]) > 256:
                raise ValueError(f"{item_path}.event: expected a bounded string")
            if entry["source"] not in sources:
                raise ValueError(f"{item_path}.source: unknown source")
            cls._validate_changes(
                entry["changes"],
                set(cls.HORMONES),
                f"{item_path}.changes",
                nonempty=True,
            )
            if "cycle" in entry:
                _count(entry["cycle"], f"{item_path}.cycle")
            for field in ("reason", "action"):
                if field in entry and (
                    not isinstance(entry[field], str)
                    or not entry[field].strip()
                    or len(entry[field]) > 128
                ):
                    raise ValueError(f"{item_path}.{field}: invalid string")
            if "origin" in entry and entry["origin"] not in {
                "own",
                "external",
                "mixed",
                "unknown",
            }:
                raise ValueError(f"{item_path}.origin: unknown origin")

    @classmethod
    def validate_checkpoint(cls, data: dict, path: str = "hormones") -> None:
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected dictionary")
        version = data.get("schema_version")
        if version not in {1, 2}:
            raise ValueError(f"{path}.schema_version: unsupported")
        required = {"schema_version", "hormones", "history", "cycle_time"}
        current = {"time_model", "legacy_mixed_time", "episodes", "profile"}
        expected = required | current if version == 2 else required
        if set(data) != expected:
            raise ValueError(f"{path}: unknown or missing checkpoint field")

        levels = data["hormones"]
        if not isinstance(levels, dict) or set(levels) != set(cls.HORMONES):
            raise ValueError(f"{path}.levels: unknown or missing hormone")
        for name, value in levels.items():
            _number(value, f"{path}.levels.{name}", low=0.0, high=1.0)
        cls._validate_history(data["history"], f"{path}.history")
        _number(data["cycle_time"], f"{path}.cycle_time", low=0.0)
        if version == 1:
            return
        if data["time_model"] != "tick_only":
            raise ValueError(f"{path}.time_model: unsupported")
        if not isinstance(data["legacy_mixed_time"], bool):
            raise ValueError(f"{path}.legacy_mixed_time: expected boolean")
        cls._validate_episodes(data["episodes"], f"{path}.episodes")
        validate_hormonal_profile(data["profile"], cls.HORMONES, f"{path}.profile")

    @classmethod
    def from_checkpoint(cls, data: dict):
        cls.validate_checkpoint(data)
        system = cls()
        system.hormones = deepcopy(data["hormones"])
        system.history = deepcopy(data["history"])[-200:]
        system.cycle_time = float(data["cycle_time"])
        if data["schema_version"] == 1:
            system.legacy_mixed_time = True
            for entry in system.history:
                if "provenance" not in entry:
                    entry["provenance_status"] = "legacy"
            return system
        system.legacy_mixed_time = data["legacy_mixed_time"]
        system.profile = HormonalProfile.from_checkpoint(data["profile"], cls.HORMONES)
        system.profile.episodes = deepcopy(data["episodes"])
        return system


__all__ = ["HormoneLevel", "HormonalSystem"]
