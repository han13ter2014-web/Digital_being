"""9B-2: ограниченный китайский диалог, evidence и offline-приёмка.

Исполняются 52 текущих ZH-сценария согласованной ревизии каталогов 9b3-r1.
Двенадцать отложенных сценариев в этом файле не исполняются; их полная
expected-приёмка находится в 9B-3. Сеть и живой data/ не используются.
"""

from __future__ import annotations

import socket
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.chinese_dialogue import (
    build_chinese_realization,
    chinese_response_references,
    recognize_chinese,
)
from src.core.dialogue_acts import classify_user_text
from src.core.language_context import detect_language
from src.core.response_experience import validate_response_plan
from tests.test_language_9b_baseline import (
    CHINESE_SCENARIOS,
    RUSSIAN_SCENARIOS,
    _make_runner,
    _new_runtime as _new_baseline_runtime,
    _run_russian,
)

CHINESE_EXECUTABLE = [
    scenario
    for scenario in CHINESE_SCENARIOS
    if scenario["driver"] in {"current_probe", "external_current_probe"}
]
CHINESE_DEFERRED = [
    scenario
    for scenario in CHINESE_SCENARIOS
    if scenario["driver"] == "not_current_executable"
]


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
    if context.dialogue_language == "zh" and input_language in {"zh", "mixed"}:
        return recognize_chinese(text, agent)
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
    before_memory = deepcopy(agent.mental_models.to_dict())
    expected = scenario["expected"]
    target_response_id = None
    if expected["outcome"] is not None:
        await _local_turn(agent, runner, "你好")
        target_response_id = agent.response_experience.latest_response_id
        before_memory = deepcopy(agent.mental_models.to_dict())
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
        node = agent.mental_models.concepts.get(concept_id)
        result["testimony_outcomes"] = [
            item.get("outcome")
            for item in (node.experiences if node is not None else [])
            if item.get("evidence_kind") == "testimony"
        ]
    elif expected["topic_policy"] == "no_new_memory":
        result["memory_unchanged"] = agent.mental_models.to_dict() == before_memory
    return agent, result


async def _run_external(scenario):
    agent, _, _ = _new_runtime(scenario)
    before_goal = deepcopy(agent.active_goal)
    before_memory = deepcopy(agent.mental_models.to_dict())
    owner = agent.social_registry.owner_profile_id
    setup = scenario["state_setup"]["external_session"]
    started = agent.external_contacts.start_session(
        agent.social_registry,
        provider="offline-fixture",
        name="Offline external",
        external_id="offline-external",
        topic=setup["topic"],
        reason="9B-2 offline acceptance",
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
    recognized = recognize_chinese(scenario["input"]["text"], agent)
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
        "memory_unchanged": agent.mental_models.to_dict() == before_memory,
    }
    return agent, result


async def run_chinese_scenario(scenario):
    if scenario["driver"] == "external_current_probe":
        return await _run_external(scenario)
    return await _run_local(scenario)


def _assert_chinese_expected(scenario, agent, result):
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
    if expected["dialogue_language"] == "zh":
        assert result["fallback_policy"] == expected["fallback_policy"]
    for reference in result["references"]:
        agent.response_experience._verify_reference(agent, reference)
    if expected["reference_policy"] == "no_references":
        assert result["references"] == []
    elif expected["reference_policy"].startswith("state:"):
        expected_references = [
            {"kind": "state", "id": item}
            for item in expected["reference_policy"].split(":", 1)[1].split(",")
        ]
        assert result["references"] == expected_references
    elif expected["reference_policy"].startswith("concept:"):
        assert result["references"] == [
            {"kind": "concept", "id": expected["reference_policy"].split(":", 1)[1]}
        ]
    if expected["topic_policy"].startswith(("known:", "testimony:")):
        concept_id = expected["topic_policy"].split(":", 1)[1]
        assert {"kind": "concept", "id": concept_id} in result["references"]
    if expected["topic_policy"].startswith("testimony:"):
        assert result["testimony_outcomes"] == [scenario["input"]["text"]]
    if expected["topic_policy"] == "no_new_memory":
        assert result["memory_unchanged"] is True
    if scenario["tags"] == ["anaphora"]:
        assert result["references"] == [
            {
                "kind": "dialogue_act",
                "id": scenario["state_setup"]["previous_act"]["kind"],
            }
        ]
    if scenario["driver"] == "external_current_probe":
        assert result["delivery_status"] == "draft"
        assert result["semantic_key"] == "instruction_boundary"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", CHINESE_EXECUTABLE, ids=lambda item: item["scenario_id"]
)
async def test_chinese_executable_scenarios_match_and_repeat(scenario, monkeypatch):
    def blocked_network(*args, **kwargs):
        raise AssertionError("9B-2 acceptance must remain offline")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    first_agent, first = await run_chinese_scenario(scenario)
    second_agent, second = await run_chinese_scenario(scenario)
    _assert_chinese_expected(scenario, first_agent, first)
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


def test_exactly_52_executable_and_12_deferred_remain_separate():
    assert len(CHINESE_EXECUTABLE) == 52
    assert sum(item["split"] == "chinese_practice" for item in CHINESE_EXECUTABLE) == 26
    assert sum(item["split"] == "chinese_heldout" for item in CHINESE_EXECUTABLE) == 26
    assert len(CHINESE_DEFERRED) == 12


def test_confirmed_links_and_realization_survive_checkpoint():
    agent = DigitalBeing(name="ChineseCheckpoint9B2")
    agent.cycle_count = 7
    agent.record_user_answer("число", "число — это понятие количества", 7)
    agent.language_concept_links.confirm_link(
        "число", "数字", language_id="zh", provenance="owner_confirmed_test"
    )
    agent.social_attribution.set_stable_dialogue_language("zh")
    agent.social_attribution.resolve_language("跟我说说数字。")
    agent.social_attribution.set_response_language("zh")
    recognition = recognize_chinese("跟我说说数字。", agent)
    realization = build_chinese_realization(agent, recognition)
    prepared = agent.response_experience.prepare_plan(
        agent,
        realization["text"],
        context=recognition.reply_context,
        source="test",
        references=chinese_response_references(recognition),
        chinese_realization=realization,
    )
    agent.response_experience.register_delivery("chinese-plan", prepared["plan"], 7)

    restored = DigitalBeing(name="ChineseCheckpoint9B2")
    apply_state_to_agent(restored, deepcopy(build_state_from_agent(agent)))

    assert (
        restored.language_concept_links.resolve("数字", language_id="zh")["concept_id"]
        == "число"
    )
    assert (
        restored.response_experience.responses["chinese-plan"]["plan"]
        == prepared["plan"]
    )
    assert recognize_chinese("跟我说说数字。", restored).concept_id == "число"


@pytest.mark.parametrize("mutation", ["text", "evidence", "references"])
def test_tampered_chinese_plan_is_rejected(mutation):
    agent = DigitalBeing(name="ChineseTamper9B2")
    agent.cycle_count = 3
    agent.social_attribution.set_stable_dialogue_language("zh")
    agent.social_attribution.resolve_language("你在做什么？")
    agent.social_attribution.set_response_language("zh")
    recognition = recognize_chinese("你在做什么？", agent)
    realization = build_chinese_realization(agent, recognition)
    plan = agent.response_experience.prepare_plan(
        agent,
        realization["text"],
        context=recognition.reply_context,
        source="test",
        references=chinese_response_references(recognition),
        chinese_realization=realization,
    )["plan"]
    if mutation == "text":
        plan["realization"]["text"] = "编造的状态。"
    elif mutation == "evidence":
        plan["realization"]["evidence"]["cycle"] = 999
    else:
        plan["references"] = []

    with pytest.raises(ValueError, match="chinese realization"):
        validate_response_plan(plan)


def test_han_detection_alone_does_not_authorize_chinese_response():
    agent = DigitalBeing(name="ChineseBoundary9B2")
    agent.social_attribution.set_stable_dialogue_language("zh")
    context = agent.social_attribution.resolve_language("你好")
    assert context.input_language == "zh"
    assert context.dialogue_language == "zh"
    assert context.response_language == "ru"
    assert agent.social_attribution.current_language_context() == context


@pytest.mark.asyncio
async def test_cross_language_feedback_does_not_capture_chinese_pending():
    agent = DigitalBeing(name="ChineseFeedbackBoundary9B2")
    agent.social_attribution.set_stable_dialogue_language("zh")
    runner, _ = _make_runner(agent)
    await _local_turn(agent, runner, "你好")
    response_id = agent.response_experience.latest_response_id
    agent.social_attribution.set_stable_dialogue_language("ru")

    await runner._on_user_message(SimpleNamespace(data={"text": "так понятно"}))

    record = agent.response_experience.responses[response_id]
    assert record["outcome"] != "explicit_support"
    assert record["plan"]["language_context"]["dialogue_language"] == "zh"
