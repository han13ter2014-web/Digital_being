"""9B-3: полная offline-диагностика ZH 64/64 и русский baseline 14/14.

Отложенные сценарии исполняются через реальный AgentRunner, profile switching и
checkpoint restart. Сеть и живой data/ не используются.
"""

from __future__ import annotations

import socket
from copy import deepcopy

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.ui.life_snapshot import build_life_snapshot
from tests.test_language_9b_2 import (
    CHINESE_DEFERRED,
    CHINESE_EXECUTABLE,
    _assert_chinese_expected,
    _local_turn,
    _new_baseline_runtime,
    run_chinese_scenario,
)
from tests.test_language_9b_baseline import (
    RUSSIAN_SCENARIOS,
    _make_runner,
    _run_russian,
)

CHINESE_SCENARIOS = CHINESE_EXECUTABLE + CHINESE_DEFERRED
RESTART_SECTIONS = (
    "user_interaction",
    "dialogue_learning",
    "associative_lexicon",
    "response_experience",
    "social_registry",
    "social_attribution",
    "language_concept_links",
    "english_language_tutor",
)


def _switch(agent, profile_id, *, cycle=0):
    if agent.social_registry.current_profile_id != profile_id:
        agent.social_registry.switch_to(profile_id, cycle=cycle)
        assert agent.social_attribution.sync_active_profile() is True
    else:
        agent.social_attribution.sync_active_profile()


def _new_deferred_runtime(scenario):
    agent, runner, bus = _new_baseline_runtime(scenario)
    for link in scenario["state_setup"]["cross_language_links"]:
        agent.language_concept_links.confirm_link(**link)
    profile_ids = {}
    legacy = scenario["checkpoint_setup"]["kind"] == "legacy_without_social_attribution"
    for descriptor in scenario["profile_setup"]["profiles"]:
        symbolic = descriptor["id"]
        if symbolic == "owner":
            profile_id = agent.social_registry.owner_profile_id
        elif symbolic == "guest":
            profile_id = agent.social_registry.create_local_person("Guest9B", cycle=1)
            agent.social_attribution.sync_active_profile()
        else:
            raise AssertionError(f"Unsupported 9B-3 profile: {symbolic}")
        profile_ids[symbolic] = profile_id
        agent.social_registry.set_preferred_language(
            descriptor["preferred_language"], profile_id=profile_id
        )
        stable = descriptor["stable_dialogue_language"]
        if stable is not None and not legacy:
            _switch(agent, profile_id, cycle=1)
            agent.social_attribution.set_stable_dialogue_language(stable)
    _switch(
        agent,
        profile_ids[scenario["profile_setup"]["current_profile"]],
        cycle=1,
    )
    runner, bus = _make_runner(agent)
    return agent, runner, bus, profile_ids


def _restart_after_response(agent, before_state):
    restored = DigitalBeing(name=agent.name)
    apply_state_to_agent(restored, deepcopy(before_state))
    after_state = build_state_from_agent(restored)
    preserved = all(
        after_state.get(key) == before_state.get(key) for key in RESTART_SECTIONS
    )
    runner, bus = _make_runner(restored)
    return restored, runner, bus, preserved and not bus.published


def _profile_states_isolated(agent, profile_ids, turns):
    if len(profile_ids) == 1:
        return True
    owner_id = profile_ids["owner"]
    guest_id = profile_ids["guest"]
    owner_state = agent.social_attribution.states.get(owner_id) or {}
    owner_language = (owner_state.get("language") or {}).get("last_context") or {}
    active_language = agent.social_attribution.current_language_context().to_dict()
    if owner_language.get("response_language") != "ru":
        return False
    if active_language.get("response_language") != "zh":
        return False
    owner_messages = (owner_state.get("user_interaction") or {}).get("messages") or []
    guest_messages = [
        item
        for item in agent.user_interaction.message_history
        if item.get("sender") == "user"
    ]
    owner_inputs = [
        item["content"] for item in owner_messages if item.get("sender") == "user"
    ]
    expected_owner = [
        turn["text"] for turn in turns if turn["current_profile"] == "owner"
    ]
    expected_guest = [
        turn["text"] for turn in turns if turn["current_profile"] == "guest"
    ]
    if owner_inputs != expected_owner:
        return False
    if [item["content"] for item in guest_messages] != expected_guest:
        return False
    owner_responses = (owner_state.get("response_experience") or {}).get(
        "responses"
    ) or []
    return all(
        item["plan"]["state"]["profile_id"] == owner_id for item in owner_responses
    ) and all(
        item["plan"]["state"]["profile_id"] == guest_id
        for item in agent.response_experience.responses.values()
    )


async def run_deferred_scenario(scenario):
    agent, runner, bus, profile_ids = _new_deferred_runtime(scenario)
    before_goal = deepcopy(agent.active_goal)
    turns = scenario["input"].get("turns") or [scenario["input"]]
    records = []
    restart_preserved = None
    for index, turn in enumerate(turns):
        symbolic = turn.get("current_profile", scenario["input"]["current_profile"])
        _switch(agent, profile_ids[symbolic], cycle=index + 1)
        explicit_switch = turn.get("explicit_switch", "none")
        if explicit_switch != "none":
            agent.social_attribution.set_stable_dialogue_language(
                explicit_switch.removeprefix("to_")
            )
        record = await _local_turn(agent, runner, turn["text"])
        record["explicit_switch"] = explicit_switch
        record["profile_symbol"] = symbolic
        record["outcome"] = None
        records.append(record)

    if scenario["restart_point"] == "after_response":
        before_state = build_state_from_agent(agent)
        agent, runner, bus, restart_preserved = _restart_after_response(
            agent, before_state
        )

    input_languages = {item["input_language"] for item in records}
    final = records[-1]
    result = {
        "act": "per_turn" if len(records) > 1 else final["act"],
        "reply_context": final["reply_context"],
        "text": final["text"],
        "input_language": (
            "mixed" if len(input_languages) > 1 else final["input_language"]
        ),
        "dialogue_language": final["dialogue_language"],
        "response_language": final["response_language"],
        "language_source": final["language_source"],
        "pending_after": final["pending_after"],
        "references": [ref for item in records for ref in item["references"]],
        "fallback_policy": "per_turn" if len(records) > 1 else final["fallback_policy"],
        "provenance_verified": all(item["provenance_verified"] for item in records),
        "profile_id": final["profile_id"],
        "realization": deepcopy(final["realization"]),
        "outcome": None,
        "explicit_switch": final["explicit_switch"],
        "active_goal_unchanged": agent.active_goal == before_goal,
        "profile_isolation_ok": _profile_states_isolated(agent, profile_ids, turns),
        "testimony_outcomes": [],
        "turns": records,
        "restart_preserved": restart_preserved,
        "automatic_external_actions": 0 if restart_preserved is not None else None,
        "ui_locale": scenario["state_setup"]["ui_locale"],
    }
    return agent, result


async def run_any_chinese_scenario(scenario):
    if scenario["driver"] == "not_current_executable":
        return await run_deferred_scenario(scenario)
    return await run_chinese_scenario(scenario)


def _assert_deferred_expected(scenario, agent, result):
    expected = scenario["expected"]
    for key in (
        "act",
        "reply_context",
        "input_language",
        "dialogue_language",
        "response_language",
        "language_source",
        "fallback_policy",
        "pending_after",
        "explicit_switch",
        "outcome",
    ):
        assert result[key] == expected[key], (scenario["scenario_id"], key, result[key])
    assert result["provenance_verified"] is True
    assert result["profile_isolation_ok"] is True
    assert result["active_goal_unchanged"] is True
    expected_turns = expected.get("turns") or [expected]
    assert len(result["turns"]) == len(expected_turns)
    for turn_result, turn_expected in zip(result["turns"], expected_turns, strict=True):
        for key in (
            "input_language",
            "response_language",
            "act",
            "reply_context",
            "explicit_switch",
        ):
            assert turn_result[key] == turn_expected[key], (
                scenario["scenario_id"],
                key,
                turn_result[key],
            )
        assert turn_result["provenance_verified"] is True
        realization = turn_result["realization"]
        if turn_expected["response_language"] == "zh":
            assert turn_result["dialogue_language"] == "zh"
            assert realization["act"] == turn_expected["act"]
            assert realization["language_id"] == "zh"
            assert realization["rule_id"]
    for reference in result["references"]:
        agent.response_experience._verify_reference(agent, reference)
    reference_policy = expected["reference_policy"]
    if reference_policy.startswith("state:"):
        assert result["references"] == [
            {"kind": "state", "id": item}
            for item in reference_policy.removeprefix("state:").split(",")
        ]
    if scenario["restart_point"] == "after_response":
        assert result["restart_preserved"] is True
        assert result["automatic_external_actions"] == 0
    if scenario["tags"] == ["ui_offline"]:
        assert result["ui_locale"] == "en"
        assert result["dialogue_language"] == "ru"
        assert result["response_language"] == "ru"
    if scenario["checkpoint_setup"]["kind"] == "legacy_without_social_attribution":
        assert result["language_source"] == "legacy_default"
        assert result["response_language"] == "ru"


def _assert_any_chinese_expected(scenario, agent, result):
    if scenario["driver"] == "not_current_executable":
        _assert_deferred_expected(scenario, agent, result)
    else:
        _assert_chinese_expected(scenario, agent, result)


def _normalize_dynamic(result):
    normalized = deepcopy(result)
    normalized["profile_id"] = "<dynamic-profile>"
    for turn in normalized.get("turns", []):
        turn["profile_id"] = "<dynamic-profile>"
    return normalized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", CHINESE_SCENARIOS, ids=lambda item: item["scenario_id"]
)
async def test_full_chinese_matrix_matches_and_repeats(scenario, monkeypatch):
    def blocked_network(*args, **kwargs):
        raise AssertionError("9B-3 acceptance must remain offline")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    first_agent, first = await run_any_chinese_scenario(scenario)
    second_agent, second = await run_any_chinese_scenario(scenario)
    _assert_any_chinese_expected(scenario, first_agent, first)
    assert _normalize_dynamic(first) == _normalize_dynamic(second)
    assert second_agent.language_concept_links.to_dict() == (
        first_agent.language_concept_links.to_dict()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", RUSSIAN_SCENARIOS, ids=lambda item: item["scenario_id"]
)
async def test_russian_baseline_remains_unchanged(scenario):
    first = await _run_russian(scenario)
    second = await _run_russian(scenario)
    assert first == second


def test_exact_full_matrix_contains_52_current_and_12_deferred():
    assert len(CHINESE_SCENARIOS) == 64
    assert len(CHINESE_EXECUTABLE) == 52
    assert len(CHINESE_DEFERRED) == 12
    assert sum(item["split"] == "chinese_practice" for item in CHINESE_SCENARIOS) == 32
    assert sum(item["split"] == "chinese_heldout" for item in CHINESE_SCENARIOS) == 32


@pytest.mark.asyncio
async def test_latest_dialogue_diagnostics_survive_restart_without_text_leak():
    scenario = next(
        item for item in CHINESE_DEFERRED if item["scenario_id"] == "zh_p_restart"
    )
    agent, result = await run_deferred_scenario(scenario)

    diagnostic = build_life_snapshot(agent)["dialogue"]

    assert result["restart_preserved"] is True
    assert diagnostic["available"] is True
    assert diagnostic["act"] == "ask_about_self"
    assert diagnostic["rule_id"] == "about_self"
    assert diagnostic["input_language"] == "zh"
    assert diagnostic["dialogue_language"] == "zh"
    assert diagnostic["response_language"] == "zh"
    assert diagnostic["language_source"] == "stable_dialogue"
    assert diagnostic["references_verified"] is True
    assert diagnostic["reference_count"] == 2
    assert result["text"] not in str(diagnostic)


@pytest.mark.asyncio
async def test_restart_scenarios_preserve_pending_and_personal_language_state():
    for scenario in CHINESE_DEFERRED:
        if scenario["restart_point"] != "after_response":
            continue
        agent, result = await run_deferred_scenario(scenario)
        assert result["restart_preserved"] is True
        assert agent.response_experience.responses
        latest = agent.response_experience.responses[
            agent.response_experience.latest_response_id
        ]
        assert latest["plan"]["language_context"]["profile_id"] == (
            agent.social_registry.current_profile_id
        )
        assert agent.user_interaction.get_pending_question() is None
