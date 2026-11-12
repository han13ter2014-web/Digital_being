"""Наблюдатели текстового восприятия и метакогниции основного контура.

SensoryInterface анализирует только реальный текст, не подменяя stimulus.
MetaCognitiveSystem наблюдает выбранные намерения и их ActionOutcome; она не
добавляет кандидатов, не меняет оценки и не создаёт цели.
"""

from copy import deepcopy
from datetime import datetime
from typing import Dict, Optional

from config.simulation_config import SIM_CONFIG
from src.cognition.meta_cognition import MetaCognitiveSystem, ThoughtTrace
from src.core.buffered_logger import get_logger


def perceive_text(agent, text: str) -> Optional[Dict]:
    """Сохранить текстовый sensory-report, оставив perceive passthrough."""
    sensory = getattr(agent, "sensory_interface", None)
    if sensory is None:
        return None
    try:
        report = sensory.integrate_multisensory(
            visual=sensory.perceive_visual(text),
            auditory=sensory.perceive_auditory(text),
            tactile=sensory.perceive_tactile(text),
        )
        agent._last_sensory_perception = report
        engine = getattr(agent, "continuous_time", None)
        if engine is not None:
            engine.emit_event(
                "stimulus",
                {
                    "modality": "text",
                    "clarity": report["overall_clarity"],
                    "patterns": list(report["visual"]["patterns"]),
                },
            )
        return report
    except Exception as exc:
        get_logger().log(f"[SENSORY] text perception error: {exc}")
        return None


def observe_action_intention(agent, selection: Dict, entry: Dict) -> None:
    meta = getattr(agent, "meta_cognition", None)
    if meta is None:
        return
    try:
        action = str(selection.get("action") or "")
        params = selection.get("params") or {}
        target = str(params.get("topic") or params.get("target") or "")
        simulation = selection.get("simulation") or {}
        trace = meta.observe_thought(
            "analysis", f"намерение: {action}; тема: {target or 'без темы'}"
        )
        trace.resulting_actions.append(action)
        probability = simulation.get("predicted_effect_probability")
        if probability is not None:
            trace.confidence = float(probability)
        node = getattr(agent, "mental_models", None)
        node = getattr(node, "concepts", {}).get(target) if target else None
        if node is not None:
            trace.confidence = float(node.confidence)
            # Знание регистрируется в этом же trace, а не второй мыслью.
            meta.recognize_knowledge(
                target, float(node.confidence), record_observation=False
            )
        meta.cognitive_state.active_models = [target] if node is not None else []
        meta.cognitive_state.monitoring = True
        meta.cognitive_state.metacognitive_monitoring = True
        _sync_cognitive_load(agent, meta)
        traces = getattr(agent, "_meta_trace_by_intention", None)
        if traces is None:
            traces = {}
            agent._meta_trace_by_intention = traces
        traces[str(entry.get("id") or "")] = trace
        _trim(meta)
    except Exception as exc:
        get_logger().log(f"[META_COGNITION] intention error: {exc}")


def observe_action_outcome(
    agent, entry: Dict, outcome=None, error: Optional[Exception] = None
) -> None:
    meta = getattr(agent, "meta_cognition", None)
    if meta is None:
        return
    try:
        traces = getattr(agent, "_meta_trace_by_intention", {})
        trace = traces.pop(str(entry.get("id") or ""), None)
        if trace is None:
            trace = meta.observe_thought(
                "reflection", f"исход намерения: {entry.get('action', '')}"
            )
        if error is not None:
            trace.needs_revision = True
            meta.meta_metrics["self_corrections"] += 1
        else:
            trace.is_useful = bool(outcome and outcome.had_effect)
            delta = getattr(outcome, "delta", None)
            trace.produced_insight = bool(
                delta and getattr(delta, "knowledge_entries", 0) > 0
            )
        meta.cognitive_state.active_models = []
        _sync_cognitive_load(agent, meta)
        _trim(meta)
    except Exception as exc:
        get_logger().log(f"[META_COGNITION] outcome error: {exc}")


def _sync_cognitive_load(agent, meta) -> None:
    state = meta.assess_metacognitive_state()
    meta.cognitive_state.cognitive_load = state["cognitive_load"]
    # ContinuousTimeEngine читает это фактическое значение на следующем такте.
    agent._current_cognitive_load = state["cognitive_load"]


def _trim(meta) -> None:
    limit = int(getattr(SIM_CONFIG, "MAX_THOUGHT_TRACES", 200))
    keep = int(getattr(SIM_CONFIG, "THOUGHT_TRACES_KEEP", 100))
    if len(meta.thought_traces) > limit:
        meta.thought_traces = meta.thought_traces[-keep:]
    meta.insights = meta.insights[-100:]
    meta.knowledge_awareness.unknown_gaps = meta.knowledge_awareness.unknown_gaps[-100:]


def meta_cognition_checkpoint(agent) -> Dict:
    meta = getattr(agent, "meta_cognition", None)
    if meta is None:
        return {}
    return {
        "schema_version": 1,
        "cognitive_state": {
            "current_focus": meta.cognitive_state.current_focus,
            "confidence_level": meta.cognitive_state.confidence_level,
            "processing_depth": meta.cognitive_state.processing_depth,
            "cognitive_load": meta.cognitive_state.cognitive_load,
            "metacognitive_monitoring": meta.cognitive_state.metacognitive_monitoring,
        },
        "knowledge_awareness": {
            "understanding_level": dict(meta.knowledge_awareness.understanding_level),
            "unknown_gaps": deepcopy(meta.knowledge_awareness.unknown_gaps[-100:]),
        },
        "thought_traces": [
            {
                "thought_type": trace.thought_type,
                "content": trace.content[:500],
                "confidence": trace.confidence,
                "resulting_actions": list(trace.resulting_actions),
                "is_useful": trace.is_useful,
                "produced_insight": trace.produced_insight,
                "needs_revision": trace.needs_revision,
                "timestamp": trace.timestamp.isoformat(),
            }
            for trace in meta.thought_traces[-int(SIM_CONFIG.MAX_THOUGHT_TRACES) :]
        ],
        "insights": deepcopy(meta.insights[-100:]),
        "meta_metrics": dict(meta.meta_metrics),
    }


def validate_meta_cognition_checkpoint(state: Dict) -> None:
    if not isinstance(state, dict):
        raise ValueError("meta_cognition: expected dictionary")
    if state.get("schema_version") != 1:
        raise ValueError("meta_cognition.schema_version: unsupported version")
    cognitive = state.get("cognitive_state")
    knowledge = state.get("knowledge_awareness")
    traces = state.get("thought_traces")
    if not isinstance(cognitive, dict) or not isinstance(knowledge, dict):
        raise ValueError("meta_cognition: missing state sections")
    if not isinstance(traces, list) or not isinstance(state.get("insights"), list):
        raise ValueError("meta_cognition: invalid history sections")
    for field in ("confidence_level", "cognitive_load"):
        value = cognitive.get(field)
        if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
            raise ValueError(f"meta_cognition.cognitive_state.{field}: out of range")
    if not isinstance(cognitive.get("processing_depth"), int):
        raise ValueError(
            "meta_cognition.cognitive_state.processing_depth: expected int"
        )
    if not isinstance(knowledge.get("understanding_level"), dict):
        raise ValueError("meta_cognition.knowledge_awareness: invalid understanding")
    for concept, value in knowledge["understanding_level"].items():
        if not isinstance(concept, str) or not isinstance(value, (int, float)):
            raise ValueError("meta_cognition.knowledge_awareness: invalid level")
    if not isinstance(knowledge.get("unknown_gaps"), list):
        raise ValueError(
            "meta_cognition.knowledge_awareness.unknown_gaps: expected list"
        )
    for trace in traces:
        if not isinstance(trace, dict):
            raise ValueError("meta_cognition.thought_traces: invalid trace")
        for field in ("thought_type", "content", "timestamp"):
            if not isinstance(trace.get(field), str):
                raise ValueError(f"meta_cognition.thought_traces.{field}: expected str")
        try:
            datetime.fromisoformat(trace["timestamp"])
        except ValueError as exc:
            raise ValueError(
                "meta_cognition.thought_traces.timestamp: invalid"
            ) from exc
        if not isinstance(trace.get("resulting_actions"), list):
            raise ValueError(
                "meta_cognition.thought_traces.resulting_actions: expected list"
            )


def restore_meta_cognition(agent, state: Optional[Dict]) -> None:
    if not state:
        agent.meta_cognition = MetaCognitiveSystem(agent.name)
        agent._current_cognitive_load = 0.0
        agent._meta_trace_by_intention = {}
        return
    validate_meta_cognition_checkpoint(state)
    meta = MetaCognitiveSystem(agent.name)
    cognitive = state["cognitive_state"]
    for field in (
        "current_focus",
        "confidence_level",
        "processing_depth",
        "cognitive_load",
        "metacognitive_monitoring",
    ):
        setattr(meta.cognitive_state, field, cognitive[field])
    knowledge = state["knowledge_awareness"]
    for concept, level in knowledge["understanding_level"].items():
        meta.knowledge_awareness.mark_known(concept, level)
    meta.knowledge_awareness.unknown_gaps = deepcopy(knowledge["unknown_gaps"])
    for raw in state["thought_traces"]:
        trace = ThoughtTrace(raw["thought_type"], raw["content"])
        trace.confidence = raw["confidence"]
        trace.resulting_actions = list(raw["resulting_actions"])
        trace.is_useful = raw["is_useful"]
        trace.produced_insight = raw["produced_insight"]
        trace.needs_revision = raw["needs_revision"]
        trace.timestamp = datetime.fromisoformat(raw["timestamp"])
        meta.thought_traces.append(trace)
    meta.insights = deepcopy(state["insights"])
    meta.meta_metrics.update(state.get("meta_metrics", {}))
    agent.meta_cognition = meta
    agent._current_cognitive_load = meta.cognitive_state.cognitive_load
    agent._meta_trace_by_intention = {}
