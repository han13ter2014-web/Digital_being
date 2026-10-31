"""Понятный разговор: без повторов, служебных кодов и выдуманных связей."""

import asyncio
import queue

from src.core.agent_runner import AgentRunner
from src.core.subsystems.proactive_communication import ProactiveCommunication


class Concept:
    def __init__(self, connections=None):
        self.connections = dict(connections or {})


class MentalModels:
    def __init__(self, concepts):
        self.concepts = concepts


class Agent:
    def __init__(self, concepts):
        self.mental_models = MentalModels(concepts)


def test_same_autonomous_thought_is_not_repeated():
    runner = AgentRunner.__new__(AgentRunner)
    runner._recent_thoughts = {}

    assert runner._should_publish_thought("Я думаю о времени", 10) is True
    assert runner._should_publish_thought("  я   думаю о времени ", 11) is False
    assert runner._should_publish_thought("Другая мысль", 12) is True


def test_thought_may_return_after_quiet_window():
    runner = AgentRunner.__new__(AgentRunner)
    runner._recent_thoughts = {}
    assert runner._should_publish_thought("Одна мысль", 0) is True
    assert runner._should_publish_thought("Одна мысль", 39) is False
    assert runner._should_publish_thought("Одна мысль", 40) is True


def test_curiosity_uses_only_recorded_connection():
    proactive = ProactiveCommunication("Alpha")
    agent = Agent({
        "время": Concept({"память": 0.7}),
        "память": Concept(),
        "случайная": Concept(),
    })
    message = proactive._compose_curiosity_message(agent, 100)
    assert message is not None
    assert "время" in message["content"]
    assert "память" in message["content"]
    # Второй концепт — только тот, с которым связь действительно записана.
    assert "случайная" not in message["content"]


def test_no_recorded_connection_means_no_claim():
    proactive = ProactiveCommunication("Alpha")
    agent = Agent({"время": Concept(), "память": Concept()})
    assert proactive._compose_curiosity_message(agent, 100) is None
    assert proactive._found_interesting_link(agent) is False


def test_curiosity_does_not_repeat_same_pair_while_other_links_exist():
    proactive = ProactiveCommunication("Alpha")
    agent = Agent({
        "а": Concept({"б": 0.5}),
        "б": Concept({"в": 0.5}),
        "в": Concept(),
    })
    first = proactive._compose_curiosity_message(agent, 1)["content"]
    second = proactive._compose_curiosity_message(agent, 2)["content"]
    assert first != second


def test_sharing_message_has_no_internal_metric():
    proactive = ProactiveCommunication("Alpha")
    agent = Agent({})
    agent.intelligence = 7
    message = proactive._compose_sharing_message(agent, 50)
    assert "интеллект" not in message["content"].lower()
    assert "7" not in message["content"]


def test_agent_question_has_no_service_code():
    from src.ui.chat_window import ChatWindow

    window = ChatWindow.__new__(ChatWindow)
    window.agent_name = "Омелла"
    window._incoming_queue = queue.Queue()

    asyncio.run(window._on_agent_question(type("E", (), {
        "data": {
            "id": "q-42",
            "priority": "high",
            "question": "Что для тебя важно?",
            "context": "",
        }
    })()))

    first = window._incoming_queue.get_nowait()
    text = first[1]
    assert "Омелла спрашивает" in text
    assert "#q-42" not in text
    assert "high" not in text
