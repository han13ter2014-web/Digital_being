"""Единый read-only адаптер сохранённых наблюдателей жизненного опыта.

Все входы приходят из уже выполненных действий и уже полученных реплик.
Наблюдатели не создают цели/кандидатов, не меняют мотивацию, энергию,
канонические эмоции, ценности или конфигурацию и не исполняют код.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, Optional

from src.cognition.emergent_behavior import EmergenceEngine
from src.cognition.personality import Personality
from src.core.buffered_logger import get_logger
from src.emotion.hormonal_system import HormonalSystem
from src.evolution.thinking_patterns import ThinkingPatternLibrary


PATTERN_BY_ACTION = {
    "explore": "analytical_thinking", "hypothesis": "analytical_thinking",
    "know_answer": "analytical_thinking", "web_search": "analytical_thinking",
    "read_news": "analytical_thinking", "browse_web": "analytical_thinking",
    "decomposition": "decomposition", "synthesis": "creative_synthesis",
    "create_draft": "creative_synthesis", "draw": "creative_synthesis",
    "compose_music": "creative_synthesis", "reflection": "self_reflection",
}


def _number(value, path, *, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: expected a finite number")
    value = float(value)
    if value != value or value in {float("inf"), float("-inf")}:
        raise ValueError(f"{path}: expected a finite number")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{path}: number out of range")
    return value


def _integer(value, path, *, low=0, high=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}: expected integer")
    if value < low or high is not None and value > high:
        raise ValueError(f"{path}: integer out of range")


def _list(value, path, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{path}: expected a bounded list")
    return value


def _dict(value, path):
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected dictionary")
    return value


class IntegratedExperience:
    """Владелец четырёх наблюдателей и их ограниченной истории."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.personality = Personality(agent_name)
        self.emergence = EmergenceEngine(agent_name)
        self.thinking_patterns = ThinkingPatternLibrary()
        self.hormones = HormonalSystem()
        self._last_tick_cycle = None

    def observe_action_outcome(self, agent, entry: Dict, outcome=None,
                               error: Optional[Exception] = None) -> Dict:
        action = str(entry.get("action") or "")
        normalized = agent._normalize_action(action)
        params = entry.get("params") or {}
        target = str(entry.get("target") or params.get("topic")
                     or params.get("target") or "")
        had_effect = bool(outcome is not None and getattr(outcome, "had_effect", False))
        reason = str(getattr(outcome, "reason", "") or "")
        cycle = int(agent.cycle_count)
        self.personality.observe_action(
            normalized, target, had_effect, cycle=cycle,
            error=str(error) if error is not None else "",
        )
        pattern = PATTERN_BY_ACTION.get(normalized)
        if pattern:
            self.thinking_patterns.use_pattern(
                pattern, had_effect, target or action
            )
        if error is not None:
            self.hormones.process_event("failure", 1.0, "negative")
        elif had_effect:
            event = "learning" if normalized in {
                "explore", "hypothesis", "know_answer", "decomposition", "synthesis",
                "web_search", "read_news", "browse_web",
            } else "success"
            self.hormones.process_event(event, 1.0, "positive")
        elif reason.startswith("denied:"):
            self.hormones.process_event("stress", 0.5, "negative")
        components = self._canonical_components(agent)
        state = self.emergence.record_state(
            components, normalized,
            "effect" if had_effect else "error" if error is not None else "no_effect",
            cycle=cycle,
        )
        self.personality.project_canonical_state(agent)
        self.personality.update_derived_state()
        return {
            "action": normalized, "had_effect": had_effect,
            "pattern": pattern, "components": state["components"],
        }

    def observe_user_message(self, agent, text: str, cycle: int) -> None:
        self.personality.observe_user_message(text, cycle=cycle)
        self.hormones.process_event("connection", 1.0, "positive")
        self.personality.project_canonical_state(agent)

    def tick(self, agent, cycle: int) -> Dict:
        cycle = int(cycle)
        if self._last_tick_cycle == cycle:
            return {"skipped": "duplicate_cycle"}
        self._last_tick_cycle = cycle
        self.hormones.tick(1.0)
        self.personality.project_canonical_state(agent)
        self.personality.update_derived_state()
        transitions = self.emergence.detect_phase_transitions()
        return {"cycle": cycle, "phase_transitions": transitions}

    def status(self) -> Dict:
        return {
            "mode": "observed_only",
            "personality": self.personality.get_personality_summary(),
            "thinking_patterns": self.thinking_patterns.get_status(),
            "emergence": self.emergence.get_emergence_report(),
            "hormones": self.hormones.get_emotional_state(),
        }

    @staticmethod
    def _canonical_components(agent) -> Dict[str, float]:
        from config.simulation_config import LR_CONFIG

        intero = getattr(agent, "interoception", None)
        state = getattr(intero, "state", None)
        fatigue = max(0.0, min(1.0, float(getattr(state, "fatigue", 0.0) or 0.0)))
        models = getattr(agent, "mental_models", None)
        concepts = getattr(models, "concepts", {}) or {}
        emotional = getattr(agent, "emotional_state", None)
        levels = getattr(emotional, "levels", {}) or {}
        meta = getattr(agent, "meta_cognition", None)
        cognitive = getattr(meta, "cognitive_state", None)
        maximum = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0) or 200.0)
        return {
            "energy": max(0.0, min(1.0, float(agent.energy) / maximum)),
            "body_readiness": 1.0 - fatigue,
            "memory": max(0.0, min(1.0, len(concepts) / 100.0)),
            "goals": 1.0 if getattr(agent, "active_goal", None) else 0.0,
            "emotions": max((float(value) for value in levels.values()), default=0.0),
            "metacognition": max(0.0, min(1.0, float(
                getattr(cognitive, "cognitive_load", 0.0) or 0.0
            ))),
        }

    def to_checkpoint(self) -> Dict:
        return {
            "schema_version": 1,
            "personality": self.personality.to_dict(),
            "emergence": self.emergence.to_dict(),
            "thinking_patterns": self.thinking_patterns.to_dict(),
            "hormones": self.hormones.to_checkpoint(),
            "last_tick_cycle": self._last_tick_cycle,
        }

    @classmethod
    def from_checkpoint(cls, data: Dict, agent_name: str):
        validate_integrated_experience(data)
        integrated = cls(agent_name)
        integrated.personality = Personality.from_checkpoint(
            data["personality"], agent_name
        )
        integrated.emergence = EmergenceEngine.from_checkpoint(
            data["emergence"], agent_name
        )
        integrated.thinking_patterns = ThinkingPatternLibrary.from_checkpoint(
            data["thinking_patterns"]
        )
        integrated.hormones = HormonalSystem.from_checkpoint(data["hormones"])
        integrated._last_tick_cycle = data.get("last_tick_cycle")
        return integrated


def initialize_integrated_experience(agent) -> IntegratedExperience:
    integrated = IntegratedExperience(agent.name)
    integrated.personality.project_canonical_state(agent)
    integrated.personality.update_derived_state()
    agent.integrated_experience = integrated
    # Понятные алиасы для диагностики; состояние остаётся в одном владельце.
    agent.personality = integrated.personality
    agent.emergence_engine = integrated.emergence
    agent.thinking_patterns = integrated.thinking_patterns
    agent.hormonal_system = integrated.hormones
    return integrated


def observe_integrated_action(agent, entry, outcome=None, error=None) -> None:
    integrated = getattr(agent, "integrated_experience", None)
    if integrated is None:
        return
    try:
        integrated.observe_action_outcome(agent, entry, outcome, error)
        metrics = getattr(agent, "metrics", None)
        if metrics is not None:
            cycle = int(agent.cycle_count)
            metrics.increment("action_outcomes", cycle=cycle)
            if outcome is not None and getattr(outcome, "had_effect", False):
                metrics.increment("action_effects", cycle=cycle)
            if error is not None:
                metrics.increment("action_errors", cycle=cycle)
    except Exception as exc:
        get_logger().log(f"[INTEGRATED_EXPERIENCE] outcome error: {exc}")


def observe_integrated_user_message(agent, text: str, cycle: int) -> None:
    integrated = getattr(agent, "integrated_experience", None)
    if integrated is None:
        return
    try:
        integrated.observe_user_message(agent, text, int(cycle))
        metrics = getattr(agent, "metrics", None)
        if metrics is not None:
            metrics.increment("social_messages", cycle=int(cycle))
    except Exception as exc:
        get_logger().log(f"[INTEGRATED_EXPERIENCE] social error: {exc}")


def tick_integrated_experience(agent, cycle: int) -> Optional[Dict]:
    integrated = getattr(agent, "integrated_experience", None)
    if integrated is None:
        return None
    try:
        report = integrated.tick(agent, cycle)
        metrics = getattr(agent, "metrics", None)
        if metrics is not None and getattr(agent, "_last_metrics_cycle", None) != int(cycle):
            agent._last_metrics_cycle = int(cycle)
            metrics.record("energy", float(agent.energy), cycle=int(cycle))
            metrics.record("intelligence", float(agent.intelligence), cycle=int(cycle))
            metrics.record("cycle_count", float(agent.cycle_count), cycle=int(cycle))
            metrics.record("completed_goals", float(agent.completed_goals), cycle=int(cycle))
            concepts = getattr(getattr(agent, "mental_models", None), "concepts", {})
            metrics.record("concepts_count", float(len(concepts)), cycle=int(cycle))
        return report
    except Exception as exc:
        get_logger().log(f"[INTEGRATED_EXPERIENCE] tick error: {exc}")
        return {"error": str(exc)}


def capture_integrated_experience(agent) -> Dict:
    integrated = getattr(agent, "integrated_experience", None)
    return integrated.to_checkpoint() if integrated is not None else {}


def validate_integrated_experience(state: Dict) -> None:
    _dict(state, "integrated_experience")
    if state.get("schema_version") != 1:
        raise ValueError("integrated_experience.schema_version: unsupported")
    personality = _dict(state.get("personality"), "integrated_experience.personality")
    if personality.get("schema_version") != 1:
        raise ValueError("integrated_experience.personality.schema_version: unsupported")
    narrative = _dict(personality.get("narrative"), "integrated_experience.personality.narrative")
    memories = _list(narrative.get("memories"), "integrated_experience.personality.memories", 200)
    for index, memory in enumerate(memories):
        path = f"integrated_experience.personality.memories[{index}]"
        _dict(memory, path)
        for field in ("type", "context", "emotional_tone", "action"):
            if not isinstance(memory.get(field), str):
                raise ValueError(f"{path}.{field}: expected string")
        _integer(memory.get("cycle"), f"{path}.cycle")
        _number(memory.get("significance"), f"{path}.significance", low=0.0, high=1.0)
        if not isinstance(memory.get("had_effect"), bool):
            raise ValueError(f"{path}.had_effect: expected boolean")
    _list(narrative.get("milestones"), "integrated_experience.personality.milestones", 50)
    _list(personality.get("value_history"), "integrated_experience.personality.value_history", 50)

    emergence = _dict(state.get("emergence"), "integrated_experience.emergence")
    if emergence.get("schema_version") != 1:
        raise ValueError("integrated_experience.emergence.schema_version: unsupported")
    states = _list(emergence.get("state_history"), "integrated_experience.emergence.state_history", 200)
    for index, item in enumerate(states):
        path = f"integrated_experience.emergence.state_history[{index}]"
        _dict(item, path)
        for name, value in _dict(item.get("components"), f"{path}.components").items():
            if not isinstance(name, str):
                raise ValueError(f"{path}.components: expected string key")
            _number(value, f"{path}.components.{name}", low=0.0, high=1.0)
    for name, values in _dict(emergence.get("component_signals"), "integrated_experience.emergence.signals").items():
        for value in _list(values, f"integrated_experience.emergence.signals.{name}", 100):
            _number(value, f"integrated_experience.emergence.signals.{name}", low=0.0, high=1.0)
    _list(emergence.get("component_combinations"), "integrated_experience.emergence.combinations", 1000)
    for name, raw in _dict(emergence.get("discovered_patterns"), "integrated_experience.emergence.patterns").items():
        path = f"integrated_experience.emergence.patterns.{name}"
        _dict(raw, path)
        _integer(raw.get("observation_count"), f"{path}.observation_count")
        _list(raw.get("contexts"), f"{path}.contexts", 50)
        _list(raw.get("combinations"), f"{path}.combinations", 50)
    _list(emergence.get("emergent_events"), "integrated_experience.emergence.events", 100)
    _dict(emergence.get("transition_signatures"), "integrated_experience.emergence.transitions")

    patterns = _dict(state.get("thinking_patterns"), "integrated_experience.thinking_patterns")
    if patterns.get("schema_version") != 1:
        raise ValueError("integrated_experience.thinking_patterns.schema_version: unsupported")
    for name, raw in _dict(patterns.get("patterns"), "integrated_experience.thinking_patterns.patterns").items():
        path = f"integrated_experience.thinking_patterns.patterns.{name}"
        _dict(raw, path)
        if raw.get("name") != name or not isinstance(raw.get("pattern_type"), str):
            raise ValueError(f"{path}: inconsistent pattern identity")
        _number(raw.get("weight"), f"{path}.weight", low=0.0, high=1.0)
        usage = raw.get("usage_count")
        successes = raw.get("success_count")
        failures = raw.get("failure_count")
        for field, value in (("usage", usage), ("successes", successes), ("failures", failures)):
            _integer(value, f"{path}.{field}")
        if successes + failures != usage:
            raise ValueError(f"{path}: outcome counts do not match usage")
        _list(raw.get("effective_contexts"), f"{path}.effective_contexts", 50)
        _list(raw.get("failed_contexts"), f"{path}.failed_contexts", 50)
        _list(raw.get("history"), f"{path}.history", 100)
    _list(patterns.get("created_patterns"), "integrated_experience.thinking_patterns.created", 1000)
    _list(patterns.get("evolution_log"), "integrated_experience.thinking_patterns.log", 200)

    hormones = _dict(state.get("hormones"), "integrated_experience.hormones")
    if hormones.get("schema_version") != 1:
        raise ValueError("integrated_experience.hormones.schema_version: unsupported")
    levels = _dict(hormones.get("hormones"), "integrated_experience.hormones.levels")
    if set(levels) != set(HormonalSystem.HORMONES):
        raise ValueError("integrated_experience.hormones.levels: unknown or missing hormone")
    for name, value in levels.items():
        _number(value, f"integrated_experience.hormones.levels.{name}", low=0.0, high=1.0)
    _list(hormones.get("history"), "integrated_experience.hormones.history", 200)
    _number(hormones.get("cycle_time"), "integrated_experience.hormones.cycle_time", low=0.0)
    last = state.get("last_tick_cycle")
    if last is not None:
        _integer(last, "integrated_experience.last_tick_cycle")


def stage_integrated_experience(state: Optional[Dict], agent_name: str):
    if not state:
        return IntegratedExperience(agent_name)
    return IntegratedExperience.from_checkpoint(deepcopy(state), agent_name)


def restore_integrated_experience(agent, staged: IntegratedExperience) -> None:
    agent.integrated_experience = staged
    agent.personality = staged.personality
    agent.emergence_engine = staged.emergence
    agent.thinking_patterns = staged.thinking_patterns
    agent.hormonal_system = staged.hormones
    staged.personality.project_canonical_state(agent)
    staged.personality.update_derived_state()


__all__ = [
    "IntegratedExperience", "initialize_integrated_experience",
    "observe_integrated_action", "observe_integrated_user_message",
    "tick_integrated_experience", "capture_integrated_experience",
    "validate_integrated_experience", "stage_integrated_experience",
    "restore_integrated_experience",
]
