"""Этап 1: профили собеседников, явное знакомство и restart-контур."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.event_bus import Events
from src.core.social_registry import SocialRegistry, validate_social_registry


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(name="SocialRegistryTest"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


async def _say(runner, text):
    await runner._on_user_message(SimpleNamespace(data={"text": text}))


def _replies(bus):
    return [
        str(data.get("content") or "")
        for name, data in bus.published
        if name == Events.AGENT_MESSAGE
    ]


def test_default_owner_is_current_and_verified():
    registry = SocialRegistry()

    owner = registry.current_profile()
    assert registry.owner_profile_id == registry.current_profile_id
    assert owner["kind"] == "local_owner"
    assert owner["identity_status"] == "verified"
    assert owner["introduced_by"] is None
    validate_social_registry(registry.to_dict())


@pytest.mark.asyncio
async def test_two_people_on_one_channel_have_distinct_profiles():
    agent, runner, bus = _make_runner()

    await _say(runner, "Я Глеб")
    owner_id = agent.social_registry.current_profile_id
    await _say(runner, "Я не Глеб, а его друг Миша")
    guest = agent.social_registry.current_profile()

    assert guest["profile_id"] != owner_id
    assert guest["kind"] == "local_person"
    assert guest["identity_status"] == "self_declared"
    assert guest["display_name"] == "Миша"
    assert guest["introduced_by"] == owner_id
    assert agent.social_registry.owner_profile_id == owner_id
    assert agent.social_registry.get_profile(owner_id)["display_name"] == "Глеб"
    assert any("Приятно познакомиться, Миша" in text for text in _replies(bus))
    validate_social_registry(agent.social_registry.to_dict())


@pytest.mark.asyncio
async def test_introduction_is_not_observed_as_previous_user(monkeypatch):
    agent, runner, _bus = _make_runner()
    observe_model = Mock()
    monkeypatch.setattr(agent.user_model, "observe", observe_model)
    observe_social = Mock()
    monkeypatch.setattr(
        "src.core.life_systems_bridge.observe_user_message", observe_social
    )

    await _say(runner, "Я не Глеб, а его друг Миша")

    observe_model.assert_not_called()
    observe_social.assert_not_called()
    history = agent.user_interaction.message_history
    assert history[-2]["content"] == "Я не Глеб, а его друг Миша"
    assert history[-1]["context"] == "social_introduction"


@pytest.mark.asyncio
async def test_unknown_guest_is_asked_then_completes_introduction():
    agent, runner, bus = _make_runner()
    owner_id = agent.social_registry.owner_profile_id

    await _say(runner, "Я друг Глеба")
    unknown = agent.social_registry.current_profile()
    assert unknown["kind"] == "unknown"
    assert unknown["display_name"] == ""
    assert unknown["identity_status"] == "unknown"
    assert "С кем я сейчас разговариваю?" in _replies(bus)[-1]

    await _say(runner, "Меня зовут Миша")
    named = agent.social_registry.current_profile()
    assert named["profile_id"] == unknown["profile_id"]
    assert named["kind"] == "local_person"
    assert named["display_name"] == "Миша"
    assert named["identity_status"] == "self_declared"
    assert agent.social_registry.owner_profile_id == owner_id


@pytest.mark.asyncio
async def test_name_only_does_not_interrupt_pending_or_naming():
    agent, runner, _bus = _make_runner()
    owner_id = agent.social_registry.current_profile_id
    agent.user_interaction.ask_user("Что для тебя важно?", context="test", cycle=1)

    await _say(runner, "Меня зовут Миша")
    assert agent.social_registry.current_profile_id == owner_id
    assert agent.social_registry.current_profile()["display_name"] == ""

    agent.user_interaction.pending_questions.clear()
    agent.start_naming_dialogue(cycle=2)
    await _say(runner, "Меня зовут Миша")
    assert agent.social_registry.current_profile_id == owner_id
    assert agent.social_registry.current_profile()["display_name"] == ""


@pytest.mark.asyncio
async def test_style_and_ordinary_message_do_not_switch_profile():
    agent, runner, _bus = _make_runner()
    before = agent.social_registry.current_profile_id

    await _say(runner, "Привет! Я рядом и сегодня пишу иначе.")
    await _say(runner, "Я рад тебя видеть")
    await _say(runner, "Я рад")
    await _say(runner, "Я сегодня работаю")

    assert agent.social_registry.current_profile_id == before
    assert agent.social_registry.current_profile()["display_name"] == ""
    assert len(agent.social_registry.profiles) == 1
    assert agent.user_interaction.get_last_user_message_cycle() == agent.cycle_count


def test_restart_preserves_profiles_current_speaker_and_legacy_models():
    source, _runner, _bus = _make_runner("SocialSource")
    source.social_registry.complete_introduction("Глеб", cycle=1)
    source.social_registry.create_local_person("Миша", cycle=2)
    source.social_attribution.sync_active_profile()
    source.user_model.observe("Я люблю чай", cycle=2)
    state = build_state_from_agent(source)

    restored, _runner, _bus = _make_runner("SocialRestored")
    apply_state_to_agent(restored, deepcopy(state))

    assert restored.social_registry.to_dict() == source.social_registry.to_dict()
    assert restored.social_registry.current_profile()["display_name"] == "Миша"
    assert restored.user_model.to_dict() == source.user_model.to_dict()
    assert restored.dialogue_learning.to_dict() == source.dialogue_learning.to_dict()


def test_legacy_checkpoint_keeps_new_default_owner():
    source, _runner, _bus = _make_runner("LegacySource")
    state = build_state_from_agent(source)
    state.pop("social_registry")
    state.pop("social_attribution")
    restored, _runner, _bus = _make_runner("LegacyRestored")
    default = restored.social_registry.to_dict()

    apply_state_to_agent(restored, state)

    assert restored.social_registry.to_dict() == default
    assert restored.social_registry.current_profile()["kind"] == "local_owner"


def test_corrupted_registry_is_rejected_before_agent_mutation():
    agent, _runner, _bus = _make_runner("CorruptGuard")
    state = build_state_from_agent(agent)
    state["energy"] = 1.0
    state["social_registry"]["current_profile_id"] = "missing"
    before = agent.social_registry.to_dict()

    with pytest.raises(ValueError, match="current_profile_id"):
        apply_state_to_agent(agent, state)

    assert agent.energy != 1.0
    assert agent.social_registry.to_dict() == before


@pytest.mark.parametrize(
    "mutation, path",
    [
        (lambda data: data.update(owner_profile_id="bad"), "owner_profile_id"),
        (
            lambda data: data["profiles"][data["owner_profile_id"]].update(
                last_seen_cycle=-1
            ),
            "last_seen_cycle",
        ),
        (
            lambda data: data["profiles"][data["owner_profile_id"]].update(
                introduced_by="00000000-0000-0000-0000-000000000000"
            ),
            "introduced_by",
        ),
    ],
)
def test_registry_validation_reports_field_path(mutation, path):
    data = SocialRegistry().to_dict()
    mutation(data)

    with pytest.raises(ValueError, match=path):
        validate_social_registry(data)
