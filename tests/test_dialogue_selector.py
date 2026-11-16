"""P2, этап 4: детерминированный выбор стратегии для непонятных реплик."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.dialogue_learning import DialogueLearning
from src.core.dialogue_strategies import (
    STRATEGY_OUTCOME_HALF_LIFE_CYCLES,
    DialogueStrategyMemory,
)
from src.core.event_bus import Events


PHRASE = "совсем другая непонятная фраза"


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(name="Selector"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


async def _say(runner, text):
    await runner._on_user_message(SimpleNamespace(data={"text": text}))


def _replies(bus):
    return [
        dict(data or {}) for name, data in bus.published if name == Events.AGENT_MESSAGE
    ]


def _questions(bus):
    return [
        dict(data or {})
        for name, data in bus.published
        if name == Events.AGENT_QUESTION
    ]


def _record(memory, response_id, feedback="opposition", cycle=0, weight=1.0):
    memory.register_response(response_id, "learning_question", "unknown", cycle)
    return memory.apply_feedback(response_id, feedback, cycle, testimony_weight=weight)


def _seed_oppositions(memory, count=3, weight=1.0):
    for index in range(count):
        result = _record(memory, f"question:{index}", weight=weight)
        assert result["status"] == "recorded"


def test_empty_memory_and_less_than_three_oppositions_keep_baseline():
    memory = DialogueStrategyMemory()
    assert memory.select_strategy("unknown", 0) == {
        "strategy_id": "learning_question",
        "reason": "baseline",
    }
    for index in range(2):
        _record(memory, f"question:{index}")
        assert memory.select_strategy("unknown", 0)["strategy_id"] == (
            "learning_question"
        )


def test_three_unique_oppositions_select_listening():
    memory = DialogueStrategyMemory()
    _seed_oppositions(memory)
    assert memory.select_strategy("unknown", 0) == {
        "strategy_id": "unknown_listen",
        "reason": "weighted_feedback",
    }


def test_duplicate_response_id_does_not_raise_response_count():
    memory = DialogueStrategyMemory()
    _record(memory, "question:1")
    duplicate = _record(memory, "question:1")
    assert duplicate["status"] == "duplicate"
    signal = memory.signal_at("unknown", "learning_question", 0)
    assert signal["response_count"] == 1
    assert memory.select_strategy("unknown", 0)["strategy_id"] == "learning_question"


def test_low_testimony_weight_does_not_cross_signal_threshold():
    memory = DialogueStrategyMemory()
    _seed_oppositions(memory, weight=0.2)
    signal = memory.signal_at("unknown", "learning_question", 0)
    assert signal["response_count"] == 3
    assert signal["difference"] == pytest.approx(0.6)
    assert memory.select_strategy("unknown", 0)["strategy_id"] == "learning_question"


def test_support_reduces_active_opposition_signal():
    memory = DialogueStrategyMemory()
    _seed_oppositions(memory, weight=0.8)
    before = memory.signal_at("unknown", "learning_question", 0)
    _record(memory, "question:support-1", feedback="support")
    after = memory.signal_at("unknown", "learning_question", 0)
    assert after["difference"] == pytest.approx(before["difference"] - 1.0)
    assert memory.select_strategy("unknown", 0)["strategy_id"] == "unknown_listen"

    _record(memory, "question:support-2", feedback="support")
    assert memory.select_strategy("unknown", 0)["strategy_id"] == "learning_question"


def test_decay_returns_to_learning_question():
    memory = DialogueStrategyMemory()
    _seed_oppositions(memory)
    later = 2 * STRATEGY_OUTCOME_HALF_LIFE_CYCLES
    assert memory.select_strategy("unknown", later) == {
        "strategy_id": "learning_question",
        "reason": "decayed_return",
    }


def test_confirmed_preferences_override_automatic_choice():
    memory = DialogueStrategyMemory()
    memory.set_preference("unknown", "unknown_listen", 0)
    assert memory.select_strategy("unknown", 0) == {
        "strategy_id": "unknown_listen",
        "reason": "confirmed_preference",
    }

    _seed_oppositions(memory)
    memory.set_preference("unknown", "learning_question", 1)
    assert memory.select_strategy("unknown", 1) == {
        "strategy_id": "learning_question",
        "reason": "confirmed_preference",
    }


def test_selector_is_repeatable_and_does_not_mutate_memory():
    memory = DialogueStrategyMemory()
    _seed_oppositions(memory)
    memory.register_response("message:1", "unknown_listen", "unknown", 0)
    before = deepcopy(memory.to_dict())
    first = memory.select_strategy("unknown", 10)
    second = memory.select_strategy("unknown", 10)
    assert first == second
    assert memory.to_dict() == before


@pytest.mark.parametrize(
    "context,cycle",
    [
        ("social", 0),
        (None, 0),
        ("unknown", -1),
        ("unknown", True),
        ("unknown", 1.5),
        ("unknown", "1"),
    ],
)
def test_selector_rejects_invalid_context_and_cycle(context, cycle):
    memory = DialogueStrategyMemory()
    with pytest.raises(ValueError):
        memory.select_strategy(context, cycle)


@pytest.mark.asyncio
async def test_three_oppositions_deliver_listen_and_register_real_message_id():
    agent, runner, bus = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    _seed_oppositions(memory)
    agent.cycle_count = 10

    await _say(runner, PHRASE)

    reply = _replies(bus)[-1]
    assert reply["context"] == "unknown_listen"
    assert reply["id"]
    assert agent.user_interaction.get_pending_question() is None
    assert _questions(bus) == []
    assert memory.feedback_target == {
        "response_id": reply["id"],
        "strategy_id": "unknown_listen",
        "context_key": "unknown",
        "cycle": 10,
    }


@pytest.mark.asyncio
async def test_feedback_after_listen_is_attributed_to_shown_strategy():
    agent, runner, _ = _make_runner()
    attachment = agent.attachment.get_or_create("user")
    attachment.trust = 1.0
    attachment.intimacy = 1.0
    memory = agent.dialogue_learning.strategy_memory
    _seed_oppositions(memory)
    await _say(runner, PHRASE)
    response_id = memory.feedback_target["response_id"]
    agent.cycle_count += 1

    await _say(runner, "не то")

    outcome = memory.outcomes["unknown"]["unknown_listen"]
    assert outcome["opposition"] == pytest.approx(1.0)
    assert outcome["response_count"] == 1
    assert outcome["recent_response_ids"] == [response_id]
    assert memory.feedback_target is None


@pytest.mark.asyncio
async def test_question_preference_overrides_feedback_in_real_route():
    agent, runner, _ = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    _seed_oppositions(memory)
    memory.set_preference("unknown", "learning_question", 1)
    agent.cycle_count = 10

    await _say(runner, PHRASE)

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert DialogueLearning.is_proposal_context(pending["context"])
    assert memory.feedback_target["strategy_id"] == "learning_question"


@pytest.mark.asyncio
async def test_decayed_signal_asks_learning_question_again():
    agent, runner, _ = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    _seed_oppositions(memory)
    agent.cycle_count = 2 * STRATEGY_OUTCOME_HALF_LIFE_CYCLES

    await _say(runner, PHRASE)

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert DialogueLearning.is_proposal_context(pending["context"])
    assert memory.feedback_target["strategy_id"] == "learning_question"


@pytest.mark.asyncio
async def test_missing_candidate_keeps_legacy_unknown_reply():
    agent, runner, bus = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    _seed_oppositions(memory)
    agent.cycle_count = 10
    agent.dialogue_learning.mark_proposed(agent.cycle_count)

    await _say(runner, PHRASE)

    assert _replies(bus)[-1]["context"] == "unknown_reply"
    assert memory.feedback_target is None


@pytest.mark.asyncio
async def test_suppressed_phrase_keeps_legacy_unknown_reply():
    agent, runner, bus = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    _seed_oppositions(memory)
    agent.dialogue_learning.suppressed[PHRASE] = 0
    agent.cycle_count = 10

    await _say(runner, PHRASE)

    assert _replies(bus)[-1]["context"] == "unknown_reply"
    assert memory.feedback_target is None


@pytest.mark.asyncio
async def test_missing_delivery_id_creates_no_feedback_target():
    agent, runner, _ = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    _seed_oppositions(memory)
    agent.user_interaction.send_reply = lambda *args, **kwargs: None
    agent.cycle_count = 10

    await _say(runner, PHRASE)

    assert memory.feedback_target is None
    assert agent.user_interaction.get_pending_question() is None


@pytest.mark.asyncio
async def test_listen_does_not_close_unrelated_pending_question():
    agent, runner, bus = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    _seed_oppositions(memory)
    unrelated = agent.user_interaction.ask_user(
        "Отдельный вопрос?", context="unrelated", cycle=0
    )
    assert unrelated["status"] == "queued"
    agent.cycle_count = 10
    questions_before = len(_questions(bus))

    await _say(runner, "что означает совершенно непонятная фраза?")

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert pending["id"] == unrelated["id"]
    assert pending["answered"] is False
    assert len(_questions(bus)) == questions_before
    assert _replies(bus)[-1]["context"] == "unknown_listen"
