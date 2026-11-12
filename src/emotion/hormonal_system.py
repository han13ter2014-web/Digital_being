"""Теневая эндокринная проекция фактических событий Core.

Уровни вычисляются детерминированно и затухают к базовым значениям. Эта
модель не управляет мотивацией, эмоциями, энергией или выбором действий.
"""

from __future__ import annotations

from copy import deepcopy


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
        self.history = []
        self.cycle_time = 0.0

    def _update_cycle(self, delta_seconds: float):
        delta = max(0.0, float(delta_seconds))
        self.cycle_time += delta
        for name, spec in self.HORMONES.items():
            if not spec.half_life:
                continue
            decay = 2 ** (-delta / spec.half_life)
            level = (self.hormones[name] - spec.base_level) * decay + spec.base_level
            self.hormones[name] = max(spec.min_level, min(spec.max_level, level))

    def tick(self, delta_seconds: float = 1.0):
        self._update_cycle(delta_seconds)
        return dict(self.hormones)

    def process_event(
        self, event_type: str, intensity: float, quality: str = "neutral"
    ) -> dict:
        event_type = str(event_type)
        intensity = max(0.0, min(2.0, float(intensity)))
        self._update_cycle(1.0)
        before = dict(self.hormones)
        if event_type in {"reward", "success", "achievement"}:
            self._change("dopamine", min(0.4, intensity * 0.15))
            self._change("serotonin", min(0.2, intensity * 0.08))
        elif event_type in {"stress", "threat", "failure", "overload"}:
            self._change("cortisol", min(0.5, intensity * 0.25))
            self._change("dopamine", -intensity * 0.05)
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
        self.history.append(entry)
        self.history = self.history[-200:]
        return {
            "event": event_type,
            "intensity": intensity,
            "quality": quality,
            "changes": changes,
        }

    def _change(self, name: str, delta: float):
        spec = self.HORMONES[name]
        self.hormones[name] = max(
            spec.min_level, min(spec.max_level, self.hormones[name] + delta)
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
            "schema_version": 1,
            "hormones": dict(self.hormones),
            "history": deepcopy(self.history),
            "cycle_time": self.cycle_time,
        }

    @classmethod
    def from_checkpoint(cls, data: dict):
        system = cls()
        for name, value in (data.get("hormones") or {}).items():
            if name in system.hormones:
                system.hormones[name] = max(0.0, min(1.0, float(value)))
        system.history = deepcopy(list(data.get("history") or []))[-200:]
        system.cycle_time = float(data.get("cycle_time", 0.0))
        return system


__all__ = ["HormoneLevel", "HormonalSystem"]
