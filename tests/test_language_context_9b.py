"""9B-1/9B-2: Han-детекция, китайский контекст и границы realization.

Двенадцать отложенных сценариев здесь выполняются только как context-only
проверки. Их ожидания китайского ответа в этом файле намеренно не assert-ятся;
полная expected-приёмка находится в 9B-3. Каталоги применяются единой ревизией
9b3-r1; сеть и живой data/ не используются.
"""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.dialogue_learning import DialogueLearning
from src.core.language_context import (
    LanguageContext,
    detect_language,
    resolve_language_context,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "language_9b"
DEFERRED_SCENARIOS = []
for filename in ("chinese_practice.json", "chinese_heldout.json"):
    catalog = json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
    DEFERRED_SCENARIOS.extend(
        scenario
        for scenario in catalog["scenarios"]
        if scenario["driver"] == "not_current_executable"
    )


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(agent):
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return runner, bus


def _switch(agent, profile_id, cycle=1):
    if agent.social_registry.current_profile_id == profile_id:
        agent.social_attribution.sync_active_profile()
        return
    agent.social_registry.switch_to(profile_id, cycle=cycle)
    assert agent.social_attribution.sync_active_profile() is True


def _current_context(agent):
    return agent.social_attribution.current_language_context().to_dict()


def _configure_scenario(scenario):
    agent = DigitalBeing(name=scenario["state_setup"]["agent_name"])
    agent.cycle_count = scenario["state_setup"]["cycle"]
    profile_ids = {}
    for descriptor in scenario["profile_setup"]["profiles"]:
        symbolic_id = descriptor["id"]
        if symbolic_id == "owner":
            profile_id = agent.social_registry.owner_profile_id
        elif symbolic_id == "guest":
            profile_id = agent.social_registry.create_local_person("Guest9B", cycle=1)
            agent.social_attribution.sync_active_profile()
        else:
            raise AssertionError(f"Unsupported context-only profile: {symbolic_id}")
        profile_ids[symbolic_id] = profile_id
        agent.social_registry.set_preferred_language(
            descriptor["preferred_language"], profile_id=profile_id
        )
        if descriptor["stable_dialogue_language"] is not None:
            _switch(agent, profile_id)
            agent.social_attribution.set_stable_dialogue_language(
                descriptor["stable_dialogue_language"]
            )
    _switch(agent, profile_ids[scenario["profile_setup"]["current_profile"]])
    return agent, profile_ids


def _run_context_scenario(scenario):
    agent, profile_ids = _configure_scenario(scenario)
    if scenario["checkpoint_setup"]["kind"] == "legacy_without_social_attribution":
        state = build_state_from_agent(agent)
        state.pop("social_attribution")
        restored = DigitalBeing(name=agent.name)
        apply_state_to_agent(restored, state)
        agent = restored

    turns = scenario["input"].get("turns") or [scenario["input"]]
    expected_turns = scenario["expected"].get("turns") or [scenario["expected"]]
    records = []
    for index, (turn, expected) in enumerate(zip(turns, expected_turns, strict=True)):
        symbolic_profile = turn.get(
            "current_profile", scenario["input"]["current_profile"]
        )
        _switch(agent, profile_ids[symbolic_profile], cycle=index + 1)
        explicit_switch = turn.get("explicit_switch", "none")
        if explicit_switch != "none":
            agent.social_attribution.set_stable_dialogue_language(
                explicit_switch.removeprefix("to_")
            )
        context = agent.social_attribution.resolve_language(turn["text"])
        prepared = agent.response_experience.prepare_plan(
            agent,
            "Ответ пока реализуется по-русски.",
            context="about_self",
            source="language_9b_1_context_only",
            user_text=turn["text"],
        )
        assert prepared["plan"]["language_context"] == context.to_dict()
        preferred = agent.social_registry.current_profile()["preferred_language"]
        if preferred is not None:
            expected_source = "profile_preference"
            expected_dialogue = preferred
        elif (
            scenario["checkpoint_setup"]["kind"] == "legacy_without_social_attribution"
        ):
            expected_source = "legacy_default"
            expected_dialogue = "ru"
        else:
            expected_source = "stable_dialogue"
            expected_dialogue = agent.social_attribution._language[
                "stable_dialogue_language"
            ]
        assert context.input_language == expected["input_language"]
        assert context.dialogue_language == expected_dialogue
        assert context.response_language == "ru"
        assert context.source == expected_source
        records.append(
            {
                "profile": symbolic_profile,
                "input_language": context.input_language,
                "dialogue_language": context.dialogue_language,
                "response_language": context.response_language,
                "source": context.source,
            }
        )

    if scenario["restart_point"] == "after_response":
        response_id = "language-9b-1-restart"
        agent.response_experience.register_delivery(
            response_id, prepared["plan"], agent.cycle_count
        )
        before = _current_context(agent)
        state = build_state_from_agent(agent)
        restored = DigitalBeing(name=agent.name)
        apply_state_to_agent(restored, state)
        assert _current_context(restored) == before
        assert (
            restored.response_experience.responses[response_id]["plan"][
                "language_context"
            ]
            == before
        )
        agent = restored

    assert records[-1]["dialogue_language"] == scenario["expected"]["dialogue_language"]
    assert records[-1]["source"] == scenario["expected"]["language_source"]
    return records


@pytest.mark.parametrize(
    ("text", "expected", "confidence"),
    [
        ("你好，世界！", "zh", 1.0),
        ("㐀", "zh", 1.0),
        ("GitHub是什么意思？", "mixed", 0.454545),
        ("我和Пользователь都想了解记忆。", "mixed", 0.4),
        ("123 …", "unknown", 0.0),
        ("😀", "unknown", 0.0),
        ("https://example.com/数字", "unknown", 0.0),
        ("这是测试：https://example.com/数字 😀", "zh", 1.0),
    ],
)
def test_han_detector(text, expected, confidence):
    assert detect_language(text) == (expected, confidence)


def test_zh_preference_stable_dialogue_and_detector_keep_russian_response():
    preferred, _ = resolve_language_context(
        "你好",
        profile_id="owner",
        preferred_language="ru",
        stable_dialogue_language="zh",
    )
    stable, _ = resolve_language_context(
        "Привет", profile_id="owner", stable_dialogue_language="zh"
    )
    detected, _ = resolve_language_context("你好", profile_id="guest")

    assert preferred.dialogue_language == "ru"
    assert preferred.source == "profile_preference"
    assert preferred.input_language == "zh"
    assert stable.dialogue_language == "zh"
    assert stable.source == "stable_dialogue"
    assert stable.input_language == "ru"
    assert detected.dialogue_language == "zh"
    assert detected.source == "limited_detector"
    assert detected.response_language == "ru"
    assert all(
        context.response_language == "ru" for context in (preferred, stable, detected)
    )


def test_zh_realization_requires_matching_dialogue():
    context = LanguageContext(
        profile_id="owner",
        input_language="zh",
        dialogue_language="zh",
        response_language="zh",
        source="limited_detector",
        confidence=1.0,
    )
    assert context.response_language == "zh"
    agent = DigitalBeing(name="LanguageRealizationBoundary9B2")
    agent.social_attribution.set_stable_dialogue_language("ru")
    agent.social_attribution.resolve_language("Привет")
    with pytest.raises(ValueError, match="response_language"):
        agent.social_attribution.set_response_language("zh")
    agent.social_attribution.set_stable_dialogue_language("zh")
    agent.social_attribution.resolve_language("你好")
    resolved = agent.social_attribution.set_response_language("zh")
    assert resolved.dialogue_language == "zh"
    assert resolved.response_language == "zh"


def test_dialogue_learning_preserves_independent_zh_state_and_restart():
    learning = DialogueLearning()
    learning.resolve("русская фраза", "1", 1)
    learning.set_language("zh")
    assert learning.learned == {}
    learning.resolve("中文短语", "1", 2)
    learning.set_language("ru")
    assert set(learning.learned) == {"русская фраза"}

    snapshot = learning.to_dict()
    validate_checkpoint_state({"dialogue_learning": snapshot})
    restored = DialogueLearning()
    restored.load_from(deepcopy(snapshot))
    restored.set_language("zh")
    assert set(restored.learned) == {"中文短语"}


@pytest.mark.asyncio
async def test_agent_runner_uses_checked_zh_realization():
    agent = DigitalBeing(name="LanguageRunner9B2")
    agent.social_attribution.set_stable_dialogue_language("zh")
    runner, _ = _make_runner(agent)

    await runner._on_user_message(SimpleNamespace(data={"text": "你好"}))

    context = agent.social_attribution.current_language_context()
    assert agent.dialogue_learning.active_language == "zh"
    assert context.input_language == "zh"
    assert context.dialogue_language == "zh"
    assert context.response_language == "zh"
    plan = agent.response_experience.responses[
        agent.response_experience.latest_response_id
    ]["plan"]
    assert plan["realization"]["language_id"] == "zh"
    assert plan["realization"]["rule_id"] == "social_greeting"


@pytest.mark.parametrize(
    "scenario", DEFERRED_SCENARIOS, ids=lambda item: item["scenario_id"]
)
def test_deferred_chinese_fixtures_context_only_repeatable(scenario, monkeypatch):
    def blocked_network(*args, **kwargs):
        raise AssertionError("9B-1 context-only tests must remain offline")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    first = _run_context_scenario(scenario)
    second = _run_context_scenario(scenario)

    assert first == second
    assert all(record["response_language"] == "ru" for record in first)


def test_exactly_twelve_deferred_fixtures_are_now_context_checked():
    assert len(DEFERRED_SCENARIOS) == 12
    assert {scenario["scenario_id"] for scenario in DEFERRED_SCENARIOS} == {
        "zh_p_switch_01",
        "zh_p_switch_02",
        "zh_p_profiles",
        "zh_p_restart",
        "zh_p_legacy",
        "zh_p_ui_locale",
        "zh_h_switch_01",
        "zh_h_switch_02",
        "zh_h_profiles",
        "zh_h_restart",
        "zh_h_legacy",
        "zh_h_ui_locale",
    }
