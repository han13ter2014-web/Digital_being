"""P2, этап 2: доставка target и явный feedback без адаптации выбора."""

from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.dialogue_learning import DialogueLearning
from src.core.dialogue_strategies import parse_feedback
from src.core.event_bus import Events


PHRASE = "ну ты понимаешь о чём я"


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(name="Feedback"):
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


@pytest.mark.parametrize(
    "text,expected",
    [
        ("так понятно", "support"),
        ("  Теперь понятно! ", "support"),
        ("так лучше", "support"),
        ("не то", "opposition"),
        ("ты меня не поняла", "opposition"),
        ("ты меня не понял.", "opposition"),
        ("не задавай таких вопросов", "opposition"),
        ("не надо таких вопросов", "opposition"),
    ],
)
def test_exact_feedback_forms(text, expected):
    assert parse_feedback(text, "learning_question") == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "спасибо",
        "1",
        "2",
        "3",
        "4",
        "отмена",
        "не то?",
        "не то, продолжай",
        "она сказала не то",
        "не задавай вопросов",
    ],
)
def test_feedback_parser_rejects_inference_and_compound_forms(text):
    assert parse_feedback(text, "learning_question") is None


def test_question_specific_opposition_does_not_apply_to_listen_strategy():
    assert parse_feedback("не задавай таких вопросов", "unknown_listen") is None
    assert parse_feedback("не то", "unknown_listen") == "opposition"


@pytest.mark.asyncio
async def test_published_learning_question_registers_exact_target():
    agent, runner, _ = _make_runner()
    agent.cycle_count = 7

    await _say(runner, PHRASE)

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert DialogueLearning.is_proposal_context(pending["context"])
    assert agent.dialogue_learning.strategy_memory.feedback_target == {
        "response_id": pending["response_id"],
        "strategy_id": "learning_question",
        "context_key": "unknown",
        "cycle": 7,
    }
    assert agent.dialogue_learning.strategy_memory.outcomes == {}


@pytest.mark.asyncio
async def test_failed_question_delivery_creates_no_target():
    agent, runner, bus = _make_runner()
    agent.user_interaction.can_ask_question = lambda cycle, respect_affect=True: False

    await _say(runner, PHRASE)

    assert agent.user_interaction.get_pending_question() is None
    assert agent.dialogue_learning.strategy_memory.feedback_target is None
    assert _last_reply(bus)["context"] == "unknown_reply"


@pytest.mark.asyncio
async def test_feedback_door_records_attachment_weight_and_clears_target():
    agent, runner, bus = _make_runner()
    attachment = agent.attachment.get_or_create("user")
    attachment.trust = 1.0
    attachment.intimacy = 1.0
    memory = agent.dialogue_learning.strategy_memory
    memory.register_response("message:7", "unknown_listen", "unknown", 0)

    await _say(runner, "так лучше")

    outcome = memory.outcomes["unknown"]["unknown_listen"]
    assert outcome["support"] == pytest.approx(1.0)
    assert outcome["opposition"] == 0.0
    assert outcome["response_count"] == 1
    assert outcome["recent_response_ids"] == ["message:7"]
    assert memory.feedback_target is None
    assert _last_reply(bus)["context"] == "dialogue_feedback"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["спасибо", "1", "2", "3", "4"])
async def test_non_feedback_reply_clears_target_without_outcome(text):
    agent, runner, _ = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    memory.register_response("message:7", "unknown_listen", "unknown", 0)

    await _say(runner, text)

    target = memory.feedback_target
    assert target is None or target["response_id"] != "message:7"
    assert memory.outcomes == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,feedback",
    [("не то", "opposition"), ("так понятно", "support")],
)
async def test_learning_pending_records_exact_feedback_without_teaching(text, feedback):
    agent, runner, bus = _make_runner()
    await _say(runner, PHRASE)
    memory = agent.dialogue_learning.strategy_memory
    pending = agent.user_interaction.get_pending_question()
    response_id = pending["response_id"]
    learned_before = dict(agent.dialogue_learning.learned)
    suppressed_before = dict(agent.dialogue_learning.suppressed)

    await _say(runner, text)

    assert agent.user_interaction.get_pending_question() is None
    assert memory.feedback_target is None
    outcome = memory.outcomes["unknown"]["learning_question"]
    assert outcome["response_count"] == 1
    assert outcome[feedback] > 0.0
    assert outcome["recent_response_ids"] == [response_id]
    assert agent.dialogue_learning.learned == learned_before
    assert agent.dialogue_learning.suppressed == suppressed_before
    assert _last_reply(bus)["context"] == "dialogue_learning"
    assert "оценку" in _last_reply(bus)["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["1", "2", "3", "4", "непонятный ответ"])
async def test_learning_pending_regular_answers_do_not_create_feedback(text):
    agent, runner, _ = _make_runner()
    await _say(runner, PHRASE)
    memory = agent.dialogue_learning.strategy_memory

    await _say(runner, text)

    assert agent.user_interaction.get_pending_question() is None
    assert memory.feedback_target is None
    assert memory.outcomes == {}


@pytest.mark.asyncio
async def test_real_question_feedback_pairs_switch_to_listening_with_unique_ids():
    agent, runner, bus = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    response_ids = []

    for index in range(3):
        agent.cycle_count += 1300 if index else 0
        await _say(runner, f"непонятная реплика регрессия {index}")
        pending = agent.user_interaction.get_pending_question()
        assert pending["id"] == 1
        response_ids.append(pending["response_id"])
        agent.cycle_count += 1
        await _say(runner, "не то")

    assert len(set(response_ids)) == 3
    outcome = memory.outcomes["unknown"]["learning_question"]
    assert outcome["response_count"] == 3
    assert set(outcome["recent_response_ids"]) == set(response_ids)

    agent.cycle_count += 1300
    await _say(runner, "четвёртая непонятная реплика регрессия")

    assert agent.user_interaction.get_pending_question() is None
    assert memory.feedback_target["strategy_id"] == "unknown_listen"
    assert _last_reply(bus)["context"] == "unknown_listen"


@pytest.mark.asyncio
async def test_three_opposition_outcomes_switch_to_listening():
    agent, runner, bus = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    for index in range(3):
        response_id = f"question:{index}"
        memory.register_response(response_id, "learning_question", "unknown", index)
        result = memory.apply_feedback(response_id, "opposition", index)
        assert result["status"] == "recorded"
    agent.cycle_count = 4

    await _say(runner, "совсем другая непонятная фраза")

    assert agent.user_interaction.get_pending_question() is None
    assert memory.feedback_target["strategy_id"] == "unknown_listen"
    assert _last_reply(bus)["context"] == "unknown_listen"
    assert not any(name == Events.AGENT_QUESTION for name, _ in bus.published)


@pytest.mark.asyncio
async def test_expired_target_is_not_attributed_by_feedback_door():
    agent, runner, _ = _make_runner()
    memory = agent.dialogue_learning.strategy_memory
    memory.register_response("message:7", "unknown_listen", "unknown", 0)
    agent.cycle_count = 51

    await _say(runner, "так понятно")

    assert memory.outcomes == {}
    target = memory.feedback_target
    assert target is None or target["response_id"] != "message:7"
