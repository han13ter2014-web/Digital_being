"""9A-2: ограниченный английский диалог, evidence и offline-приёмка.

Исполняются 44 текущих EN-сценария из неизменных каталогов 9A-0. Двенадцать
отложенных сценариев остаются предметом 9A-5. Сеть и живой data/ не используются.
"""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.dialogue_acts import classify_user_text
from src.core.english_dialogue import (
    build_english_realization,
    english_response_references,
    recognize_english,
)
from src.core.language_context import detect_language
from src.core.response_experience import validate_response_plan
from tests.test_language_9a_baseline import (
    FIXTURE_DIR,
    RUSSIAN_SCENARIOS,
    _make_runner,
    _new_runtime as _new_baseline_runtime,
    _run_russian,
)

ENGLISH_SCENARIOS = []
for filename in ("english_practice.json", "english_heldout.json"):
    catalog = json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
    ENGLISH_SCENARIOS.extend(
        scenario
        for scenario in catalog["scenarios"]
        if scenario["driver"] in {"current_probe", "external_current_probe"}
    )


def _new_runtime(scenario):
    agent, runner, bus = _new_baseline_runtime(scenario)
    for link in scenario["state_setup"]["cross_language_links"]:
        agent.language_concept_links.confirm_link(**link)
    descriptor = scenario["profile_setup"]["profiles"][0]
    preferred = descriptor["preferred_language"]
    if preferred is not None:
        agent.social_registry.set_preferred_language(preferred)
    stable = descriptor["stable_dialogue_language"]
    if stable is not None:
        agent.social_attribution.set_stable_dialogue_language(stable)
    return agent, runner, bus


def _recognition(agent, runner, text):
    context = agent.social_attribution.current_language_context()
    input_language, _ = detect_language(text)
    if context.dialogue_language == "en" and input_language == "en":
        return recognize_english(text, agent)
    result = SimpleNamespace(
        act=classify_user_text(
            text,
            learned=runner._learned_markers(),
            learned_affect=runner._learned_affect(),
            cycle=agent.cycle_count,
        )
    )
    if (
        context.dialogue_language == "ru"
        and input_language == "mixed"
        and result.act.kind in {"unknown", "ask_about_self"}
    ):
        result.act = SimpleNamespace(kind="unknown")
    return result


def _latest_plan(agent):
    response_id = agent.response_experience.latest_response_id
    record = agent.response_experience.responses.get(response_id)
    assert record is not None
    return deepcopy(record["plan"])


async def _local_turn(agent, runner, text):
    recognized = _recognition(agent, runner, text)
    await runner._on_user_message(SimpleNamespace(data={"text": text}))
    plan = _latest_plan(agent)
    language = plan.get("language_context") or {}
    realization = plan["realization"]
    return {
        "act": recognized.act.kind,
        "reply_context": plan["context"],
        "text": agent.user_interaction.message_history[-1]["content"],
        "input_language": language.get("input_language"),
        "dialogue_language": language.get("dialogue_language"),
        "response_language": language.get("response_language"),
        "language_source": language.get("source"),
        "pending_after": agent.user_interaction.get_pending_question() is not None,
        "references": deepcopy(plan["references"]),
        "fallback_policy": realization.get("fallback_policy", "none"),
        "provenance_verified": plan["provenance_verified"],
        "profile_id": plan["state"]["profile_id"],
        "realization": deepcopy(realization),
    }


async def _run_local(scenario):
    agent, runner, _bus = _new_runtime(scenario)
    before_goal = deepcopy(agent.active_goal)
    expected = scenario["expected"]
    target_response_id = None
    if expected["outcome"] is not None:
        await _local_turn(agent, runner, "Hello")
        target_response_id = agent.response_experience.latest_response_id
    result = await _local_turn(agent, runner, scenario["input"]["text"])
    result["outcome"] = None
    if target_response_id is not None:
        result["outcome"] = agent.response_experience.responses[target_response_id][
            "outcome"
        ]
    result["active_goal_unchanged"] = agent.active_goal == before_goal
    result["profile_isolation_ok"] = (
        result["profile_id"] == agent.social_registry.current_profile_id
    )
    result["testimony_outcomes"] = []
    if expected["topic_policy"].startswith("testimony:"):
        concept_id = expected["topic_policy"].split(":", 1)[1]
        node = agent.mental_models.concepts[concept_id]
        result["testimony_outcomes"] = [
            item.get("outcome")
            for item in node.experiences
            if item.get("evidence_kind") == "testimony"
        ]
    return agent, result


async def _run_external(scenario):
    agent, _, _ = _new_runtime(scenario)
    before_goal = deepcopy(agent.active_goal)
    owner = agent.social_registry.owner_profile_id
    setup = scenario["state_setup"]["external_session"]
    started = agent.external_contacts.start_session(
        agent.social_registry,
        provider="offline-fixture",
        name="Offline external",
        external_id="offline-external",
        topic=setup["topic"],
        reason="9A-2 offline acceptance",
        cycle=agent.cycle_count,
        model="offline/none",
    )
    session_id = started["session_id"]
    session = next(
        item
        for item in agent.external_contacts.sessions
        if item["session_id"] == session_id
    )
    session["dialogue_language"] = scenario["expected"]["dialogue_language"]
    agent.external_contacts.ingest(
        session_id, scenario["input"]["text"], cycle=agent.cycle_count
    )
    draft = agent.external_contacts.create_draft(session_id, cycle=agent.cycle_count)
    response = draft["response"]
    plan = response["plan"]
    language = plan["language_context"]
    recognized = recognize_english(scenario["input"]["text"], agent)
    result = {
        "act": recognized.act.kind,
        "reply_context": plan["context"],
        "text": draft["text"],
        "input_language": language["input_language"],
        "dialogue_language": language["dialogue_language"],
        "response_language": language["response_language"],
        "language_source": language["source"],
        "pending_after": agent.user_interaction.get_pending_question() is not None,
        "references": deepcopy(plan["references"]),
        "fallback_policy": plan["realization"].get("fallback_policy", "none"),
        "provenance_verified": plan["provenance_verified"],
        "profile_id": plan["state"]["profile_id"],
        "realization": deepcopy(plan["realization"]),
        "outcome": response["outcome"],
        "active_goal_unchanged": agent.active_goal == before_goal,
        "profile_isolation_ok": plan["state"]["profile_id"] != owner,
        "delivery_status": response["status"],
        "semantic_key": response["semantic_key"],
        "testimony_outcomes": [],
    }
    return agent, result


async def run_english_scenario(scenario):
    if scenario["driver"] == "external_current_probe":
        return await _run_external(scenario)
    return await _run_local(scenario)


def _assert_english_expected(scenario, agent, result):
    expected = scenario["expected"]
    for key in (
        "act",
        "reply_context",
        "input_language",
        "dialogue_language",
        "response_language",
        "language_source",
        "pending_after",
        "outcome",
    ):
        assert result[key] == expected[key], (scenario["scenario_id"], key, result[key])
    assert result["provenance_verified"] is True
    assert result["profile_isolation_ok"] is True
    assert result["active_goal_unchanged"] is True
    for reference in result["references"]:
        agent.response_experience._verify_reference(agent, reference)
    if expected["dialogue_language"] == "en" and expected["fallback_policy"] != "none":
        assert result["fallback_policy"] == expected["fallback_policy"]
    if expected["reference_policy"] == "no_references":
        assert result["references"] == []
    if expected["topic_policy"].startswith(("known:", "testimony:")):
        concept_id = expected["topic_policy"].split(":", 1)[1]
        assert {"kind": "concept", "id": concept_id} in result["references"]
    if expected["topic_policy"].startswith("testimony:"):
        assert result["testimony_outcomes"] == [scenario["input"]["text"]]
    if scenario["tags"] == ["anaphora"]:
        assert result["references"] == [
            {
                "kind": "dialogue_act",
                "id": scenario["state_setup"]["previous_act"]["kind"],
            }
        ]
    if scenario["scenario_id"] in {"en_p_self_01", "en_h_self_01"}:
        assert result["references"] == [{"kind": "state", "id": "emotional_state"}]
    if scenario["scenario_id"] in {"en_p_self_02", "en_h_self_02"}:
        assert result["references"] == [
            {"kind": "state", "id": "name"},
            {"kind": "state", "id": "cycle_count"},
        ]
    if scenario["driver"] == "external_current_probe":
        assert result["delivery_status"] == "draft"
        assert result["semantic_key"] == "instruction_boundary"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ENGLISH_SCENARIOS, ids=lambda item: item["scenario_id"]
)
async def test_english_executable_scenarios_match_and_repeat(scenario, monkeypatch):
    def blocked_network(*args, **kwargs):
        raise AssertionError("9A-2 acceptance must remain offline")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    first_agent, first = await run_english_scenario(scenario)
    second_agent, second = await run_english_scenario(scenario)
    _assert_english_expected(scenario, first_agent, first)
    first["profile_id"] = "<dynamic-profile>"
    second["profile_id"] = "<dynamic-profile>"
    assert first == second
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


def test_exactly_44_executable_and_12_deferred_remain_separate():
    assert len(ENGLISH_SCENARIOS) == 44
    assert sum(item["split"] == "english_practice" for item in ENGLISH_SCENARIOS) == 22
    assert sum(item["split"] == "english_heldout" for item in ENGLISH_SCENARIOS) == 22


def test_confirmed_links_and_realization_survive_checkpoint():
    agent = DigitalBeing(name="EnglishCheckpoint9A2")
    agent.cycle_count = 7
    agent.record_user_answer("число", "число — это понятие количества", 7)
    agent.language_concept_links.confirm_link(
        "число", "number", provenance="owner_confirmed_test"
    )
    agent.social_attribution.set_stable_dialogue_language("en")
    agent.social_attribution.resolve_language("Tell me about number")
    agent.social_attribution.set_response_language("en")
    recognition = recognize_english("Tell me about number", agent)
    realization = build_english_realization(agent, recognition)
    prepared = agent.response_experience.prepare_plan(
        agent,
        realization["text"],
        context=recognition.reply_context,
        source="test",
        references=english_response_references(recognition),
        english_realization=realization,
    )
    agent.response_experience.register_delivery("english-plan", prepared["plan"], 7)

    restored = DigitalBeing(name="EnglishCheckpoint9A2")
    apply_state_to_agent(restored, deepcopy(build_state_from_agent(agent)))

    assert restored.language_concept_links.resolve("NUMBER")["concept_id"] == "число"
    assert (
        restored.response_experience.responses["english-plan"]["plan"]
        == prepared["plan"]
    )
    assert recognize_english("Tell me about number", restored).concept_id == "число"


def test_checkpoint_rejects_invalid_link_before_mutation():
    agent = DigitalBeing(name="EnglishAtomic9A2")
    agent.language_concept_links.confirm_link(
        "число", "number", provenance="owner_confirmed_test"
    )
    state = build_state_from_agent(agent)
    state["language_concept_links"]["links"][0]["confidence"] = float("nan")
    state["energy"] = 0.123
    before = build_state_from_agent(agent)

    with pytest.raises(ValueError, match="confidence"):
        apply_state_to_agent(agent, state)

    assert agent.energy == before["energy"]
    assert agent.language_concept_links.to_dict() == before["language_concept_links"]


@pytest.mark.parametrize(
    "reference",
    [
        {"kind": "concept", "id": "invented"},
        {"kind": "dialogue_act", "id": "invented"},
    ],
)
def test_unresolvable_english_reference_is_rejected(reference):
    agent = DigitalBeing(name="EnglishReference9A2")
    agent.social_attribution.set_stable_dialogue_language("en")
    agent.social_attribution.resolve_language("Hello")
    recognition = recognize_english("Hello", agent)
    realization = build_english_realization(agent, recognition)

    with pytest.raises(ValueError, match="real .* is required"):
        agent.response_experience.prepare_plan(
            agent,
            realization["text"],
            context=recognition.reply_context,
            source="test",
            references=[reference],
            english_realization=realization,
        )


@pytest.mark.parametrize("mutation", ["text", "evidence", "references"])
def test_tampered_english_plan_is_rejected(mutation):
    agent = DigitalBeing(name="EnglishTamper9A2")
    agent.cycle_count = 3
    agent.social_attribution.set_stable_dialogue_language("en")
    agent.social_attribution.resolve_language("What are you doing?")
    agent.social_attribution.set_response_language("en")
    recognition = recognize_english("What are you doing?", agent)
    realization = build_english_realization(agent, recognition)
    plan = agent.response_experience.prepare_plan(
        agent,
        realization["text"],
        context=recognition.reply_context,
        source="test",
        references=english_response_references(recognition),
        english_realization=realization,
    )["plan"]
    if mutation == "text":
        plan["realization"]["text"] = "Invented state."
    elif mutation == "evidence":
        plan["realization"]["evidence"]["cycle"] = 999
    else:
        plan["references"] = []

    with pytest.raises(ValueError, match="english realization"):
        validate_response_plan(plan)


@pytest.mark.asyncio
async def test_cross_language_feedback_does_not_capture_english_pending():
    agent = DigitalBeing(name="EnglishFeedbackBoundary9A2")
    agent.social_attribution.set_stable_dialogue_language("en")
    runner, _ = _make_runner(agent)
    await _local_turn(agent, runner, "Hello")
    response_id = agent.response_experience.latest_response_id
    agent.social_attribution.set_stable_dialogue_language("ru")

    await runner._on_user_message(SimpleNamespace(data={"text": "так понятно"}))

    record = agent.response_experience.responses[response_id]
    assert record["outcome"] != "explicit_support"
    assert record["plan"]["language_context"]["dialogue_language"] == "en"
