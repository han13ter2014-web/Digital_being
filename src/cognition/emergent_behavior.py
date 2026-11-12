"""Наблюдение устойчивых сочетаний состояний реальных подсистем.

EmergenceEngine не симулирует действия и не приписывает агенту новые
способности. Он лишь сохраняет измерения Core, повторяющиеся комбинации и
изменения сигналов. Выбор действия остаётся в DecisionArbitrator.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime


class BehaviorPattern:
    """Повторяющееся сочетание активных компонентов."""

    def __init__(self, name: str, category: str = "observed"):
        self.name = name
        self.category = category
        self.observation_count = 0
        self.contexts = []
        self.combinations = []
        self.strength = 0.0
        self.consistency = 0.0
        self.created_at = datetime.now()

    def record_observation(self, context: str, active_comps: list[str]):
        self.observation_count += 1
        self.contexts.append(str(context)[:200])
        self.combinations.append(list(active_comps))
        self.contexts = self.contexts[-50:]
        self.combinations = self.combinations[-50:]
        self.strength = min(1.0, self.observation_count / 20.0)
        self.consistency = 1.0 if self.observation_count else 0.0

    def to_dict(self) -> dict:
        combos = Counter(tuple(sorted(combo)) for combo in self.combinations)
        common = list(combos.most_common(1)[0][0]) if combos else []
        return {
            "name": self.name,
            "category": self.category,
            "observation_count": self.observation_count,
            "strength": round(self.strength, 3),
            "consistency": round(self.consistency, 3),
            "top_contexts": self.contexts[-3:],
            "most_common_combination": common,
            "contexts": list(self.contexts),
            "combinations": deepcopy(self.combinations),
        }

    @classmethod
    def from_dict(cls, data: dict):
        pattern = cls(str(data["name"]), str(data.get("category") or "observed"))
        pattern.observation_count = int(data.get("observation_count") or 0)
        pattern.contexts = list(data.get("contexts") or data.get("top_contexts") or [])[
            -50:
        ]
        pattern.combinations = [
            list(combo) for combo in data.get("combinations") or []
        ][-50:]
        pattern.strength = min(1.0, pattern.observation_count / 20.0)
        pattern.consistency = 1.0 if pattern.observation_count else 0.0
        return pattern


class EmergenceEngine:
    """Ограниченный наблюдатель комбинаций и фазовых изменений."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.discovered_patterns: dict[str, BehaviorPattern] = {}
        self.component_signals = defaultdict(list)
        self.component_combinations = Counter()
        self.emergent_events = []
        self.state_history = []
        self.combination_threshold = 3
        self._last_transition_signatures = {}
        self.metrics = {
            "total_emergent_events": 0,
            "unique_patterns_discovered": 0,
            "most_emergent_component": None,
        }

    def record_state(
        self,
        component_states: dict[str, float],
        action_taken: str = "",
        result: str = "",
        *,
        cycle: int = 0,
    ):
        clean = {
            str(name)[:80]: max(0.0, min(1.0, float(value)))
            for name, value in component_states.items()
        }
        state = {
            "timestamp": datetime.now().isoformat(),
            "cycle": max(0, int(cycle)),
            "components": clean,
            "action": str(action_taken or "")[:80],
            "result": str(result or "")[:80],
        }
        self.state_history.append(state)
        self.state_history = self.state_history[-200:]
        for name, value in clean.items():
            self.component_signals[name].append(value)
            self.component_signals[name] = self.component_signals[name][-100:]
        active = tuple(sorted(name for name, value in clean.items() if value > 0.5))
        if len(active) >= 2:
            self.component_combinations[active] += 1
            name = "observed:" + "+".join(active)
            if self.component_combinations[active] >= self.combination_threshold:
                pattern = self.discovered_patterns.get(name)
                if pattern is None:
                    pattern = BehaviorPattern(name)
                    self.discovered_patterns[name] = pattern
                    self.emergent_events.append(
                        {
                            "type": "pattern_discovery",
                            "pattern_name": name,
                            "components": list(active),
                            "cycle": state["cycle"],
                            "timestamp": state["timestamp"],
                        }
                    )
                pattern.record_observation(state["action"] or name, list(active))
        self.emergent_events = self.emergent_events[-100:]
        self.metrics.update(
            {
                "total_emergent_events": len(self.emergent_events),
                "unique_patterns_discovered": len(self.discovered_patterns),
                "most_emergent_component": self._most_emergent_component(),
            }
        )
        return state

    def detect_emergent_patterns(self) -> list[str]:
        """Имена уже подтверждённых повторами паттернов; без мутации."""
        return sorted(self.discovered_patterns)

    def detect_phase_transitions(self) -> list[dict]:
        transitions = []
        for component, values in self.component_signals.items():
            if len(values) < 20:
                continue
            previous = sum(values[-20:-10]) / 10.0
            recent = sum(values[-10:]) / 10.0
            if abs(recent - previous) <= 0.3:
                continue
            direction = "increase" if recent > previous else "decrease"
            signature = (direction, round(previous, 2), round(recent, 2))
            transition = {
                "component": component,
                "from_value": round(previous, 3),
                "to_value": round(recent, 3),
                "direction": direction,
            }
            transitions.append(transition)
            if self._last_transition_signatures.get(component) != signature:
                self._last_transition_signatures[component] = signature
                self.emergent_events.append(
                    {
                        "type": "phase_transition",
                        **transition,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
        self.emergent_events = self.emergent_events[-100:]
        return transitions

    def _most_emergent_component(self):
        counts = Counter(
            component
            for pattern in self.discovered_patterns.values()
            for combo in pattern.combinations[-1:]
            for component in combo
        )
        return counts.most_common(1)[0][0] if counts else None

    def get_emergence_report(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "mode": "observed_only",
            "discovered_patterns": [
                p.to_dict() for p in self.discovered_patterns.values()
            ],
            "emergent_events_count": len(self.emergent_events),
            "unique_patterns": len(self.discovered_patterns),
            "most_emergent_component": self._most_emergent_component(),
            "recent_emergences": deepcopy(self.emergent_events[-5:]),
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "agent_name": self.agent_name,
            "state_history": deepcopy(self.state_history),
            "component_signals": deepcopy(dict(self.component_signals)),
            "component_combinations": [
                {"components": list(combo), "count": count}
                for combo, count in self.component_combinations.items()
            ],
            "discovered_patterns": {
                name: pattern.to_dict()
                for name, pattern in self.discovered_patterns.items()
            },
            "emergent_events": deepcopy(self.emergent_events),
            "transition_signatures": {
                name: list(value)
                for name, value in self._last_transition_signatures.items()
            },
        }

    @classmethod
    def from_checkpoint(cls, data: dict, agent_name: str):
        engine = cls(agent_name)
        engine.state_history = deepcopy(list(data.get("state_history") or []))[-200:]
        for name, values in (data.get("component_signals") or {}).items():
            engine.component_signals[str(name)] = [float(v) for v in values][-100:]
        for item in data.get("component_combinations") or []:
            combo = tuple(sorted(str(value) for value in item["components"]))
            engine.component_combinations[combo] = int(item["count"])
        engine.discovered_patterns = {
            name: BehaviorPattern.from_dict(raw)
            for name, raw in (data.get("discovered_patterns") or {}).items()
        }
        engine.emergent_events = deepcopy(list(data.get("emergent_events") or []))[
            -100:
        ]
        engine._last_transition_signatures = {
            str(name): tuple(value)
            for name, value in (data.get("transition_signatures") or {}).items()
        }
        engine.metrics.update(
            {
                "total_emergent_events": len(engine.emergent_events),
                "unique_patterns_discovered": len(engine.discovered_patterns),
                "most_emergent_component": engine._most_emergent_component(),
            }
        )
        return engine


__all__ = ["BehaviorPattern", "EmergenceEngine"]
