"""Обычный ответ пользователя закрывает вопрос Core, а не обучает новой теме."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.agent_runner import AgentRunner
from src.core.open_questions import OpenQuestionsManager
from src.perception.user_interaction import UserInteraction


@pytest.mark.asyncio
async def test_user_message_answers_latest_open_question():
    manager = OpenQuestionsManager(cycle_provider=lambda: 8)
    manager.ask("Ты понимаешь меня?", source="self")
    agent = SimpleNamespace(
        name="Alpha", cycle_count=8,
        naming_dialogue=SimpleNamespace(phase="completed"),
        user_interaction=UserInteraction("Alpha"),
        has_open_questions=manager.has_unanswered,
        answer_open_question=manager.answer,
    )
    runner = AgentRunner.__new__(AgentRunner)
    runner.name = "Alpha"; runner.agent = agent
    runner.bus = SimpleNamespace(publish=AsyncMock())

    await runner._on_user_message(SimpleNamespace(data={"text": "Да, я тебя слышу и стараюсь понять."}))

    assert manager.list_public()[0]["answered"] is True
    assert agent.user_interaction.get_pending_question() is None
    assert not hasattr(runner, "_pending_user_messages")


def test_name_result_formatter_does_not_invent_alternative():
    text = AgentRunner._format_name_result(
        {"status": "alternative_proposed", "agent_alternative": "Альфа Jr."},
        "Малютка",
    )
    assert "Альфа Jr." in text
    assert "Малютка" not in text or "другое имя" in text


@pytest.mark.asyncio
async def test_i_dont_know_is_recorded_as_unknown_not_fact():
    interaction = UserInteraction("Alpha")
    interaction.ask_user("Что для тебя важно?", cycle=2)
    agent = SimpleNamespace(
        name="Alpha", cycle_count=2,
        naming_dialogue=SimpleNamespace(phase="completed"),
        user_interaction=interaction,
        has_open_questions=lambda: False,
    )
    runner = AgentRunner.__new__(AgentRunner)
    runner.name = "Alpha"; runner.agent = agent
    runner.bus = SimpleNamespace(publish=AsyncMock())

    await runner._on_user_message(SimpleNamespace(data={"text": "Не знаю"}))

    assert interaction.question_history[0]["answer"] == "Не знаю"
    assert interaction.pending_questions == []
    assert "не знаю" in runner.bus.publish.call_args.args[1]["text"].lower()
    assert "факт" in runner.bus.publish.call_args.args[1]["text"].lower()


def test_open_question_unknown_answer_has_explicit_kind():
    manager = OpenQuestionsManager(cycle_provider=lambda: 1)
    manager.ask("Что происходит?", source="self")
    result = manager.answer("не уверен.")
    assert result["status"] == "answered"
    assert result["answer_kind"] == "unknown"


@pytest.mark.asyncio
async def test_direct_user_question_gets_priority_over_learning_queue():
    interaction = UserInteraction("Alpha")
    interaction.ask_user("Как тебя поддержать?", cycle=2)
    agent = SimpleNamespace(
        name="Alpha", cycle_count=2,
        naming_dialogue=SimpleNamespace(phase="completed"),
        user_interaction=interaction,
        has_open_questions=lambda: False,
    )
    runner = AgentRunner.__new__(AgentRunner)
    runner.name = "Alpha"; runner.agent = agent
    runner.bus = SimpleNamespace(publish=AsyncMock())

    await runner._on_user_message(SimpleNamespace(data={"text": "Просто будь рядом."}))

    assert interaction.question_history[0]["answer"] == "Просто будь рядом."
    assert not hasattr(runner, "_pending_user_messages")
    assert "Ответ записан" in runner.bus.publish.call_args.args[1]["text"]
