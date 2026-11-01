"""Side-effect-free preflight for checkpoint data consumed by the serializer."""
from __future__ import annotations

import math

from src.core.checkpoint_migrations import SCHEMA_VERSION


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _dict(value, path):
    if not isinstance(value, dict):
        _fail(path, "expected a dictionary")
    return value


def _list(value, path):
    if not isinstance(value, list):
        _fail(path, "expected a list")
    return value


def _number(value, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "expected a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        _fail(path, "expected a finite number")


def _integer(value, path, *, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "expected an integer")
    if nonnegative and value < 0:
        _fail(path, "expected a nonnegative integer")


def _convertible_int(value, path):
    if isinstance(value, bool):
        _fail(path, "expected an int-convertible value")
    try:
        int(value)
    except (TypeError, ValueError, OverflowError):
        _fail(path, "expected an int-convertible value")


def _hashables(value, path):
    for index, item in enumerate(_list(value, path)):
        try:
            hash(item)
        except TypeError:
            _fail(f"{path}[{index}]", "expected a hashable value")


def _numbers(data, fields, path):
    for field in fields:
        if field in data:
            _number(data[field], f"{path}.{field}")


def _numeric_mapping(value, path):
    for key, item in _dict(value, path).items():
        _number(item, f"{path}.{key}")


def _node(data, path, *, name=None):
    from src.cognition.mental_models import ConceptNode

    _dict(data, path)
    if "connections" in data:
        _numeric_mapping(data["connections"], f"{path}.connections")
    _numbers(data, ("confidence",), path)
    if data.get("legacy_confidence") is not None:
        _number(data["legacy_confidence"], f"{path}.legacy_confidence")
    for field in ("contexts", "usage_examples", "tags"):
        if field in data:
            _hashables(data[field], f"{path}.{field}")
    if "schema_version" in data:
        _integer(data["schema_version"], f"{path}.schema_version", nonnegative=True)
    for index, experience in enumerate(_list(data.get("experiences", []), f"{path}.experiences")):
        exp_path = f"{path}.experiences[{index}]"
        _dict(experience, exp_path)
        _numbers(experience, ("valence", "evidence_strength", "evidence_direction"), exp_path)
        for field in ("context", "source", "evidence_kind"):
            if field in experience and not isinstance(experience[field], str):
                _fail(f"{exp_path}.{field}", "expected a string")
    for field in ("created_at", "last_updated"):
        if data.get(field):
            from datetime import datetime
            try:
                datetime.fromisoformat(data[field])
            except (TypeError, ValueError):
                _fail(f"{path}.{field}", "expected an ISO datetime")
    try:
        ConceptNode.from_dict({**data, "name": name} if name is not None else data)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        _fail(path, f"invalid concept: {exc}")


def _mental_models(data):
    from src.cognition.empirical_claims import EmpiricalClaim

    path = "mental_models"
    _dict(data, path)
    if "concepts" not in data:
        _fail(f"{path}.concepts", "required dictionary is missing")
    for name, raw in _dict(data["concepts"], f"{path}.concepts").items():
        _node(raw, f"{path}.concepts.{name}", name=name)
    claims = data.get("claims")
    if claims is not None:
        for key, raw in _dict(claims, f"{path}.claims").items():
            claim_path = f"{path}.claims.{key}"
            _dict(raw, claim_path)
            if "evidence" not in raw:
                _fail(f"{claim_path}.evidence", "required dictionary is missing")
            _node(raw["evidence"], f"{claim_path}.evidence")
            try:
                EmpiricalClaim.from_dict(raw)
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                _fail(claim_path, f"invalid empirical claim: {exc}")
    if data.get("metadata") is not None:
        _dict(data["metadata"], f"{path}.metadata")
    if data.get("recent_associations") is not None:
        _list(data["recent_associations"], f"{path}.recent_associations")


def _social(data):
    from src.core.social_cell import ToMLevel

    def tom(value, path):
        _integer(value, path)
        try:
            ToMLevel(value)
        except ValueError:
            _fail(path, "unknown ToMLevel")

    path = "social_cell"
    if "current_tom_level" in data:
        tom(data["current_tom_level"], f"{path}.current_tom_level")
    for key, model in _dict(data.get("agent_models", {}), f"{path}.agent_models").items():
        model_path = f"{path}.agent_models.{key}"
        _dict(model, model_path)
        if "tom_level" in model:
            tom(model["tom_level"], f"{model_path}.tom_level")
        for field in ("believed_goals", "believed_beliefs", "believed_intentions", "believed_emotional_state", "believed_model_of_self"):
            if field in model:
                _numeric_mapping(model[field], f"{model_path}.{field}")
        _numbers(model, ("model_precision",), model_path)
        if "interaction_history" in model:
            for index, item in enumerate(_list(model["interaction_history"], f"{model_path}.interaction_history")):
                _dict(item, f"{model_path}.interaction_history[{index}]")
    if "self_model_as_seen_by_others" in data:
        for key, model in _dict(data["self_model_as_seen_by_others"], f"{path}.self_model_as_seen_by_others").items():
            _dict(model, f"{path}.self_model_as_seen_by_others.{key}")


def _motivation(data):
    path = "motivation"
    for section in ("needs", "drives"):
        for key, item in _dict(data.get(section, {}), f"{path}.{section}").items():
            item_path = f"{path}.{section}.{key}"
            _dict(item, item_path)
            _numbers(item, ("base_level", "current_level", "decay_rate", "threshold", "priority", "activation_threshold"), item_path)
            if "activation_count" in item:
                _integer(item["activation_count"], f"{item_path}.activation_count", nonnegative=True)
            for field in ("related_concepts", "related_actions", "goal_types"):
                if field in item:
                    _list(item[field], f"{item_path}.{field}")
            if "contributing_needs" in item:
                _numeric_mapping(item["contributing_needs"], f"{item_path}.contributing_needs")
    if "goal_history" in data:
        _list(data["goal_history"], f"{path}.goal_history")
    if "last_generated_cycle" in data:
        _integer(data["last_generated_cycle"], f"{path}.last_generated_cycle")


def validate_checkpoint_state(state) -> None:
    """Raise ``ValueError`` with a field path before any checkpoint is applied.

    Missing optional fields are legacy defaults, not corruption. Validation never
    modifies the input, constructs an agent, or applies saved hyperparameters.
    """
    _dict(state, "state")
    if "life_id" in state:
        from src.core.life_identity import validate_life_id

        validate_life_id(state["life_id"])
    if state.get("active_inference") is not None:
        from src.cognition.inference_continuity import validate_inference

        validate_inference(state["active_inference"])
    if "personal_state" in state:
        from src.core.personal_continuity import validate_personal_state

        validate_personal_state(state["personal_state"])
    if "schema_version" in state:
        _integer(state["schema_version"], "schema_version", nonnegative=True)
        if state["schema_version"] > SCHEMA_VERSION:
            _fail("schema_version", "unsupported future schema version")
    if "energy" in state:
        _number(state["energy"], "energy")
    for field in ("cycle_count", "intelligence", "completed_goals", "success_streak"):
        if field in state:
            _integer(state[field], field, nonnegative=True)
    for field in ("knowledge_base", "_known_definitions"):
        if field in state:
            _dict(state[field], field)
    if "_learned_facts" in state:
        _hashables(state["_learned_facts"], "_learned_facts")
    if "goals" in state:
        for index, goal in enumerate(_list(state["goals"], "goals")):
            path = f"goals[{index}]"
            _dict(goal, path)
            for field in ("id", "title"):
                if field not in goal:
                    _fail(f"{path}.{field}", "required field is missing")
            _convertible_int(goal["id"], f"{path}.id")
            if not isinstance(goal["title"], str):
                _fail(f"{path}.title", "expected a string")
            if "motivation_origin" in goal:
                _dict(goal["motivation_origin"], f"{path}.motivation_origin")
            if "activity" in goal:
                activity = _dict(goal["activity"], f"{path}.activity")
                expected = {"play": {"play_turn", "play_round"}, "create_draft": {"draft_revision"}}
                if activity.get("action") not in expected or activity.get("criterion") not in expected[activity["action"]]:
                    _fail(f"{path}.activity", "unsupported activity criterion")
                if "steps" in activity:
                    _integer(activity["steps"], f"{path}.activity.steps", nonnegative=True)
    active = state.get("active_goal")
    if active is not None:
        if not isinstance(active, str):
            _fail("active_goal", "expected a title string or null")
        if active and "goals" in state and not any(goal["title"] == active for goal in state["goals"]):
            _fail("active_goal", "title does not match any saved goal")
    for key, progress in _dict(state.get("_goal_progress", {}), "_goal_progress").items():
        path = f"_goal_progress.{key}"
        _convertible_int(key, path)
        if isinstance(progress, dict):
            for field in ("percentage", "last_update_cycle"):
                if field in progress:
                    _convertible_int(progress[field], f"{path}.{field}")
            matched = progress.get("matched_concepts", [])
            _hashables(matched if matched is not None else [], f"{path}.matched_concepts")
        else:
            _hashables(progress, path)
    if "creative_catalog" in state:
        from src.cognition.creative_catalog import validate_catalog

        validate_catalog(state["creative_catalog"])
    if state.get("creative_draft") is not None:
        from src.cognition.creative_draft import validate_draft

        validate_draft(state["creative_draft"])
    if state.get("local_play") is not None:
        from src.cognition.local_play import validate_game

        validate_game(state["local_play"])
    if "waiting_intentions" in state:
        from src.cognition.intention_waiting import validate_waits

        validate_waits(state["waiting_intentions"])
    if "method_preferences" in state:
        from src.cognition.method_preferences import validate

        validate(state["method_preferences"])
    if "intention_history" in state:
        from src.cognition.intention_history import validate_history

        validate_history(state["intention_history"])
    if "pending_user_messages" in state:
        pending = _list(state["pending_user_messages"], "pending_user_messages")
        if any(not isinstance(text, str) for text in pending):
            _fail("pending_user_messages", "expected a list of strings")
    if state.get("deferred_stimulus") is not None:
        deferred = _dict(state["deferred_stimulus"], "deferred_stimulus")
        if not isinstance(deferred.get("text"), str) or not isinstance(deferred.get("user_initiated"), bool):
            _fail("deferred_stimulus", "expected text and boolean user_initiated")
    if state.get("mental_models") is not None:
        _mental_models(state["mental_models"])
    for field in ("naming_dialogue_history", "exploration_history", "birth_values"):
        if field in state and state[field] is not None:
            _list(state[field], field)
    if state.get("naming_dialogue_phase") is not None and not isinstance(state["naming_dialogue_phase"], str):
        _fail("naming_dialogue_phase", "expected a string")
    if state.get("user_model") is not None:
        user_model = _dict(state["user_model"], "user_model")
        promises = _dict(user_model.get("promises", {}), "user_model.promises")
        for kind, entry in promises.items():
            entry_path = f"user_model.promises.{kind}"
            entry_dict = _dict(entry, entry_path)
            if not isinstance(entry_dict.get("text"), str):
                _fail(f"{entry_path}.text", "expected a string")
            if "cycle" in entry_dict:
                _integer(entry_dict["cycle"], f"{entry_path}.cycle", nonnegative=True)
        traits = _dict(user_model.get("traits", {}), "user_model.traits")
        for marker, text in traits.items():
            if not isinstance(text, str):
                _fail(f"user_model.traits.{marker}", "expected a string")
        if user_model.get("last_contact_cycle") is not None:
            _integer(
                user_model["last_contact_cycle"],
                "user_model.last_contact_cycle",
                nonnegative=True,
            )
    if state.get("user_explained_topics") is not None:
        explained = _dict(
            state["user_explained_topics"], "user_explained_topics"
        )
        for topic, cycle in explained.items():
            if not isinstance(topic, str):
                _fail("user_explained_topics", "expected string keys")
            _integer(cycle, f"user_explained_topics.{topic}", nonnegative=True)
    if state.get("shared_topics") is not None:
        shared = _dict(state["shared_topics"], "shared_topics")
        for topic, cycle in shared.items():
            if not isinstance(topic, str):
                _fail("shared_topics", "expected string keys")
            _integer(cycle, f"shared_topics.{topic}", nonnegative=True)
    if state.get("user_interaction") is not None:
        interaction = _dict(state["user_interaction"], "user_interaction")
        for index, entry in enumerate(
            _list(
                interaction.get("question_history", []),
                "user_interaction.question_history",
            )
        ):
            path = f"user_interaction.question_history[{index}]"
            _dict(entry, path)
            for field in ("question", "answer"):
                if not isinstance(entry.get(field), str):
                    _fail(f"{path}.{field}", "expected a string")
            if "cycle" in entry:
                _integer(entry["cycle"], f"{path}.cycle", nonnegative=True)
        for index, question in enumerate(
            _list(
                interaction.get("pending_questions", []),
                "user_interaction.pending_questions",
            )
        ):
            path = f"user_interaction.pending_questions[{index}]"
            _dict(question, path)
            if not isinstance(question.get("question"), str):
                _fail(f"{path}.question", "expected a string")
            if "id" in question:
                _convertible_int(question["id"], f"{path}.id")
            for field in ("cycle", "sub_question_index"):
                if field in question:
                    _integer(question[field], f"{path}.{field}", nonnegative=True)
            if "sub_answers" in question:
                _dict(question["sub_answers"], f"{path}.sub_answers")
        for field in ("last_question_cycle", "last_user_message_cycle"):
            if interaction.get(field) is not None:
                _integer(interaction[field], f"user_interaction.{field}")
    if state.get("open_questions") is not None:
        for index, question in enumerate(_list(state["open_questions"], "open_questions")):
            path = f"open_questions[{index}]"
            _dict(question, path)
            if "explorations" in question:
                for attempt_index, attempt in enumerate(_list(question["explorations"], f"{path}.explorations")):
                    attempt_path = f"{path}.explorations[{attempt_index}]"
                    _dict(attempt, attempt_path)
                    _integer(attempt.get("cycle"), f"{attempt_path}.cycle", nonnegative=True)
                    for field in ("thought", "strategy"):
                        if not isinstance(attempt.get(field), str):
                            _fail(f"{attempt_path}.{field}", "expected a string")
            for field in ("started_at", "last_explored_at", "explorations_count", "max_explorations"):
                if field in question:
                    _integer(question[field], f"{path}.{field}", nonnegative=True)
    numeric_sections = {
        "interoception": ("glucose", "atp", "mitochondrial_health", "fatigue", "action_cost_multiplier", "cognitive_throughput", "exploration_drive"),
        "continuous_time": ("total_objective_time", "total_subjective_time", "subjective_time_dilation"),
        "death_risk": ("cognitive_coherence", "memory_consistency", "value_stability", "metabolic_viability", "social_coherence", "corruption_accumulator"),
        "consolidation": ("count", "sleep_units"),
    }
    for section, fields in numeric_sections.items():
        if section in state and not (section == "consolidation" and state[section] is None):
            _numbers(_dict(state[section], section), fields, section)
    if "last_checkpoint_step" in state.get("death_risk", {}):
        _integer(state["death_risk"]["last_checkpoint_step"], "death_risk.last_checkpoint_step", nonnegative=True)
    for field in ("birth_concepts", "birth_defined", "last_experiment_cycle"):
        if state.get(field) is not None:
            _integer(state[field], field, nonnegative=True)
    if state.get("loop_closure") is not None:
        loop = _dict(state["loop_closure"], "loop_closure")
        for field in ("no_effect_streak", "effect_count", "denied_streak"):
            if field in loop:
                _numeric_mapping(loop[field], f"loop_closure.{field}")
        _numbers(loop, ("total_actions", "total_with_effect", "productive_total", "productive_effect_total"), "loop_closure")
    if "meta_learning" in state:
        meta = _dict(state["meta_learning"], "meta_learning")
        for field in ("current_config", "best_config"):
            if field in meta and not (field == "best_config" and meta[field] is None):
                _numeric_mapping(meta[field], f"meta_learning.{field}")
        if "population" in meta:
            for index, config in enumerate(_list(meta["population"], "meta_learning.population")):
                _numeric_mapping(config, f"meta_learning.population[{index}]")
        _numbers(meta, ("current_fitness",), "meta_learning")
        best = meta.get("best_fitness")
        if best is not None and not (isinstance(best, float) and best == float("-inf")):
            _number(best, "meta_learning.best_fitness")
        if "cycle_counter" in meta:
            _integer(meta["cycle_counter"], "meta_learning.cycle_counter", nonnegative=True)
    if "social_cell" in state:
        _social(_dict(state["social_cell"], "social_cell"))
    if "motivation" in state:
        _motivation(_dict(state["motivation"], "motivation"))
