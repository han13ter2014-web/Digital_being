"""9A-1: языковой контекст без английских recognition/realization.

Двенадцать отложенных сценариев 9A-0 выполняются только как context-only
проверки. Их будущие ожидания английского ответа здесь намеренно не assert-ятся.
Тесты автономны и используют изолированный data/ из общего conftest.py.
"""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from pathlib import Path

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.event_bus import Events
from src.core.language_context import (
    LanguageContext,
    detect_language,
    resolve_language_context,
    validate_language_context,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "language_9a"
DEFERRED_SCENARIOS = []
for filename in ("english_practice.json", "english_heldout.json"):
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
            profile_id = agent.social_registry.create_local_person("Guest9A", cycle=1)
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
            source="language_9a_1_context_only",
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
        response_id = "language-9a-1-restart"
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
    return agent, records


@pytest.mark.parametrize(
    ("text", "expected", "confidence"),
    [
        ("Привет, как дела?", "ru", 1.0),
        ("Hello, how are you?", "en", 1.0),
        ("Привет, hello", "mixed", 0.454545),
        ("123 …", "unknown", 0.0),
        ("https://example.com/path", "unknown", 0.0),
        ("Python", "en", 1.0),
    ],
)
def test_limited_detector(text, expected, confidence):
    assert detect_language(text) == (expected, confidence)


def test_preference_and_stable_dialogue_outrank_detector():
    preferred, _ = resolve_language_context(
        "Привет",
        profile_id="owner",
        preferred_language="en",
        stable_dialogue_language="ru",
    )
    stable_ru, _ = resolve_language_context(
        "Python", profile_id="owner", stable_dialogue_language="ru"
    )
    stable_en, _ = resolve_language_context(
        "Глеб", profile_id="owner", stable_dialogue_language="en"
    )
    detected, _ = resolve_language_context("Hello world", profile_id="guest")

    assert preferred.dialogue_language == "en"
    assert preferred.source == "profile_preference"
    assert preferred.input_language == "ru"
    assert stable_ru.dialogue_language == "ru"
    assert stable_ru.source == "stable_dialogue"
    assert stable_en.dialogue_language == "en"
    assert stable_en.input_language == "ru"
    assert detected.dialogue_language == "en"
    assert detected.source == "limited_detector"
    assert detected.response_language == "ru"


def test_explicit_internal_switch_ru_en_ru_does_not_enable_english_realization():
    agent = DigitalBeing(name="LanguageSwitch9A1")
    assert agent.social_attribution.resolve_language("Привет").dialogue_language == "ru"

    agent.social_attribution.set_stable_dialogue_language("en")
    english = agent.social_attribution.resolve_language("What are you doing?")
    agent.social_attribution.set_stable_dialogue_language("ru")
    russian = agent.social_attribution.resolve_language("Чем занимаешься?")

    assert english.dialogue_language == "en"
    assert english.response_language == "ru"
    assert russian.dialogue_language == "ru"
    assert russian.response_language == "ru"


@pytest.mark.asyncio
async def test_language_survives_delivery_feedback_and_outcome():
    agent = DigitalBeing(name="LanguageDelivery9A1")
    agent.social_attribution.set_stable_dialogue_language("en")
    context = agent.social_attribution.resolve_language("Hello").to_dict()
    agent.user_interaction.receive_user_message("Hello", cycle=agent.cycle_count)
    runner, bus = _make_runner(agent)

    response_id = await runner._reply_to_user(
        "Русский ответ.", context="social_reply", source="test", user_text="Hello"
    )

    record = agent.response_experience.responses[response_id]
    assert record["plan"]["language_context"] == context
    incoming = [
        item
        for item in agent.user_interaction.message_history
        if item["sender"] == "user"
    ]
    outgoing = [
        item
        for item in agent.user_interaction.message_history
        if item["sender"] == "agent"
    ]
    events = [data for name, data in bus.published if name == Events.AGENT_MESSAGE]
    assert incoming[-1]["language_context"] == context
    assert outgoing[-1]["language_context"] == context
    assert events[-1]["language_context"] == context
    assert context["dialogue_language"] == "en"
    assert context["response_language"] == "ru"

    observed = agent.response_experience.observe_feedback(
        response_id, "support", agent.cycle_count
    )
    assert observed["outcome"] == "explicit_support"
    assert observed["plan"]["language_context"] == context


@pytest.mark.asyncio
async def test_pending_history_plan_and_language_restart_together():
    agent = DigitalBeing(name="LanguageRestart9A1")
    agent.social_attribution.set_stable_dialogue_language("en")
    first = agent.social_attribution.resolve_language("Hello")
    asked = agent.user_interaction.ask_user("Первый вопрос?", cycle=1)
    agent.user_interaction.submit_answer(asked["id"], "Ответ", cycle=2)
    agent.cycle_count = 100
    second = agent.social_attribution.resolve_language("Hello again")
    agent.user_interaction.ask_user("Вопрос после ответа?", cycle=100)
    runner, _ = _make_runner(agent)
    response_id = await runner._reply_to_user(
        "Русский ответ.", context="social_reply", source="test", user_text="Hello again"
    )
    state = build_state_from_agent(agent)

    restored = DigitalBeing(name=agent.name)
    apply_state_to_agent(restored, deepcopy(state))

    assert restored.social_attribution._language["stable_dialogue_language"] == "en"
    assert _current_context(restored) == second.to_dict()
    assert restored.user_interaction.question_history[0]["language_context"] == (
        first.to_dict()
    )
    pending = restored.user_interaction.get_pending_question()
    assert pending["language_context"] == second.to_dict()
    assert restored.user_interaction.message_history[-1]["language_context"] == (
        second.to_dict()
    )
    assert (
        restored.response_experience.responses[response_id]["plan"]["language_context"]
        == second.to_dict()
    )
    restored.user_interaction.submit_answer(pending["id"], "Новый ответ", cycle=101)
    assert restored.user_interaction.question_history[-1]["language_context"] == (
        second.to_dict()
    )


def test_owner_and_guest_keep_pending_plans_and_languages_isolated():
    agent = DigitalBeing(name="LanguageProfiles9A1")
    agent.cycle_count = 1
    owner = agent.social_registry.owner_profile_id
    owner_context = agent.social_attribution.resolve_language("Привет").to_dict()
    agent.user_interaction.ask_user("Вопрос владельцу?", cycle=1)
    owner_plan = agent.response_experience.prepare_plan(
        agent, "Ответ владельцу.", context="social_reply", source="test"
    )["plan"]
    agent.response_experience.register_delivery("owner-response", owner_plan, 1)

    guest = agent.social_registry.create_local_person("Guest", cycle=2)
    agent.social_attribution.sync_active_profile()
    agent.cycle_count = 100
    agent.social_registry.set_preferred_language("en")
    guest_context = agent.social_attribution.resolve_language("Hello").to_dict()
    agent.user_interaction.ask_user("Вопрос гостю?", cycle=100)
    guest_plan = agent.response_experience.prepare_plan(
        agent, "Ответ гостю.", context="social_reply", source="test"
    )["plan"]
    agent.response_experience.register_delivery("guest-response", guest_plan, 100)

    assert guest_context["dialogue_language"] == "en"
    assert guest_context["response_language"] == "ru"
    _switch(agent, owner, cycle=101)
    assert _current_context(agent) == owner_context
    assert agent.user_interaction.get_pending_question()["question"] == (
        "Вопрос владельцу?"
    )
    assert set(agent.response_experience.responses) == {"owner-response"}
    guest_state = agent.social_attribution.states[guest]
    assert guest_state["language"]["last_context"] == guest_context
    assert (
        guest_state["user_interaction"]["pending_questions"][0]["language_context"]
        == guest_context
    )
    assert (
        guest_state["response_experience"]["responses"][0]["plan"]["language_context"]
        == guest_context
    )


def test_legacy_v1_snapshots_and_missing_attribution_remain_russian_owner_state():
    source = DigitalBeing(name="LanguageLegacy9A1")
    source.cycle_count = 1
    source.social_attribution.resolve_language("Привет")
    plan = source.response_experience.prepare_plan(
        source, "Старый ответ.", context="social_reply", source="test"
    )["plan"]
    source.response_experience.register_delivery("legacy-response", plan, 1)
    state = build_state_from_agent(source)
    registry = state["social_registry"]
    registry["schema_version"] = 1
    for profile in registry["profiles"].values():
        profile.pop("preferred_language")
    attribution = state["social_attribution"]
    attribution["schema_version"] = 1
    for personal in attribution["states"].values():
        personal.pop("language")
    for experience in [state["response_experience"]] + [
        personal["response_experience"] for personal in attribution["states"].values()
    ]:
        experience["schema_version"] = 1
        for response in experience["responses"]:
            response["plan"].pop("language_context", None)

    restored = DigitalBeing(name="LanguageLegacyRestored9A1")
    apply_state_to_agent(restored, state)
    owner = restored.social_registry.owner_profile_id
    assert restored.social_registry.current_profile()["preferred_language"] is None
    legacy_plan = restored.response_experience.responses["legacy-response"]["plan"]
    assert legacy_plan["realization"]["base_text"] == "Старый ответ."
    assert "language_context" not in legacy_plan
    assert _current_context(restored)["dialogue_language"] == "ru"
    assert _current_context(restored)["source"] == "legacy_default"
    assert restored.social_attribution.resolve_language(
        "Как дела?"
    ).dialogue_language == ("ru")

    state.pop("social_attribution")
    legacy = DigitalBeing(name="LanguageLegacyOnly9A1")
    apply_state_to_agent(legacy, state)
    assert legacy.social_registry.current_profile_id == owner
    assert set(legacy.social_attribution.states) == {owner}
    assert _current_context(legacy)["source"] == "legacy_default"


def test_external_session_plan_does_not_inherit_owner_language():
    agent = DigitalBeing(name="LanguageExternal9A1")
    agent.social_attribution.set_stable_dialogue_language("en")
    agent.social_attribution.resolve_language("Hello")

    prepared = agent.response_experience.prepare_plan(
        agent,
        "Session-scoped text.",
        context="external_reply",
        source="test",
        profile_id="external-session",
        expire_pending=False,
    )

    assert "language_context" not in prepared["plan"]


@pytest.mark.parametrize(
    "patch",
    [
        {"input_language": "de"},
        {"source": "guessed"},
        {"confidence": float("nan")},
        {"confidence": True},
    ],
)
def test_invalid_language_context_is_rejected(patch):
    data = LanguageContext(
        profile_id="owner",
        input_language="en",
        dialogue_language="en",
        response_language="ru",
        source="limited_detector",
        confidence=1.0,
    ).to_dict()
    data.update(patch)
    with pytest.raises(ValueError):
        validate_language_context(data)


@pytest.mark.parametrize(
    "section", ["pending_questions", "question_history", "outgoing_messages"]
)
def test_checkpoint_rejects_wrong_profile_before_mutation(section):
    agent = DigitalBeing(name="LanguageAtomic9A1")
    context = agent.social_attribution.resolve_language("Привет").to_dict()
    agent.user_interaction.ask_user("Вопрос?", cycle=1)
    state = build_state_from_agent(agent)
    interaction = state["user_interaction"]
    if section == "question_history":
        interaction[section] = [
            {
                "question": "Вопрос?",
                "answer": "Ответ",
                "context": "test",
                "cycle": 1,
                "language_context": deepcopy(context),
            }
        ]
    elif section == "outgoing_messages":
        interaction[section] = [
            {
                "id": "message-1",
                "sender": "agent",
                "content": "Ответ",
                "cycle": 1,
                "language_context": deepcopy(context),
            }
        ]
    interaction[section][0]["language_context"]["profile_id"] = "another-profile"
    state["energy"] = 0.123
    before = build_state_from_agent(agent)

    with pytest.raises(ValueError, match=rf"{section}\[0\]\.language_context"):
        apply_state_to_agent(agent, state)

    assert agent.energy == before["energy"]
    assert agent.social_attribution.to_dict() == before["social_attribution"]


@pytest.mark.parametrize(
    "scenario", DEFERRED_SCENARIOS, ids=lambda item: item["scenario_id"]
)
def test_deferred_english_fixtures_context_only_repeatable(scenario, monkeypatch):
    def blocked_network(*args, **kwargs):
        raise AssertionError("9A-1 context-only tests must remain offline")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    _, first = _run_context_scenario(scenario)
    _, second = _run_context_scenario(scenario)

    assert first == second
    assert all(record["response_language"] == "ru" for record in first)


def test_exactly_twelve_deferred_fixtures_are_now_context_checked():
    assert len(DEFERRED_SCENARIOS) == 12
    assert {scenario["scenario_id"] for scenario in DEFERRED_SCENARIOS} == {
        "en_p_switch_01",
        "en_p_switch_02",
        "en_p_profiles",
        "en_p_restart",
        "en_p_legacy",
        "en_p_ui_locale",
        "en_h_switch_01",
        "en_h_switch_02",
        "en_h_profiles",
        "en_h_restart",
        "en_h_legacy",
        "en_h_ui_locale",
    }
