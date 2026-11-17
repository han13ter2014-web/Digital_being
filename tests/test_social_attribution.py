"""Этап 2: персональная атрибуция отношений, контекста и обучения."""

from copy import deepcopy

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.human_affect import (
    attachment_testimony_weight,
    extract_static_human_affect,
)
from src.core.life_systems_bridge import observe_user_message


def _agent(name):
    return DigitalBeing(name=name)


def _new_guest(agent, name, cycle=1):
    profile_id = agent.social_registry.create_local_person(name, cycle=cycle)
    assert agent.social_attribution.sync_active_profile() is True
    return profile_id


def _switch(agent, profile_id, cycle=1):
    agent.social_registry.switch_to(profile_id, cycle=cycle)
    assert agent.social_attribution.sync_active_profile() is True


def _teach(agent, marker, preference, cycle=1):
    agent.user_model.observe("Я люблю чай и могу молчать", cycle=cycle)
    agent.dialogue_learning.learned[marker] = {"act": "social", "cycle": cycle}
    memory = agent.dialogue_learning.strategy_memory
    memory.set_preference("unknown", preference, cycle)
    memory.register_response(f"response:{marker}", preference, "unknown", cycle)
    memory.apply_feedback(f"response:{marker}", "support", cycle)


def test_owner_personal_state_does_not_leak_to_guest():
    agent = _agent("AttributionOwner")
    owner_id = agent.social_registry.owner_profile_id
    _teach(agent, "владелец говорит", "unknown_listen")
    agent.attachment.record_interaction("user", True)
    agent.user_interaction.ask_user("Вопрос владельцу?", cycle=1)
    agent.user_interaction.receive_user_message("Личное владельца", cycle=1)
    agent.user_interaction.record_dialogue_act(
        "social",
        cycle=1,
        user_text="Личное владельца",
        agent_text="Ответ владельцу",
    )
    agent.user_interaction.set_human_affect(
        extract_static_human_affect("Мне грустно", cycle=1)
    )
    owner_weight = attachment_testimony_weight(agent.attachment)

    _new_guest(agent, "Миша", cycle=2)

    assert agent.user_model.to_dict()["traits"] == {}
    assert agent.user_model.to_dict()["promises"] == {}
    assert agent.dialogue_learning.learned == {}
    assert agent.dialogue_learning.strategy_memory.outcomes == {}
    assert agent.dialogue_learning.strategy_memory.preference_for("unknown") is None
    assert agent.attachment.trust_factor("user") == 0.5
    assert agent.attachment.get_or_create("user").intimacy == 0.0
    assert attachment_testimony_weight(agent.attachment) < owner_weight
    assert agent.user_interaction.pending_questions == []
    assert agent.user_interaction.question_history == []
    assert agent.user_interaction.message_history == []
    assert agent.user_interaction.dialogue_act_ring.snapshot() == []
    assert agent.user_interaction.last_human_affect is None
    assert agent.user_interaction.get_last_user_message_cycle() is None
    assert set(agent.attachment._attachments) == {
        "user",
        f"profile:{agent.social_registry.current_profile_id}",
    }
    assert agent.social_attribution.states[owner_id]["user_interaction"][
        "dialogue_acts"
    ]


def test_guest_learning_does_not_change_owner_and_return_restores_it():
    agent = _agent("AttributionReturn")
    owner_id = agent.social_registry.owner_profile_id
    _teach(agent, "маркер владельца", "unknown_listen")
    agent.social_attribution.capture_active()
    owner_before = deepcopy(agent.social_attribution.states[owner_id])
    guest_id = _new_guest(agent, "Миша", cycle=2)

    _teach(agent, "маркер гостя", "learning_question", cycle=2)
    agent.attachment.record_interaction("user", False)
    _switch(agent, owner_id, cycle=3)

    assert agent.social_attribution.states[guest_id]["dialogue_learning"]["learned"]
    assert agent.user_model.traits["я люблю"] == "я люблю чай и могу молчать"
    assert set(agent.dialogue_learning.learned) == {"маркер владельца"}
    assert (
        agent.dialogue_learning.strategy_memory.preference_for("unknown")["strategy"]
        == "unknown_listen"
    )
    assert agent.attachment._active_user_key == "user"
    assert agent.attachment.get_or_create("user").interactions == 0
    current = agent.social_attribution.states[owner_id]
    assert current["dialogue_learning"] == owner_before["dialogue_learning"]


def test_two_guests_keep_contradictory_preferences_and_feedback():
    agent = _agent("AttributionGuests")
    first = _new_guest(agent, "Миша")
    _teach(agent, "первый гость", "unknown_listen")
    second = _new_guest(agent, "Аня", cycle=2)
    _teach(agent, "второй гость", "learning_question", cycle=2)

    _switch(agent, first, cycle=3)
    assert (
        agent.dialogue_learning.strategy_memory.preference_for("unknown")["strategy"]
        == "unknown_listen"
    )
    assert set(agent.dialogue_learning.learned) == {"первый гость"}
    _switch(agent, second, cycle=4)
    assert (
        agent.dialogue_learning.strategy_memory.preference_for("unknown")["strategy"]
        == "learning_question"
    )
    assert set(agent.dialogue_learning.learned) == {"второй гость"}
    assert agent.dialogue_learning.strategy_memory.feedback_target is None


def test_switch_preserves_shared_quiet_hours_bus_and_empty_pending():
    agent = _agent("AttributionInfrastructure")
    bus = object()
    agent.user_interaction.attach_bus(bus)
    agent.user_interaction.add_quiet_app("OwnerOnlyEditor")
    agent.user_interaction.ask_user("Вопрос владельцу?", cycle=1)
    _new_guest(agent, "Миша", cycle=2)

    assert agent.user_interaction.pending_questions == []
    assert agent.user_interaction._bus is bus
    assert agent.user_interaction.is_quiet_app("OwnerOnlyEditor") is True


def test_social_cell_observations_are_scoped_by_profile():
    agent = _agent("AttributionSocialCell")
    observe_user_message(agent, "Привет", type("Act", (), {"kind": "social"})(), 1)
    guest = _new_guest(agent, "Миша", cycle=2)
    observe_user_message(agent, "Привет", type("Act", (), {"kind": "social"})(), 2)

    assert set(agent.social_cell.agent_models) == {"user", f"profile:{guest}"}
    assert len(agent.social_cell.agent_models["user"].interaction_history) == 1
    assert (
        len(agent.social_cell.agent_models[f"profile:{guest}"].interaction_history) == 1
    )


def test_restart_restores_guest_and_both_private_histories():
    source = _agent("AttributionRestart")
    owner = source.social_registry.owner_profile_id
    source.user_interaction.receive_user_message("Входящее владельца", cycle=1)
    source.user_interaction.ask_user("Вопрос владельцу?", cycle=1)
    _teach(source, "владелец", "unknown_listen")
    guest = _new_guest(source, "Миша", cycle=2)
    source.user_interaction.receive_user_message("Входящее гостя", cycle=2)
    source.user_interaction.ask_user("Вопрос гостю?", cycle=2)
    source.user_interaction.record_dialogue_act(
        "social", cycle=2, user_text="Входящее гостя", agent_text="Ответ гостю"
    )
    source.user_interaction.set_human_affect(
        extract_static_human_affect("Мне грустно", cycle=2)
    )
    _teach(source, "гость", "learning_question", cycle=2)
    state = build_state_from_agent(source)

    restored = _agent("AttributionRestarted")
    apply_state_to_agent(restored, deepcopy(state))

    assert restored.social_registry.current_profile_id == guest
    assert restored.social_attribution.active_profile_id == guest
    assert set(restored.dialogue_learning.learned) == {"гость"}
    assert (
        restored.user_interaction.get_pending_question()["question"] == "Вопрос гостю?"
    )
    assert (
        restored.user_interaction.dialogue_act_ring.snapshot()[0]["user_text"]
        == "Входящее гостя"
    )
    assert restored.user_interaction.last_human_affect["components"] == {"sadness": 0.7}
    assert [m["content"] for m in restored.user_interaction.message_history] == [
        "Входящее гостя"
    ]
    _switch(restored, owner, cycle=3)
    assert set(restored.dialogue_learning.learned) == {"владелец"}
    assert (
        restored.user_interaction.get_pending_question()["question"]
        == "Вопрос владельцу?"
    )
    assert restored.user_interaction.last_human_affect is None
    assert [m["content"] for m in restored.user_interaction.message_history] == [
        "Входящее владельца"
    ]


def test_legacy_checkpoint_assigns_old_single_user_state_to_owner():
    source = _agent("AttributionLegacy")
    source.social_registry.complete_introduction("Глеб")
    source.social_registry.create_local_person("Миша")
    source.social_attribution.sync_active_profile()
    _teach(source, "старая история", "unknown_listen")
    state = build_state_from_agent(source)
    state.pop("social_attribution")

    restored = _agent("AttributionLegacyRestored")
    apply_state_to_agent(restored, state)

    owner = restored.social_registry.owner_profile_id
    assert restored.social_registry.current_profile_id == owner
    assert set(restored.dialogue_learning.learned) == {"старая история"}
    assert set(restored.social_attribution.states) == {owner}


def test_owner_name_does_not_reactivate_owner_or_restore_private_state():
    from src.core.social_registry import process_introduction

    agent = _agent("AttributionNoNameAuth")
    owner = agent.social_registry.owner_profile_id
    agent.social_registry.complete_introduction("Глеб")
    _teach(agent, "личное владельца", "unknown_listen")
    guest = _new_guest(agent, "Миша", cycle=2)

    result = process_introduction(agent.social_registry, "Я Глеб", cycle=3)
    agent.social_attribution.sync_active_profile()

    assert result is not None
    assert agent.social_registry.current_profile_id not in {owner, guest}
    assert agent.dialogue_learning.learned == {}
    assert agent.dialogue_learning.strategy_memory.preference_for("unknown") is None
    assert agent.attachment.trust_factor("user") == 0.5


def test_corrupted_profile_state_is_rejected_before_mutation():
    agent = _agent("AttributionCorruption")
    state = build_state_from_agent(agent)
    owner = agent.social_registry.owner_profile_id
    state["energy"] = 1.0
    state["social_attribution"]["states"][owner]["dialogue_learning"]["learned"] = {
        "bad": {"act": "answer", "cycle": 1}
    }
    before = build_state_from_agent(agent)

    with pytest.raises(ValueError, match=r"social_attribution\.states\..*\.act"):
        apply_state_to_agent(agent, state)

    assert agent.energy == before["energy"]
    assert agent.user_model.to_dict() == before["user_model"]
    assert agent.dialogue_learning.to_dict() == before["dialogue_learning"]
    assert agent.social_attribution.to_dict() == before["social_attribution"]
