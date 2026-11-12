"""Проводка уже созданных систем времени, метаобучения и социальной модели.

Мост только передаёт реальные события основного контура. Он не выбирает
действия, не создаёт цели и не разрешает MetaLearner менять параметры жизни.
"""

from typing import Dict, Optional

from src.core.buffered_logger import get_logger


def tick_continuous_time(agent, cycle: int) -> Optional[Dict]:
    """Прожить один логический такт и оставить наблюдаемое событие времени."""
    engine = getattr(agent, "continuous_time", None)
    if engine is None:
        return None
    try:
        report = engine.step(dt=1.0)
        engine.emit_event("tick", {"cycle": int(cycle)})
        return {
            "objective_time": engine.total_objective_time,
            "subjective_time": engine.total_subjective_time,
            "time_dilation": report["time_dilation"],
            "processed_events": report["processed_events"],
            "retention_events": len(engine.retention.events),
        }
    except Exception as exc:
        get_logger().log(f"[CONTINUOUS_TIME] tick error: {exc}")
        return {"error": str(exc)}


def step_meta_learning(agent) -> Optional[Dict]:
    """Накопить fitness каждого цикла без автономной мутации конфигурации."""
    learner = getattr(agent, "meta_learner", None)
    if learner is None:
        return None
    try:
        fitness = learner._compute_fitness()
        learner.step(fitness_signal=fitness, adapt=False)
        return {
            "mode": "shadow",
            "cycle_counter": learner.cycle_counter,
            "current_fitness": fitness,
            "best_fitness": (
                learner.best_fitness if learner.best_fitness != float("-inf") else None
            ),
        }
    except Exception as exc:
        get_logger().log(f"[META_LEARNING] tick error: {exc}")
        return {"error": str(exc)}


def observe_user_message(
    agent, text: str, act, cycle: int, reaction_to_us: str = ""
) -> Optional[Dict]:
    """Записать один фактический вход пользователя в SocialCell и время."""
    observation = {
        "timestamp": int(cycle),
        "action": str(getattr(act, "kind", "message") or "message"),
        "text": str(text or "")[:500],
    }
    if reaction_to_us:
        observation["reaction_to_us"] = reaction_to_us
    try:
        social = getattr(agent, "social_cell", None)
        if social is not None:
            social.observe_interaction("user", observation)
        engine = getattr(agent, "continuous_time", None)
        if engine is not None:
            engine.emit_event("social", dict(observation))
        from src.cognition.integrated_experience import observe_integrated_user_message

        observe_integrated_user_message(agent, text, int(cycle))
        return observation
    except Exception as exc:
        get_logger().log(f"[SOCIAL_CELL] observation error: {exc}")
        return None


def record_action_intention(agent, selection: Dict, entry: Dict) -> None:
    """Связать выбранное действие и его прогноз с retention/protension."""
    engine = getattr(agent, "continuous_time", None)
    if engine is None:
        return
    try:
        action = str(selection.get("action") or "")
        intention_id = str(entry.get("id") or "")
        simulation = selection.get("simulation") or {}
        engine.intend(
            {
                "intention_id": intention_id,
                "action": action,
                "expected_outcome": simulation.get("predicted_outcome"),
                "priority": float(selection.get("strength", 0.5) or 0.5),
            }
        )
        prediction_id = simulation.get("prediction_id")
        if prediction_id and simulation.get("status") == "predicted":
            engine.predict(
                {
                    "prediction_id": prediction_id,
                    "action": simulation.get("action", action),
                    "target": simulation.get("target", ""),
                    "expected_effect_probability": simulation.get(
                        "predicted_effect_probability"
                    ),
                    "confidence": simulation.get("confidence", 0.0),
                    "source": "internal_simulator",
                }
            )
        engine.emit_event(
            "action",
            {
                "intention_id": intention_id,
                "action": action,
                "prediction_id": prediction_id,
            },
            causality=[prediction_id] if prediction_id else [],
        )
    except Exception as exc:
        get_logger().log(f"[CONTINUOUS_TIME] intention error: {exc}")


def record_action_outcome(
    agent, entry: Dict, outcome=None, error: Optional[Exception] = None
) -> None:
    """Завершить protension только фактическим исходом этого намерения."""
    engine = getattr(agent, "continuous_time", None)
    if engine is None:
        return
    try:
        intention_id = str(entry.get("id") or "")
        engine.resolve_intention(intention_id)
        simulation = entry.get("simulation") or {}
        prediction_id = simulation.get("prediction_id")
        if prediction_id:
            engine.resolve_prediction(str(prediction_id))
        payload = {
            "intention_id": intention_id,
            "action": entry.get("action"),
            "prediction_id": prediction_id,
        }
        if error is not None:
            payload["status"] = "execution_error"
            payload["error"] = str(error)[:300]
        else:
            payload["status"] = "observed"
            payload["had_effect"] = bool(outcome and outcome.had_effect)
            payload["reason"] = str(getattr(outcome, "reason", "") or "")
        engine.emit_event(
            "observation", payload, causality=[intention_id] if intention_id else []
        )
    except Exception as exc:
        get_logger().log(f"[CONTINUOUS_TIME] outcome error: {exc}")
