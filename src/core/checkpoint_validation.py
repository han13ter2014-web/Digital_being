"""Side-effect-free preflight for checkpoint data consumed by the serializer."""

from __future__ import annotations

import math

from src.core.checkpoint_migrations import SCHEMA_VERSION
from src.core.emotional_state import EMOTIONS
from src.motivation.goal_memory import GOAL_OUTCOMES


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


def _convertible_float(value, path):
    if isinstance(value, bool):
        _fail(path, "expected a float-convertible value")
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(path, "expected a float-convertible value")
    return float(value)


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


def _affect(data, path, *, learned=False, metadata=False):
    """Проверить свидетельство, не присваивая ему статус факта."""
    from src.core.human_affect import (
        AFFECT_COMPONENTS,
        AFFECT_EVIDENCE_KINDS,
        AFFECT_PHRASE_MAX_LEN,
        normalize_affect_phrase,
    )

    data = _dict(data, path)
    components = _dict(data.get("components"), f"{path}.components")
    if not components:
        _fail(f"{path}.components", "expected at least one component")
    for name, value in components.items():
        if name not in AFFECT_COMPONENTS:
            _fail(f"{path}.components.{name}", "unknown affect component")
        _number(value, f"{path}.components.{name}")
        if not 0.0 <= value <= 1.0:
            _fail(f"{path}.components.{name}", "expected a value in [0, 1]")
    evidence = data.get("evidence")
    expected = {"user_taught"} if learned else AFFECT_EVIDENCE_KINDS
    if evidence not in expected:
        _fail(f"{path}.evidence", "unknown evidence kind")
    weight_field = "weight" if learned else "testimony_weight"
    weight = data.get(weight_field)
    _number(weight, f"{path}.{weight_field}")
    if not 0.0 < weight <= 1.0:
        _fail(f"{path}.{weight_field}", "expected a value in (0, 1]")
    _integer(data.get("cycle"), f"{path}.cycle", nonnegative=True)
    if metadata:
        if not isinstance(data.get("marker"), str):
            _fail(f"{path}.marker", "expected a string")
        if not isinstance(data.get("shared_marker"), bool):
            _fail(f"{path}.shared_marker", "expected a boolean")
    return normalize_affect_phrase, AFFECT_PHRASE_MAX_LEN


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
    for index, experience in enumerate(
        _list(data.get("experiences", []), f"{path}.experiences")
    ):
        exp_path = f"{path}.experiences[{index}]"
        _dict(experience, exp_path)
        _numbers(
            experience, ("valence", "evidence_strength", "evidence_direction"), exp_path
        )
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
    for key, model in _dict(
        data.get("agent_models", {}), f"{path}.agent_models"
    ).items():
        model_path = f"{path}.agent_models.{key}"
        _dict(model, model_path)
        if "tom_level" in model:
            tom(model["tom_level"], f"{model_path}.tom_level")
        for field in (
            "believed_goals",
            "believed_beliefs",
            "believed_intentions",
            "believed_emotional_state",
            "believed_model_of_self",
        ):
            if field in model:
                _numeric_mapping(model[field], f"{model_path}.{field}")
        _numbers(model, ("model_precision",), model_path)
        if "interaction_history" in model:
            for index, item in enumerate(
                _list(model["interaction_history"], f"{model_path}.interaction_history")
            ):
                _dict(item, f"{model_path}.interaction_history[{index}]")
    if "self_model_as_seen_by_others" in data:
        for key, model in _dict(
            data["self_model_as_seen_by_others"], f"{path}.self_model_as_seen_by_others"
        ).items():
            _dict(model, f"{path}.self_model_as_seen_by_others.{key}")


def _motivation(data, path="motivation"):
    for section in ("needs", "drives"):
        for key, item in _dict(data.get(section, {}), f"{path}.{section}").items():
            item_path = f"{path}.{section}.{key}"
            _dict(item, item_path)
            _numbers(
                item,
                (
                    "base_level",
                    "current_level",
                    "decay_rate",
                    "threshold",
                    "priority",
                    "activation_threshold",
                ),
                item_path,
            )
            if "activation_count" in item:
                _integer(
                    item["activation_count"],
                    f"{item_path}.activation_count",
                    nonnegative=True,
                )
            for field in ("related_concepts", "related_actions", "goal_types"):
                if field in item:
                    _list(item[field], f"{item_path}.{field}")
            if "contributing_needs" in item:
                _numeric_mapping(
                    item["contributing_needs"], f"{item_path}.contributing_needs"
                )
    if "goal_history" in data:
        _list(data["goal_history"], f"{path}.goal_history")
    if "goal_summary" in data:
        summary = _dict(data["goal_summary"], f"{path}.goal_summary")
        for outcome in GOAL_OUTCOMES:
            if outcome in summary:
                _integer(
                    summary[outcome],
                    f"{path}.goal_summary.{outcome}",
                    nonnegative=True,
                )
        for section in ("by_need", "by_drive"):
            if section not in summary:
                continue
            counts = _dict(summary[section], f"{path}.goal_summary.{section}")
            for name, item in counts.items():
                item_path = f"{path}.goal_summary.{section}.{name}"
                _dict(item, item_path)
                for outcome in GOAL_OUTCOMES:
                    if outcome in item:
                        _integer(
                            item[outcome],
                            f"{item_path}.{outcome}",
                            nonnegative=True,
                        )
    if "pending_goal_origins" in data:
        pending = _dict(data["pending_goal_origins"], f"{path}.pending_goal_origins")
        for goal_id, entry in pending.items():
            _dict(entry, f"{path}.pending_goal_origins.{goal_id}")
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
    for field, limit in (
        ("parent_seed", 128),
        ("parent_name", 128),
        ("parent_dream_time", 64),
    ):
        value = state.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            _fail(field, f"expected null or a string of at most {limit} characters")
    if "seed_generation" in state:
        _integer(state["seed_generation"], "seed_generation", nonnegative=True)
    if state.get("active_inference") is not None:
        from src.cognition.inference_continuity import validate_inference

        validate_inference(state["active_inference"])
    if state.get("internal_simulation") is not None:
        from src.cognition.internal_simulator import InternalSimulator

        InternalSimulator.validate_checkpoint_dict(state["internal_simulation"])
    if state.get("music_memory") is not None:
        from src.cognition.music_memory import validate_music_memory

        validate_music_memory(state["music_memory"])
    if state.get("meta_cognition"):
        # Пустая секция означает, что у legacy/fake-агента её ещё нет.
        from src.cognition.experience_observers import (
            validate_meta_cognition_checkpoint,
        )

        validate_meta_cognition_checkpoint(state["meta_cognition"])
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
    if "hunt_misses" in state:
        for topic, miss_cycle in _dict(state["hunt_misses"], "hunt_misses").items():
            path = f"hunt_misses.{topic}"
            if not isinstance(topic, str) or not topic:
                _fail("hunt_misses", "expected nonempty string topics")
            _integer(miss_cycle, path, nonnegative=True)
            if "cycle_count" in state and miss_cycle > state["cycle_count"]:
                _fail(path, "miss cycle exceeds cycle_count")
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
                # Белый список строится из рук производителя: новые виды
                # деятельности (draw, compose_music, ...) не должны молча
                # превращать свежий снимок жизни в нечитаемый.
                from src.cognition.activity_goals import CRITERIA

                expected = {
                    action: {criterion} for action, criterion in CRITERIA.items()
                }
                expected.setdefault("play", set()).add("play_turn")  # старые снимки
                if (
                    activity.get("action") not in expected
                    or activity.get("criterion") not in expected[activity["action"]]
                ):
                    _fail(f"{path}.activity", "unsupported activity criterion")
                if "steps" in activity:
                    _integer(
                        activity["steps"], f"{path}.activity.steps", nonnegative=True
                    )
    active = state.get("active_goal")
    if active is not None:
        if not isinstance(active, str):
            _fail("active_goal", "expected a title string or null")
        if (
            active
            and "goals" in state
            and not any(goal["title"] == active for goal in state["goals"])
        ):
            _fail("active_goal", "title does not match any saved goal")
    active_id = state.get("active_goal_id")
    if active_id is not None:
        _convertible_int(active_id, "active_goal_id")
        if "goals" in state and not any(
            int(goal["id"]) == int(active_id) for goal in state["goals"]
        ):
            _fail("active_goal_id", "id does not match any saved goal")
    for key, progress in _dict(
        state.get("_goal_progress", {}), "_goal_progress"
    ).items():
        path = f"_goal_progress.{key}"
        _convertible_int(key, path)
        if isinstance(progress, dict):
            for field in ("percentage", "last_update_cycle"):
                if field in progress:
                    _convertible_int(progress[field], f"{path}.{field}")
            matched = progress.get("matched_concepts", [])
            _hashables(
                matched if matched is not None else [], f"{path}.matched_concepts"
            )
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
        if not isinstance(deferred.get("text"), str) or not isinstance(
            deferred.get("user_initiated"), bool
        ):
            _fail("deferred_stimulus", "expected text and boolean user_initiated")
    if state.get("mental_models") is not None:
        _mental_models(state["mental_models"])
    for field in ("naming_dialogue_history", "exploration_history", "birth_values"):
        if field in state and state[field] is not None:
            _list(state[field], field)
    if state.get("naming_dialogue_phase") is not None and not isinstance(
        state["naming_dialogue_phase"], str
    ):
        _fail("naming_dialogue_phase", "expected a string")
    if state.get("social_registry") is not None:
        from src.core.social_registry import validate_social_registry

        validate_social_registry(state["social_registry"])
    if state.get("response_experience") is not None:
        from src.core.response_experience import validate_response_experience

        validate_response_experience(state["response_experience"])
        registry = state.get("social_registry")
        if isinstance(registry, dict):
            current = registry.get("current_profile_id")
            for response in state["response_experience"]["responses"]:
                if response["plan"]["state"]["profile_id"] != current:
                    _fail(
                        "response_experience.responses",
                        "response profile does not match current social profile",
                    )
            for expression in state["response_experience"]["imitation"]["expressions"]:
                if expression["profile_id"] != current:
                    _fail(
                        "response_experience.imitation.expressions",
                        "expression profile does not match current social profile",
                    )
    if state.get("language_concept_links") is not None:
        from src.core.language_concepts import validate_language_concept_links

        validate_language_concept_links(state["language_concept_links"])
    if state.get("language_tutor") is not None:
        from src.core.language_tutor import validate_language_tutor

        validate_language_tutor(state["language_tutor"])
    if state.get("english_language_tutor") is not None:
        from src.core.english_language_tutor import validate_english_language_tutor

        validate_english_language_tutor(state["english_language_tutor"])
    if state.get("external_contacts") is not None:
        from src.core.external_contacts import validate_external_contacts

        validate_external_contacts(
            state["external_contacts"], state.get("social_registry")
        )
    if state.get("social_channels") is not None:
        from src.core.social_channels import validate_social_channels

        validate_social_channels(state["social_channels"], state.get("social_registry"))
    if state.get("social_attribution") is not None:
        from src.core.social_attribution import validate_social_attribution

        validate_social_attribution(
            state["social_attribution"], state.get("social_registry")
        )
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
        explained = _dict(state["user_explained_topics"], "user_explained_topics")
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
    if state.get("dialogue_learning") is not None:
        learning = _dict(state["dialogue_learning"], "dialogue_learning")
        buffer = _dict(learning.get("buffer", {}), "dialogue_learning.buffer")
        for phrase, entry in buffer.items():
            entry_path = f"dialogue_learning.buffer.{phrase}"
            entry_dict = _dict(entry, entry_path)
            _convertible_int(entry_dict.get("count"), f"{entry_path}.count")
        learned = _dict(learning.get("learned", {}), "dialogue_learning.learned")
        for phrase, entry in learned.items():
            entry_path = f"dialogue_learning.learned.{phrase}"
            entry_dict = _dict(entry, entry_path)
            if entry_dict.get("act") not in (
                "social",
                "ask_about_self",
                "request",
            ):
                _fail(f"{entry_path}.act", "expected a learnable act")
        suppressed = _dict(
            learning.get("suppressed", {}), "dialogue_learning.suppressed"
        )
        for phrase, cycle in suppressed.items():
            _convertible_int(cycle, f"dialogue_learning.suppressed.{phrase}")
        learned_affect = _dict(
            learning.get("learned_affect", {}), "dialogue_learning.learned_affect"
        )
        if len(learned_affect) > 200:
            _fail("dialogue_learning.learned_affect", "too many entries")
        for phrase, entry in learned_affect.items():
            entry_path = f"dialogue_learning.learned_affect.{phrase}"
            normalize, max_len = _affect(entry, entry_path, learned=True)
            if not isinstance(phrase, str) or normalize(phrase) != phrase:
                _fail(entry_path, "expected a normalized string phrase")
            if not phrase or len(phrase) > max_len:
                _fail(entry_path, "phrase length out of range")
        suppressed_affect = _dict(
            learning.get("suppressed_affect", {}),
            "dialogue_learning.suppressed_affect",
        )
        for phrase, cycle in suppressed_affect.items():
            path = f"dialogue_learning.suppressed_affect.{phrase}"
            if not isinstance(phrase, str) or not phrase:
                _fail(path, "expected a nonempty string phrase")
            _integer(cycle, path, nonnegative=True)
        strategies_state = _dict(
            learning.get("dialogue_strategies", {}),
            "dialogue_learning.dialogue_strategies",
        )
        from src.core.dialogue_strategies import (
            RECENT_RESPONSE_IDS_MAX,
            RESPONSE_ID_MAX_LEN,
            STRATEGY_WHITELIST,
        )

        outcomes = _dict(
            strategies_state.get("outcomes", {}),
            "dialogue_learning.dialogue_strategies.outcomes",
        )
        for context, strategies in outcomes.items():
            context_path = f"dialogue_learning.dialogue_strategies.outcomes.{context}"
            if context not in STRATEGY_WHITELIST:
                _fail(context_path, "unknown strategy context")
            strategies = _dict(strategies, context_path)
            for strategy, raw in strategies.items():
                path = f"{context_path}.{strategy}"
                if strategy not in STRATEGY_WHITELIST[context]:
                    _fail(path, "unknown dialogue strategy")
                entry = _dict(raw, path)
                for field in ("support", "opposition"):
                    value = entry.get(field)
                    _number(value, f"{path}.{field}")
                    if value < 0.0:
                        _fail(f"{path}.{field}", "expected a nonnegative number")
                response_count = entry.get("response_count")
                _integer(response_count, f"{path}.response_count", nonnegative=True)
                _integer(
                    entry.get("last_cycle"), f"{path}.last_cycle", nonnegative=True
                )
                recent = _list(
                    entry.get("recent_response_ids"), f"{path}.recent_response_ids"
                )
                if len(recent) > RECENT_RESPONSE_IDS_MAX:
                    _fail(f"{path}.recent_response_ids", "too many response IDs")
                for index, response_id in enumerate(recent):
                    if (
                        not isinstance(response_id, str)
                        or not 0 < len(response_id.strip()) <= RESPONSE_ID_MAX_LEN
                    ):
                        _fail(
                            f"{path}.recent_response_ids[{index}]",
                            "invalid response ID",
                        )
                if len(set(recent)) != len(recent):
                    _fail(f"{path}.recent_response_ids", "duplicate response ID")
                if response_count < len(recent):
                    _fail(f"{path}.response_count", "inconsistent response count")
        preferences = _dict(
            strategies_state.get("preferences", {}),
            "dialogue_learning.dialogue_strategies.preferences",
        )
        for context, raw in preferences.items():
            path = f"dialogue_learning.dialogue_strategies.preferences.{context}"
            if context not in STRATEGY_WHITELIST:
                _fail(path, "unknown strategy context")
            entry = _dict(raw, path)
            if entry.get("strategy") not in STRATEGY_WHITELIST[context]:
                _fail(f"{path}.strategy", "unknown dialogue strategy")
            if entry.get("evidence") != "user_taught":
                _fail(f"{path}.evidence", "expected user_taught")
            _integer(entry.get("cycle"), f"{path}.cycle", nonnegative=True)
        target = strategies_state.get("feedback_target")
        if target is not None:
            path = "dialogue_learning.dialogue_strategies.feedback_target"
            target = _dict(target, path)
            response_id = target.get("response_id")
            if (
                not isinstance(response_id, str)
                or not 0 < len(response_id.strip()) <= RESPONSE_ID_MAX_LEN
            ):
                _fail(f"{path}.response_id", "invalid response ID")
            context = target.get("context_key")
            if context not in STRATEGY_WHITELIST:
                _fail(f"{path}.context_key", "unknown strategy context")
            if target.get("strategy_id") not in STRATEGY_WHITELIST[context]:
                _fail(f"{path}.strategy_id", "unknown dialogue strategy")
            _integer(target.get("cycle"), f"{path}.cycle", nonnegative=True)
        schema_version = learning.get("schema_version")
        if schema_version is not None and schema_version != 2:
            _fail("dialogue_learning.schema_version", "unsupported schema version")
        if schema_version == 2 and not {"active_language", "language_states"} <= set(
            learning
        ):
            _fail("dialogue_learning", "missing versioned language fields")
        active_language = learning.get("active_language", "ru")
        if active_language not in {"ru", "en", "zh"}:
            _fail("dialogue_learning.active_language", "unsupported language")
        language_states = _dict(
            learning.get("language_states", {}), "dialogue_learning.language_states"
        )
        for language_id, payload in language_states.items():
            path = f"dialogue_learning.language_states.{language_id}"
            if language_id not in {"ru", "en", "zh"} or language_id == active_language:
                _fail(path, "invalid or duplicate active language state")
            payload = _dict(payload, path)
            if payload.get("schema_version") not in {None, 2}:
                _fail(f"{path}.schema_version", "unsupported schema version")
            if payload.get("active_language", language_id) != language_id:
                _fail(f"{path}.active_language", "language state mismatch")
            if payload.get("language_states"):
                _fail(f"{path}.language_states", "nested language states are forbidden")
            flat = {
                key: value
                for key, value in payload.items()
                if key not in {"schema_version", "active_language", "language_states"}
            }
            try:
                validate_checkpoint_state(
                    {
                        "dialogue_learning": {
                            **flat,
                            "schema_version": 2,
                            "active_language": language_id,
                            "language_states": {},
                        }
                    }
                )
            except ValueError as error:
                raise ValueError(f"{path}.{error}") from error
    if state.get("emotional_state") is not None:
        emotions = _dict(state["emotional_state"], "emotional_state")
        levels = _dict(emotions.get("levels", {}), "emotional_state.levels")
        for name, level in levels.items():
            if name not in EMOTIONS:
                _fail(f"emotional_state.levels.{name}", "unknown emotion")
            value = _convertible_float(level, f"emotional_state.levels.{name}")
            if not 0.0 <= value <= 1.0:
                _fail(
                    f"emotional_state.levels.{name}",
                    "level out of [0, 1]",
                )
        for index, episode in enumerate(
            _list(emotions.get("episodes", []), "emotional_state.episodes")
        ):
            path = f"emotional_state.episodes[{index}]"
            episode_dict = _dict(episode, path)
            if episode_dict.get("emotion") not in EMOTIONS:
                _fail(f"{path}.emotion", "unknown emotion")
            _convertible_int(episode_dict.get("cycle", 0), f"{path}.cycle")
            intensity = _convertible_float(
                episode_dict.get("intensity", 0.0), f"{path}.intensity"
            )
            if not 0.0 <= intensity <= 1.0:
                _fail(f"{path}.intensity", "intensity out of [0, 1]")
    if state.get("associative_lexicon") is not None:
        from src.core.associative_lexicon import validate_associative_lexicon

        validate_associative_lexicon(
            state["associative_lexicon"], expected_scope="shared"
        )
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
            language_context = entry.get("language_context")
            if language_context is not None:
                from src.core.language_context import validate_language_context

                validate_language_context(language_context, f"{path}.language_context")
                registry = state.get("social_registry")
                if isinstance(registry, dict) and language_context[
                    "profile_id"
                ] != registry.get("current_profile_id"):
                    _fail(
                        f"{path}.language_context",
                        "profile does not match current profile",
                    )
        if interaction.get("last_human_affect") is not None:
            _affect(
                interaction["last_human_affect"], "user_interaction.last_human_affect"
            )
        for index, entry in enumerate(
            _list(
                interaction.get("dialogue_acts", []),
                "user_interaction.dialogue_acts",
            )
        ):
            path = f"user_interaction.dialogue_acts[{index}]"
            _dict(entry, path)
            for field in ("kind", "topic", "user_text", "agent_text"):
                if not isinstance(entry.get(field), str):
                    _fail(f"{path}.{field}", "expected a string")
            for entity_index, entity in enumerate(
                _list(entry.get("entities"), f"{path}.entities")
            ):
                if not isinstance(entity, str):
                    _fail(f"{path}.entities[{entity_index}]", "expected a string")
            _integer(entry.get("cycle"), f"{path}.cycle", nonnegative=True)
            if entry.get("affect") is not None:
                _affect(entry["affect"], f"{path}.affect", metadata=True)
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
            if "response_id" in question and (
                not isinstance(question["response_id"], str)
                or not question["response_id"].strip()
            ):
                _fail(f"{path}.response_id", "expected a non-empty string")
            language_context = question.get("language_context")
            if language_context is not None:
                from src.core.language_context import validate_language_context

                validate_language_context(language_context, f"{path}.language_context")
                registry = state.get("social_registry")
                if isinstance(registry, dict) and language_context[
                    "profile_id"
                ] != registry.get("current_profile_id"):
                    _fail(
                        f"{path}.language_context",
                        "profile does not match current profile",
                    )
            for field in ("cycle", "sub_question_index"):
                if field in question:
                    _integer(question[field], f"{path}.{field}", nonnegative=True)
            if "sub_answers" in question:
                _dict(question["sub_answers"], f"{path}.sub_answers")
        for index, entry in enumerate(
            _list(
                interaction.get("outgoing_messages", []),
                "user_interaction.outgoing_messages",
            )
        ):
            path = f"user_interaction.outgoing_messages[{index}]"
            _dict(entry, path)
            language_context = entry.get("language_context")
            if language_context is not None:
                from src.core.language_context import validate_language_context

                validate_language_context(language_context, f"{path}.language_context")
                registry = state.get("social_registry")
                if isinstance(registry, dict) and language_context[
                    "profile_id"
                ] != registry.get("current_profile_id"):
                    _fail(
                        f"{path}.language_context",
                        "profile does not match current profile",
                    )
        for field in ("last_question_cycle", "last_user_message_cycle"):
            if interaction.get(field) is not None:
                _integer(interaction[field], f"user_interaction.{field}")
    if state.get("open_questions") is not None:
        for index, question in enumerate(
            _list(state["open_questions"], "open_questions")
        ):
            path = f"open_questions[{index}]"
            _dict(question, path)
            if "explorations" in question:
                for attempt_index, attempt in enumerate(
                    _list(question["explorations"], f"{path}.explorations")
                ):
                    attempt_path = f"{path}.explorations[{attempt_index}]"
                    _dict(attempt, attempt_path)
                    _integer(
                        attempt.get("cycle"), f"{attempt_path}.cycle", nonnegative=True
                    )
                    for field in ("thought", "strategy"):
                        if not isinstance(attempt.get(field), str):
                            _fail(f"{attempt_path}.{field}", "expected a string")
            for field in (
                "started_at",
                "last_explored_at",
                "explorations_count",
                "max_explorations",
            ):
                if field in question:
                    _integer(question[field], f"{path}.{field}", nonnegative=True)
    numeric_sections = {
        "interoception": (
            "glucose",
            "atp",
            "mitochondrial_health",
            "fatigue",
            "action_cost_multiplier",
            "cognitive_throughput",
            "exploration_drive",
        ),
        "continuous_time": (
            "total_objective_time",
            "total_subjective_time",
            "subjective_time_dilation",
        ),
        "death_risk": (
            "cognitive_coherence",
            "memory_consistency",
            "value_stability",
            "metabolic_viability",
            "social_coherence",
            "corruption_accumulator",
        ),
        "consolidation": ("count", "sleep_units"),
    }
    for section, fields in numeric_sections.items():
        if section in state and not (
            section == "consolidation" and state[section] is None
        ):
            _numbers(_dict(state[section], section), fields, section)
    if "last_checkpoint_step" in state.get("death_risk", {}):
        _integer(
            state["death_risk"]["last_checkpoint_step"],
            "death_risk.last_checkpoint_step",
            nonnegative=True,
        )
    for field in ("birth_concepts", "birth_defined", "last_experiment_cycle"):
        if state.get(field) is not None:
            _integer(state[field], field, nonnegative=True)
    if state.get("loop_closure") is not None:
        loop = _dict(state["loop_closure"], "loop_closure")
        for field in ("no_effect_streak", "effect_count", "denied_streak"):
            if field in loop:
                _numeric_mapping(loop[field], f"loop_closure.{field}")
        _numbers(
            loop,
            (
                "total_actions",
                "total_with_effect",
                "productive_total",
                "productive_effect_total",
            ),
            "loop_closure",
        )
    if "meta_learning" in state:
        meta = _dict(state["meta_learning"], "meta_learning")
        for field in ("current_config", "best_config"):
            if field in meta and not (field == "best_config" and meta[field] is None):
                _numeric_mapping(meta[field], f"meta_learning.{field}")
        if "population" in meta:
            for index, config in enumerate(
                _list(meta["population"], "meta_learning.population")
            ):
                _numeric_mapping(config, f"meta_learning.population[{index}]")
        _numbers(meta, ("current_fitness",), "meta_learning")
        if "fitness_history" in meta:
            history = _list(meta["fitness_history"], "meta_learning.fitness_history")
            for index, value in enumerate(history):
                _number(value, f"meta_learning.fitness_history[{index}]")
        best = meta.get("best_fitness")
        if best is not None and not (isinstance(best, float) and best == float("-inf")):
            _number(best, "meta_learning.best_fitness")
        if "cycle_counter" in meta:
            _integer(
                meta["cycle_counter"], "meta_learning.cycle_counter", nonnegative=True
            )
        if "resource_recovery_cycles" in meta:
            _integer(
                meta["resource_recovery_cycles"],
                "meta_learning.resource_recovery_cycles",
            )
            if meta["resource_recovery_cycles"] <= 0:
                _fail(
                    "meta_learning.resource_recovery_cycles",
                    "expected a positive integer",
                )
        if "resource_low_pressure_cycles" in meta:
            _integer(
                meta["resource_low_pressure_cycles"],
                "meta_learning.resource_low_pressure_cycles",
                nonnegative=True,
            )
        if "resource_adaptation_history" in meta:
            events = _list(
                meta["resource_adaptation_history"],
                "meta_learning.resource_adaptation_history",
            )
            for index, event in enumerate(events):
                path = f"meta_learning.resource_adaptation_history[{index}]"
                event = _dict(event, path)
                if event.get("response") not in ("conserve", "recover"):
                    _fail(f"{path}.response", "unknown resource response")
                _integer(event.get("cycle"), f"{path}.cycle", nonnegative=True)
                _numbers(event, ("pressure", "previous_scale", "new_scale"), path)
        if "last_resource_status" in meta:
            resource = _dict(
                meta["last_resource_status"], "meta_learning.last_resource_status"
            )
            if "available" in resource and not isinstance(resource["available"], bool):
                _fail("meta_learning.last_resource_status.available", "expected a bool")
            _numbers(
                resource,
                (
                    "score",
                    "host_cpu_percent",
                    "host_memory_percent",
                    "process_cpu_percent",
                    "process_rss_mb",
                    "process_rss_ratio",
                    "cycle_duration_ms",
                ),
                "meta_learning.last_resource_status",
            )
    if "social_cell" in state:
        _social(_dict(state["social_cell"], "social_cell"))
    if "motivation" in state:
        _motivation(_dict(state["motivation"], "motivation"))
    if "internal_motivation" in state:
        _motivation(
            _dict(state["internal_motivation"], "internal_motivation"),
            path="internal_motivation",
        )
