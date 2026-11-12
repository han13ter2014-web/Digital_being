"""Подключённые наблюдатели получают факты, но не становятся вторым Core."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.cognition.agent_cooperation import MessageType
from src.cognition.creative_catalog import perform_creative
from src.cognition.integrated_experience import (
    observe_integrated_action,
    tick_integrated_experience,
)
from src.core.agent import DigitalBeing
from src.core.auxiliary_adapters import tick_auxiliary_adapters
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.dialogue_acts import classify_user_text
from src.core.effector_port import EffectorResult, EffectorStatus
from src.core.life_systems_bridge import observe_user_message


def _canonical_state(agent):
    return {
        "energy": agent.energy,
        "goals": deepcopy(agent.goals),
        "active_goal": deepcopy(agent.active_goal),
        "values": list(agent.value_evolution.current_values),
        "emotions": deepcopy(agent.emotional_state.levels),
        "meta_config": agent.meta_learner._get_current_config(),
    }


def test_real_action_outcome_updates_observers_without_mutating_core():
    agent = DigitalBeing(name="IntegratedAction")
    before = _canonical_state(agent)
    entry = {"action": "explore", "target": "память", "params": {}}
    outcome = SimpleNamespace(had_effect=True, reason="knowledge_changed")

    observe_integrated_action(agent, entry, outcome)

    assert _canonical_state(agent) == before
    memory = agent.personality.narrative.memories[-1]
    assert memory["action"] == "explore"
    assert memory["had_effect"] is True
    pattern = agent.thinking_patterns.patterns["analytical_thinking"]
    assert (pattern.usage_count, pattern.success_count, pattern.failure_count) == (
        1,
        1,
        0,
    )
    assert agent.hormonal_system.history[-1]["event"] == "learning"
    assert agent.emergence_engine.state_history[-1]["result"] == "effect"
    assert agent.metrics.get_stats("action_outcomes")["count"] == 1
    assert agent.metrics.get_stats("action_effects")["count"] == 1


def test_failed_action_is_recorded_once_as_failure():
    agent = DigitalBeing(name="IntegratedFailure")
    entry = {"action": "explore", "target": "память", "params": {}}

    observe_integrated_action(agent, entry, error=RuntimeError("нет наблюдения"))

    assert len(agent.personality.narrative.memories) == 1
    assert agent.personality.narrative.memories[0]["had_effect"] is False
    pattern = agent.thinking_patterns.patterns["analytical_thinking"]
    assert (pattern.usage_count, pattern.success_count, pattern.failure_count) == (
        1,
        0,
        1,
    )
    assert agent.hormonal_system.history[-1]["event"] == "failure"
    assert agent.metrics.get_stats("action_errors")["count"] == 1


def test_social_observation_and_cycle_tick_are_not_duplicated():
    agent = DigitalBeing(name="IntegratedSocial")

    observe_user_message(agent, "привет", classify_user_text("привет"), 3)

    assert len(agent.personality.narrative.memories) == 1
    assert agent.personality.narrative.memories[0]["type"] == "social"
    assert agent.metrics.get_stats("social_messages")["count"] == 1
    assert len(agent.hormonal_system.history) == 1
    first = tick_integrated_experience(agent, 3)
    cycle_time = agent.hormonal_system.cycle_time
    second = tick_integrated_experience(agent, 3)
    assert first != {"skipped": "duplicate_cycle"}
    assert second == {"skipped": "duplicate_cycle"}
    assert agent.hormonal_system.cycle_time == cycle_time
    assert agent.metrics.get_stats("energy")["count"] == 1


def test_integrated_experience_and_cooperation_survive_checkpoint():
    agent = DigitalBeing(name="IntegratedCheckpoint")
    observe_user_message(agent, "сохрани опыт", classify_user_text("сохрани опыт"), 2)
    observe_integrated_action(
        agent,
        {"action": "create_draft", "target": "тихая работа", "params": {}},
        SimpleNamespace(had_effect=True, reason="artifact_changed"),
    )
    agent.cooperation_hub.shared_knowledge_base["память"] = {
        agent.life_id: {"raw": "только карантин"}
    }
    state = build_state_from_agent(agent)

    reborn = DigitalBeing(name="IntegratedCheckpoint")
    apply_state_to_agent(reborn, state)

    assert (
        reborn.integrated_experience.to_checkpoint() == state["integrated_experience"]
    )
    assert reborn.cooperation_hub.to_checkpoint() == state["cooperation"]
    assert reborn.cooperation_hub.agents == {reborn.life_id: reborn}
    assert reborn.personality.narrative.memories[-1]["action"] == "create_draft"


def test_legacy_checkpoint_creates_clean_observers():
    agent = DigitalBeing(name="IntegratedLegacySource")
    state = build_state_from_agent(agent)
    state.pop("integrated_experience")
    state.pop("cooperation")

    reborn = DigitalBeing(name="IntegratedLegacyTarget")
    apply_state_to_agent(reborn, state)

    assert reborn.personality.narrative.memories == []
    assert reborn.hormonal_system.history == []
    assert reborn.cooperation_hub.message_history == []


def test_corrupted_integrated_section_leaves_agent_untouched():
    source = DigitalBeing(name="IntegratedInvalidSource")
    state = build_state_from_agent(source)
    pattern = state["integrated_experience"]["thinking_patterns"]["patterns"][
        "analytical_thinking"
    ]
    pattern["success_count"] = 1
    reborn = DigitalBeing(name="IntegratedInvalidTarget")
    before = _canonical_state(reborn)
    experience_before = reborn.integrated_experience.to_checkpoint()

    with pytest.raises(ValueError):
        apply_state_to_agent(reborn, state)

    assert _canonical_state(reborn) == before
    assert reborn.integrated_experience.to_checkpoint() == experience_before


def test_auxiliary_adapters_are_local_and_process_messages_autonomously():
    first = DigitalBeing(name="AuxiliaryFirst")
    second = DigitalBeing(name="AuxiliarySecond")

    assert first.cooperation_hub is not second.cooperation_hub
    assert first.voice_router.status()["enabled"] is True
    assert first.voice_router.status()["available_tts"]
    # Без настроенных endpoint-ов сетевой worker не нужен.
    assert first.webhooks.status()["worker_alive"] is False
    assert first.metrics._persist_dir is None

    # Совместная работа требует явно общего хаба; глобальной доставки нет.
    knowledge_before = deepcopy(second.knowledge_base)
    first.cooperation_hub.register_agent(second)
    assert first.cooperation_hub.send_message(
        first.life_id,
        second.life_id,
        MessageType.SHARE_KNOWLEDGE,
        '{"fact": "непроверенно"}',
        context="карантин",
    )
    assert tick_auxiliary_adapters(second, 1)["cooperation"]["pending_messages"] == 0
    second.cooperation_hub = first.cooperation_hub
    result = tick_auxiliary_adapters(second, 1)["cooperation"]
    assert result["processed_messages"] == 1
    assert result["actions"] == ["knowledge_quarantined"]
    assert result["pending_messages"] == 0
    assert second.cooperation_hub.get_pending_messages(second.life_id) == []
    assert second.knowledge_base == knowledge_before


def test_export_creative_draft_is_explicit_idempotent_effector_request():
    agent = DigitalBeing(name="CreativeExport")
    draft = perform_creative(agent, "new")
    effector = Mock()
    effector.submit.return_value = EffectorResult(
        request_id=f"creative-export-{draft['id']}-r{draft['revision']}",
        status=EffectorStatus.WAITING_APPROVAL,
    )
    agent.delamain_effector = effector

    result = agent.export_creative_draft()

    assert result["status"] == "waiting_approval"
    request = effector.submit.call_args.args[0]
    assert request.request_id == f"creative-export-{draft['id']}-r{draft['revision']}"
    assert request.plan[0]["action"] == "write_creative_draft"
    assert request.plan[0]["args"]["path"] == f"{draft['id']}.txt"
    assert request.metadata["activity"] == "creative"
    assert agent._creative_draft["revision"] == draft["revision"]
    effector.submit.assert_called_once_with(request)
