"""Мосты памяти, доведение намерений и послеменный след диалога."""

import json
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.dialogue_acts import ACT_SOCIAL
from src.core.dialogue_learning import DialogueLearning
from src.core.event_bus import Events
from src.core.paths import data_path


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(name="Нова"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


async def _say(runner, text):
    await runner._on_user_message(SimpleNamespace(data={"text": text}))


def _events(bus, event_name):
    return [dict(data or {}) for name, data in bus.published if name == event_name]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic,question,expected",
    [
        ("изучать", "Что такое изучать?", "получать новый опыт"),
        ("изучение", "Что значит изучать?", "получать новый опыт"),
        ("выбор", "Что такое выбор?", "принятие одной из возможностей"),
        ("Питон", "Что ты знаешь про питон?", "язык программирования"),
    ],
)
async def test_user_definition_answers_later_question(topic, question, expected):
    agent, runner, bus = _make_runner()
    agent.record_user_answer(topic, f"{topic} — это {expected}", cycle=7)

    await _say(runner, question)

    replies = _events(bus, Events.AGENT_MESSAGE)
    assert replies[-1]["context"] == "known_topic"
    assert expected in replies[-1]["content"]
    assert "от тебя" in replies[-1]["content"]
    assert all(reply["context"] != "unknown_reply" for reply in replies)


@pytest.mark.asyncio
async def test_known_definition_answers_without_concept_node():
    agent, runner, bus = _make_runner()
    agent._known_definitions["выбор"] = "принятие одной из возможностей"

    await _say(runner, "Что такое выбор?")

    reply = _events(bus, Events.AGENT_MESSAGE)[-1]
    assert reply["context"] == "known_topic"
    assert "принятие одной из возможностей" in reply["content"]


@pytest.mark.asyncio
async def test_name_fact_does_not_invent_date_or_reason():
    agent, runner, bus = _make_runner()
    agent.naming_dialogue._name_history.append(
        {
            "old_name": "Прежнее имя",
            "new_name": "Нова",
            "cycle": 8123,
            "source": "rename",
        }
    )

    await _say(runner, "Ты вчера выбрала имя Нова. Помнишь, почему?")

    reply = _events(bus, Events.AGENT_MESSAGE)[-1]
    assert reply["context"] == "persistent_fact"
    assert "моё имя — Нова" in reply["content"]
    assert "цикл 8123" in reply["content"]
    assert "Календарная дата выбора не сохранена" in reply["content"]
    assert "не стану её придумывать" in reply["content"]


@pytest.mark.asyncio
async def test_user_facts_answer_from_persistent_model():
    agent, runner, bus = _make_runner()
    agent.user_model.observe("Я работаю по ночам", cycle=10)

    await _say(runner, "Что ты помнишь обо мне?")

    reply = _events(bus, Events.AGENT_MESSAGE)[-1]
    assert reply["context"] == "persistent_fact"
    assert "я работаю по ночам" in reply["content"]


@pytest.mark.asyncio
async def test_capabilities_request_gets_enumerated_answer():
    agent, runner, bus = _make_runner()

    await _say(runner, "Что ты умеешь из просьб?")

    reply = _events(bus, Events.AGENT_MESSAGE)[-1]
    assert reply["context"] == "persistent_fact"
    assert "Из просьб я умею:" in reply["content"]
    assert "запомнить" in reply["content"]
    assert reply["context"] != "unknown_reply"


@pytest.mark.asyncio
async def test_first_unknown_asks_category_and_answer_one_still_teaches():
    agent, runner, bus = _make_runner()
    phrase = "совсем незнакомая реплика"

    await _say(runner, phrase)

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert DialogueLearning.is_proposal_context(pending["context"])
    assert "1 — обычный разговор" in pending["question"]
    assert _events(bus, Events.AGENT_MESSAGE) == []

    await _say(runner, "1")

    assert agent.dialogue_learning.learned[phrase]["act"] == ACT_SOCIAL
    reply = _events(bus, Events.AGENT_MESSAGE)[-1]
    assert reply["context"] == "dialogue_learning"
    assert "Поняла" in reply["content"]
    assert agent.user_interaction.get_pending_question() is None


class FakeSearcher:
    is_enabled = True

    def __init__(self):
        self.queries = []

    def search(self, target):
        self.queries.append(target)
        return {
            "found": True,
            "title": "Слои нейросети",
            "extract": (
                "Слои нейросети преобразуют представления данных и передают "
                "результат следующему слою, образуя последовательную модель."
            ),
        }


def test_three_web_searches_use_active_intention_target():
    agent = DigitalBeing(name="Нова")
    searcher = FakeSearcher()
    agent.web_searcher = searcher
    agent._pick_exploration_target = lambda: "посторонняя тема"
    intention = {"params": {"target": "как связаны слои нейросети"}}

    for _ in range(3):
        agent.act("web_search", intention=intention)

    assert searcher.queries == ["как связаны слои нейросети"] * 3


def test_web_search_without_intention_keeps_exploration_fallback():
    agent = DigitalBeing(name="Нова")
    searcher = FakeSearcher()
    agent.web_searcher = searcher
    agent._pick_exploration_target = lambda: "свободная тема"

    result = agent._act_web_search()

    assert result["target"] == "свободная тема"
    assert searcher.queries == ["свободная тема"]


@pytest.mark.asyncio
async def test_dialogue_snapshot_contains_both_sides_and_survives_new_runner():
    agent, runner, bus = _make_runner()
    path = data_path("logs", "dialogue_cycles.jsonl")

    await _say(runner, "Что ты умеешь из просьб?")
    runner._save_dialogue_cycle_snapshot()
    # Новый runner не очищает журнал: прежний сеанс остаётся доступен.
    new_runner = AgentRunner(agent, bus)
    new_runner._save_dialogue_cycle_snapshot()

    with open(path, encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    assert len(records) >= 2
    messages = records[-2]["dialogue"]["messages"]
    assert any(
        entry["sender"] == "user" and entry["content"] == "Что ты умеешь из просьб?"
        for entry in messages
    )
    assert any(
        entry["sender"] == "agent" and "Из просьб я умею:" in entry["content"]
        for entry in messages
    )
    assert records[-1]["schema_version"] == 1


@pytest.mark.asyncio
async def test_tick_once_automatically_appends_dialogue_snapshot():
    agent, runner, bus = _make_runner()
    path = data_path("logs", "dialogue_cycles.jsonl")
    await _say(runner, "Что ты умеешь из просьб?")
    with open(path, encoding="utf-8") as stream:
        before = sum(1 for line in stream if line.strip())

    from src.core.agent_runner import PersistentMessageQueue

    runner._pending_user_messages = PersistentMessageQueue(agent)
    runner._next_stimulus = lambda: None
    runner._rest_tick = lambda: None
    await runner._tick_once(wait_for_user=False)

    with open(path, encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    assert len(records) == before + 1
    messages = records[-1]["dialogue"]["messages"]
    assert any(entry["sender"] == "user" for entry in messages)
    assert any(entry["sender"] == "agent" for entry in messages)


def test_share_message_uses_feminine_self_description():
    agent = DigitalBeing(name="Нова")
    agent.record_user_answer("выбор", "выбор — это принятие возможности", cycle=1)
    node = agent.mental_models.concepts["выбор"]
    node.definition_hypothesis = "выбор — принятие одной из возможностей"

    message = agent._compose_share_message()

    assert message.startswith("Я разобралась")
    assert "разобрался" not in message


def test_share_failure_uses_feminine_self_description():
    agent = DigitalBeing(name="Нова")
    agent.record_user_answer("выбор", "выбор — это принятие возможности", cycle=1)
    node = agent.mental_models.concepts["выбор"]
    node.definition_hypothesis = "выбор — принятие одной из возможностей"

    def fail_send(**kwargs):
        raise RuntimeError("сбой")

    agent.user_interaction.send_message = fail_send
    result = agent._act_communicate()

    assert result["text"] == "Ответ: хотела рассказать, но не смогла: сбой"
