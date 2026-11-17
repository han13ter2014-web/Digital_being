"""Проводка уже созданных систем времени, метаобучения и социальной модели.

Мост передаёт реальные события основного контура и метрики ресурсов. Он не
выбирает действия и не создаёт цели; MetaLearner меняет только ограниченный
ресурсный масштаб темпа, не мутируя случайно все подсистемы.
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


def step_meta_learning(agent, resource_status: Optional[Dict] = None) -> Optional[Dict]:
    """Накопить fitness и адаптировать темп к реальным ресурсам хоста."""
    learner = getattr(agent, "meta_learner", None)
    if learner is None:
        return None
    try:
        if resource_status is None:
            from src.core.watchdog import get_watchdog

            resource_status = get_watchdog().get_resource_status()
        fitness = learner._compute_fitness()
        learner.step(
            fitness_signal=fitness, adapt=True, resource_status=resource_status
        )
        return {
            "mode": "resource_adaptive",
            "cycle_counter": learner.cycle_counter,
            "current_fitness": fitness,
            "best_fitness": (
                learner.best_fitness if learner.best_fitness != float("-inf") else None
            ),
            "cycle_interval_scale": learner.hyperparams["cycle_interval_scale"].value,
            "resource_status": dict(learner.last_resource_status),
        }
    except Exception as exc:
        get_logger().log(f"[META_LEARNING] tick error: {exc}")
        return {"error": str(exc)}


def associate_expression(
    agent,
    expression: str,
    target_kind: str,
    target_id: str,
    *,
    cycle: int,
    scope: str = "personal",
    source: str = "explicit",
    confirmed=None,
    language_id=None,
) -> Dict:
    """Создать связь только с реальной целью и отдельным provenance."""
    lexicon = getattr(agent, "associative_lexicon", None)
    if lexicon is None:
        raise ValueError("associative_lexicon: subsystem is not attached")
    registry = getattr(agent, "social_registry", None)
    profile_id = str(getattr(registry, "current_profile_id", "") or "")

    def target_exists(value: str) -> bool:
        if target_kind == "concept":
            models = getattr(agent, "mental_models", None)
            return value in getattr(models, "concepts", {})
        if target_kind == "episode":
            memory = getattr(agent, "long_term_memory", None)
            checker = getattr(memory, "has_episode", None)
            return callable(checker) and checker(value)
        return False

    if language_id is None:
        attribution = getattr(agent, "social_attribution", None)
        context = (
            attribution.current_language_context() if attribution is not None else None
        )
        language_id = context.dialogue_language if context is not None else "ru"
    return lexicon.associate(
        expression,
        target_kind,
        target_id,
        cycle=int(cycle),
        scope=scope,
        profile_id=profile_id,
        source=source,
        confirmed=confirmed,
        target_exists=target_exists,
        language_id=language_id,
    )


def observe_user_message(
    agent, text: str, act, cycle: int, reaction_to_us: str = ""
) -> Optional[Dict]:
    """Записать один фактический вход пользователя в наблюдатели жизни."""
    observation = {
        "timestamp": int(cycle),
        "action": str(getattr(act, "kind", "message") or "message"),
        "text": str(text or "")[:500],
    }
    if reaction_to_us:
        observation["reaction_to_us"] = reaction_to_us
    try:
        social = getattr(agent, "social_cell", None)
        registry = getattr(agent, "social_registry", None)
        current = str(getattr(registry, "current_profile_id", "") or "")
        if social is not None:
            social_key = "user"
            if registry is not None and current != registry.owner_profile_id:
                social_key = f"profile:{current}"
            social.observe_interaction(social_key, observation)
        engine = getattr(agent, "continuous_time", None)
        if engine is not None:
            engine.emit_event("social", dict(observation))
        from src.cognition.integrated_experience import observe_integrated_user_message

        observe_integrated_user_message(agent, text, int(cycle))

        attribution = getattr(agent, "social_attribution", None)
        language_context = (
            attribution.current_language_context() if attribution is not None else None
        )
        language_id = (
            language_context.dialogue_language if language_context is not None else "ru"
        )
        unambiguous_language = language_context is None or (
            language_context.input_language == language_context.dialogue_language
        )
        lexicon = getattr(agent, "associative_lexicon", None)
        if lexicon is not None and current and unambiguous_language:
            source = "observed_act"
            confirmed = False
            learning = getattr(agent, "dialogue_learning", None)
            marker = str(getattr(act, "matched_marker", "") or "")
            taught = getattr(learning, "learned", {}).get(marker, {})
            if taught.get("act") == getattr(act, "kind", None):
                source = "user_taught"
                confirmed = True
            lexicon.observe_act(
                text,
                getattr(act, "kind", ""),
                cycle=int(cycle),
                profile_id=current,
                source=source,
                confirmed=confirmed,
                language_id=language_id,
            )
        experience = getattr(agent, "response_experience", None)
        if (
            experience is not None
            and current
            and unambiguous_language
            and getattr(act, "kind", "") == "social"
        ):
            from src.core.dialogue_acts import social_reply_kind

            if language_id == "en":
                normalized = " ".join(str(text).lower().split()).strip(" .!?…")
                if normalized in {"hello", "hi", "good morning", "good evening"}:
                    imitation_context = "greeting"
                elif normalized == "how are you":
                    imitation_context = "state"
                else:
                    imitation_context = "other"
            else:
                imitation_context = social_reply_kind(text)
            # Наблюдение не даёт права сразу повторить оборот: уровень и
            # возможность использования определяет SpeechImitation.
            experience.imitation.observe(
                text,
                context=imitation_context,
                profile_id=current,
                cycle=int(cycle),
                language_id=language_id,
            )
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
