"""P2, этап 3: подтверждаемые scoped preferences без адаптации выбора."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.dialogue_strategies import (
    build_preference_proposal,
    is_preference_context,
    parse_preference_decision,
    parse_preference_request,
    preference_from_context,
)
from src.core.event_bus import Events


LISTEN_REQUEST = "В таких случаях не задавай вопросов"
QUESTION_REQUEST = "В таких случаях спрашивай"
FORGET_REQUEST = "забудь правило для таких ответов"


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(name="Preference"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


async def _say(runner, text):
    await runner._on_user_message(SimpleNamespace(data={"text": text}))


def _last_reply(bus):
    replies = [
        dict(data or {}) for name, data in bus.published if name == Events.AGENT_MESSAGE
    ]
    return replies[-1] if replies else None


def _advance(agent):
    agent.cycle_count += 120


@pytest.mark.parametrize(
    "text,expected",
    [
        (LISTEN_REQUEST, "unknown_listen"),
        ("  в таких случаях спрашивай! ", "learning_question"),
        ("не задавай вопросов", None),
        ("в таких случаях не задавай вопросов?", None),
        ("в таких случаях не задавай вопросов и слушай", None),
        (None, None),
    ],
)
def test_preference_request_is_exact_and_scoped(text, expected):
    assert parse_preference_request(text) == expected


def test_preference_proposal_context_roundtrip():
    for action, strategy in (
        ("set", "unknown_listen"),
        ("set", "learning_question"),
        ("forget", "unknown_listen"),
    ):
        proposal = build_preference_proposal(strategy, action)
        assert is_preference_context(proposal["context"])
        assert preference_from_context(proposal["context"]) == (action, strategy)
        assert "да" in proposal["question"]
        assert "нет" in proposal["question"]
    with pytest.raises(ValueError):
        build_preference_proposal("unknown", "set")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("да", True),
        ("подтверждаю", True),
        ("верно", True),
        ("согласен", True),
        ("согласна", True),
        ("нет", False),
        ("отмена", False),
        ("не учи", False),
        ("возможно", None),
        ("да?", None),
        ("1", None),
    ],
)
def test_preference_decision_requires_explicit_answer(text, expected):
    assert parse_preference_decision(text) == expected


@pytest.mark.asyncio
async def test_preference_request_alone_saves_nothing():
    agent, runner, _ = _make_runner()

    await _say(runner, LISTEN_REQUEST)

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert preference_from_context(pending["context"]) == ("set", "unknown_listen")
    assert agent.dialogue_learning.strategy_memory.preferences == {}


@pytest.mark.asyncio
async def test_confirmed_preference_is_saved_only_for_unknown():
    agent, runner, bus = _make_runner()
    methods_before = deepcopy(getattr(agent, "_method_preferences", {}))
    await _say(runner, LISTEN_REQUEST)
    _advance(agent)

    await _say(runner, "да")

    memory = agent.dialogue_learning.strategy_memory
    assert memory.preference_for("unknown") == {
        "strategy": "unknown_listen",
        "evidence": "user_taught",
        "cycle": agent.cycle_count,
    }
    assert memory.preference_for("social") is None
    assert getattr(agent, "_method_preferences", {}) == methods_before
    assert agent.user_interaction.get_pending_question() is None
    assert _last_reply(bus)["context"] == "dialogue_preference"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["нет", "отмена", "не учи", "возможно", "1"])
async def test_rejected_or_unclear_confirmation_changes_nothing(answer):
    agent, runner, _ = _make_runner()
    await _say(runner, LISTEN_REQUEST)
    _advance(agent)

    await _say(runner, answer)

    assert agent.dialogue_learning.strategy_memory.preferences == {}
    assert agent.user_interaction.get_pending_question() is None


@pytest.mark.asyncio
async def test_correction_requires_and_uses_a_new_confirmation():
    agent, runner, _ = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    await _say(runner, LISTEN_REQUEST)
    _advance(agent)
    await _say(runner, "да")
    assert memory.preference_for("unknown")["strategy"] == "unknown_listen"

    _advance(agent)
    await _say(runner, QUESTION_REQUEST)
    assert memory.preference_for("unknown")["strategy"] == "unknown_listen"
    pending = agent.user_interaction.get_pending_question()
    assert preference_from_context(pending["context"]) == ("set", "learning_question")

    _advance(agent)
    await _say(runner, "подтверждаю")
    assert memory.preference_for("unknown")["strategy"] == "learning_question"


@pytest.mark.asyncio
async def test_forget_requires_confirmation_and_preserves_outcomes():
    agent, runner, _ = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    memory.set_preference("unknown", "unknown_listen", 0)
    memory.register_response("message:1", "unknown_listen", "unknown", 0)
    memory.apply_feedback("message:1", "support", 0)
    outcomes_before = deepcopy(memory.outcomes)

    await _say(runner, FORGET_REQUEST)
    assert memory.preference_for("unknown") is not None
    pending = agent.user_interaction.get_pending_question()
    assert preference_from_context(pending["context"]) == ("forget", "unknown_listen")
    _advance(agent)
    await _say(runner, "нет")
    assert memory.preference_for("unknown") is not None

    _advance(agent)
    await _say(runner, FORGET_REQUEST)
    _advance(agent)
    await _say(runner, "да")

    assert memory.preference_for("unknown") is None
    assert memory.outcomes == outcomes_before


@pytest.mark.asyncio
async def test_forget_without_existing_rule_asks_no_question():
    agent, runner, bus = _make_runner()

    await _say(runner, FORGET_REQUEST)

    assert agent.user_interaction.get_pending_question() is None
    assert "забывать нечего" in _last_reply(bus)["content"]


@pytest.mark.asyncio
async def test_failed_confirmation_delivery_does_not_save_preference():
    agent, runner, bus = _make_runner()
    agent.user_interaction.can_ask_question = lambda cycle, respect_affect=True: False

    await _say(runner, LISTEN_REQUEST)

    assert agent.dialogue_learning.strategy_memory.preferences == {}
    assert agent.user_interaction.get_pending_question() is None
    assert "Правило не изменено" in _last_reply(bus)["content"]


@pytest.mark.asyncio
async def test_saved_preference_adapts_unknown_choice():
    agent, runner, bus = _make_runner()
    await _say(runner, LISTEN_REQUEST)
    _advance(agent)
    await _say(runner, "да")
    assert agent.dialogue_learning.strategy_memory.preference_for("unknown") is not None

    _advance(agent)
    await _say(runner, "новая непонятная фраза")

    assert agent.user_interaction.get_pending_question() is None
    memory = agent.dialogue_learning.strategy_memory
    assert memory.feedback_target["strategy_id"] == "unknown_listen"
    assert _last_reply(bus)["context"] == "unknown_listen"
