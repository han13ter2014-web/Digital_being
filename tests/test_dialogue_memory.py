"""Память диалога (участок «Собеседник-4»).

До этого этапа сущность повторялась: «поделиться знанием» отправляло
одну и ту же тему, а забота о молчащем человеке была шаблонной — без
памяти о том, о чём говорили в последний раз. Здесь проверяются:
дедуп рассказанных тем (_shared_topics), первое реальное использование
get_history() и конкретное «скучаю» в care-сообщении с промисом.
"""

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.subsystems.proactive_communication import ProactiveCommunication
from src.core.user_model import UserModel
from src.perception.user_interaction import UserInteraction


def _agent_with_knowledge(name="DM", topic="число"):
    """Агент с одной концепцией, по которой есть своя формулировка."""
    agent = DigitalBeing(name=name)
    for known in list(agent.mental_models.concepts):
        if agent._is_learnable(known):
            del agent.mental_models.concepts[known]
    node = agent.mental_models.encounter_concept(topic, "стимул", "встреча")
    node.definition_hypothesis = (
        "Число — это понятие количества, которое используется в счёте."
    )
    return agent


# ============================================================
# Дедуп рассказанного
# ============================================================

def test_share_message_is_not_repeated():
    agent = _agent_with_knowledge()

    first = agent._compose_share_message(record=True)
    assert "«число»" in first

    # Уже рассказано — повторять нечего.
    assert agent._compose_share_message(record=True) == ""
    assert agent._shared_topics == {"число": agent.cycle_count}


def test_gate_check_does_not_burn_topic():
    agent = _agent_with_knowledge()

    probe = agent._compose_share_message()
    assert "«число»" in probe
    # Проверка без записи не помечает тему рассказанной.
    assert agent._shared_topics == {}
    assert agent._compose_share_message() == probe


def test_act_communicate_sends_topic_once():
    agent = _agent_with_knowledge()
    ui = agent.user_interaction

    result = agent._act_communicate()
    assert "рассказал человеку" in result["text"]
    assert ui.message_history
    assert "«число»" in ui.message_history[-1]["content"]

    repeat = agent._act_communicate()
    assert "нечего рассказать" in repeat["text"]
    assert len(ui.message_history) == 1


def test_new_topic_is_shared_after_first():
    agent = _agent_with_knowledge()

    assert "«число»" in agent._compose_share_message(record=True)

    node = agent.mental_models.encounter_concept("пространство", "стимул", "встреча")
    node.definition_hypothesis = "Пространство — это вместилище форм и расстояний."

    assert "«пространство»" in agent._compose_share_message(record=True)
    assert set(agent._shared_topics) == {"число", "пространство"}


def test_shared_topics_capped_at_fifty():
    agent = _agent_with_knowledge()
    for i in range(55):
        agent._remember_shared_topic(f"тема{i}")

    assert len(agent._shared_topics) == 50
    assert "тема0" not in agent._shared_topics
    assert "тема54" in agent._shared_topics


# ============================================================
# Память диалога: get_history впервые реально используется
# ============================================================

def test_get_history_merges_user_messages_and_answers():
    ui = UserInteraction(agent_name="DM")
    ui.receive_user_message("Расскажи, что нового ты узнал?", cycle=2)
    question = ui.ask_user("Что такое число?", context="c", cycle=3)
    ui.submit_answer(question["id"], "Число — это количество", cycle=4)

    history = ui.get_history(10)
    senders = [entry["sender"] for entry in history]
    assert senders.count("user") == 2
    answers = [e for e in history if e["msg_type"] == "answer"]
    assert answers and "количеств" in answers[-1]["content"]


def test_recent_dialogue_topics_reads_history():
    ui = UserInteraction(agent_name="DM")
    ui.receive_user_message("Я ушёл разбираться с дедлайном на работе.", cycle=5)
    agent = SimpleNamespaceWrapper(user_interaction=ui)
    pc = ProactiveCommunication(
        agent_name="DM", user_interaction=ui, attachment=None
    )

    topics = pc._recent_dialogue_topics(agent)
    assert len(topics) == 1
    assert topics[0].startswith("Я ушёл разбираться")
    assert topics[0].endswith("…")


def test_recent_dialogue_topics_limit_and_dedup():
    ui = UserInteraction(agent_name="DM")
    for i in range(5):
        ui.receive_user_message(f"реплика номер {i} о жизни", cycle=i)
    agent = SimpleNamespaceWrapper(user_interaction=ui)
    pc = ProactiveCommunication(
        agent_name="DM", user_interaction=ui, attachment=None
    )

    topics = pc._recent_dialogue_topics(agent)

    assert len(topics) == 3
    assert topics[0] == "реплика номер 4 о жизни"


def test_recent_dialogue_topics_without_interaction():
    agent = SimpleNamespaceWrapper()
    pc = ProactiveCommunication(
        agent_name="DM", user_interaction=None, attachment=None
    )
    assert pc._recent_dialogue_topics(agent) == []


# ============================================================
# Care с промисом вспоминает диалог
# ============================================================

def _care_pc(ui):
    return ProactiveCommunication(
        agent_name="DM", user_interaction=ui, attachment=None
    )


def test_care_with_promise_mentions_recent_dialogue():
    um = UserModel()
    um.observe("Не переживай, могу отлучаться надолго.", cycle=1)
    ui = UserInteraction(agent_name="DM")
    ui.receive_user_message("Я ушёл разбираться с дедлайном на работе.", cycle=5)
    agent = SimpleNamespaceWrapper(user_model=um, user_interaction=ui)

    msg = _care_pc(ui)._compose_care_with_promise(agent, cycle=100)

    assert msg["context"] == "silence_with_promise"
    assert "Последнее, о чём мы говорили" in msg["content"]
    assert "дедлайном на работе" in msg["content"]


def test_care_with_promise_without_history_keeps_quiet_text():
    um = UserModel()
    um.observe("Не переживай, могу отлучаться надолго.", cycle=1)
    agent = SimpleNamespaceWrapper(user_model=um)
    pc = ProactiveCommunication(
        agent_name="DM", user_interaction=None, attachment=None
    )

    msg = pc._compose_care_with_promise(agent, cycle=100)

    assert "не тревожу" in msg["content"]
    assert "Последнее, о чём мы говорили" not in msg["content"]


# ============================================================
# Чекпоинт
# ============================================================

def test_shared_topics_survive_checkpoint():
    original = _agent_with_knowledge(name="DM")
    original.cycle_count = 9
    original._remember_shared_topic("число")

    state = build_state_from_agent(original)
    validate_checkpoint_state(state)
    assert state["shared_topics"] == {"число": 9}

    restored = DigitalBeing(name="DM")
    restored.cycle_count = 9
    apply_state_to_agent(restored, state)
    assert restored._shared_topics == {"число": 9}


def test_validation_rejects_bad_shared_topics():
    with pytest.raises(ValueError):
        validate_checkpoint_state({"shared_topics": {"тема": "вчера"}})
    with pytest.raises(ValueError):
        validate_checkpoint_state({"shared_topics": {"тема": -1}})
    with pytest.raises(ValueError):
        validate_checkpoint_state({"shared_topics": {7: 1}})


# ============================================================
# Вспомогательное
# ============================================================

class SimpleNamespaceWrapper:
    """Минимальный агент-заглушка как в тестах «Собеседника-2»."""

    def __init__(self, **attrs):
        for key, value in attrs.items():
            setattr(self, key, value)
