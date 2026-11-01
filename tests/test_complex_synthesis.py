"""Под-вопросы и синтез сложного вопроса (ступень 3.2).

Живой путь: UserInteraction.submit_answer -> on_synthesis_needed ->
Agent.synthesize_complex_question -> ThinkingPipeline. Раньше колбэк
существовал только во внутреннем контуре (_process_user_answer), а ответы
цепочки собирались сканированием общей истории — синтез в живом режиме
не запускался и работал на мусорных данных.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.cognition.thinking_pipeline import ThinkingPipeline
from src.perception.user_interaction import UserInteraction


# ============================================================
# Цепочка под-вопросов: точное накопление ответов
# ============================================================

def test_sub_question_chain_accumulates_exact_answers():
    ui = UserInteraction("Тэсс")
    subs = ["что такое жизнь?", "что такое смысл?"]
    r1 = ui.ask_user(
        "Я изучаю концепцию 'жизнь'. Мне сложно понять без внешней помощи. "
        "Можете кратко объяснить: что такое жизнь?",
        context="Концепция: жизнь, под-запросы: что такое жизнь?",
        cycle=100, complex_question="жизнь", sub_questions=subs,
        sub_question_index=0,
    )
    assert r1["status"] == "queued"

    calls = []
    ui.submit_answer(r1["id"], "Жизнь — это процесс",
                     on_synthesis_needed=lambda c, sa: calls.append((c, sa)))

    # Синтез ещё рано: должен прийти следующий под-вопрос.
    assert calls == []
    pending = ui.get_pending_question()
    assert pending is not None
    assert pending["complex_question"] == "жизнь"
    assert pending["sub_question_index"] == 1
    assert pending["sub_answers"] == {"что такое жизнь?": "Жизнь — это процесс"}

    ui.submit_answer(pending["id"], "Смысл — это цель",
                     on_synthesis_needed=lambda c, sa: calls.append((c, sa)))

    assert len(calls) == 1
    complex_question, sub_answers = calls[0]
    assert complex_question == "жизнь"
    assert sub_answers == {
        "что такое жизнь?": "Жизнь — это процесс",
        "что такое смысл?": "Смысл — это цель",
    }
    assert ui.get_pending_question() is None


def test_synthesis_answers_not_polluted_by_unrelated_history():
    """Ответ на чужой вопрос с темой в контексте не попадает в синтез."""
    ui = UserInteraction("Тэсс")
    other = ui.ask_user(
        "Как тебя поддержать?",
        context="самостоятельный вопрос по теме: смысл",
        cycle=1,
    )
    ui.submit_answer(other["id"], "Просто будь рядом")

    calls = []
    r = ui.ask_user(
        "Я изучаю концепцию 'смысл'. ... Можете кратко объяснить: что такое смысл?",
        context="Концепция: смысл, под-запросы: что такое смысл?",
        cycle=100, complex_question="смысл",
        sub_questions=["что такое смысл?"], sub_question_index=0,
    )
    ui.submit_answer(r["id"], "Смысл — это цель",
                     on_synthesis_needed=lambda c, sa: calls.append((c, sa)))

    assert calls == [("смысл", {"что такое смысл?": "Смысл — это цель"})]


def test_legacy_chain_without_accumulator_falls_back_to_context():
    """Подвешенная из старого чекпоинта цепочка не теряет первые ответы."""
    ui = UserInteraction("Тэсс")
    r = ui.ask_user(
        "Также для понимания 'жизнь': что такое смысл?",
        context="Под-вопрос 2/2 для: жизнь",
        cycle=100, complex_question="жизнь",
        sub_questions=["что такое жизнь?", "что такое смысл?"],
        sub_question_index=1,
    )
    # Имитируем старую запись: накопителя нет, первый ответ в истории.
    ui.pending_questions[0]["sub_answers"] = {}
    ui.question_history.append({
        "question": "Я изучаю концепцию 'жизнь'. ... что такое жизнь?",
        "answer": "Жизнь — это процесс",
        "context": "Концепция: жизнь, под-запросы: что такое жизнь?",
        "cycle": 40, "priority": "medium",
    })

    calls = []
    ui.submit_answer(r["id"], "Смысл — это цель",
                     on_synthesis_needed=lambda c, sa: calls.append((c, sa)))

    assert calls == [("жизнь", {
        "Я изучаю концепцию 'жизнь'. ... что такое жизнь?": "Жизнь — это процесс",
        "что такое смысл?": "Смысл — это цель",
    })]


# ============================================================
# Живая дверь ответа: колбэк синтеза доходит до Core
# ============================================================

def _runner(agent):
    runner = AgentRunner.__new__(AgentRunner)
    runner.name = agent.name
    runner.agent = agent
    runner.bus = SimpleNamespace(publish=AsyncMock(), publish_sync=Mock())
    return runner


def _chain_last_question(ui):
    """Последний под-вопрос цепочки «жизнь» ждёт ответа."""
    return ui.ask_user(
        "Также для понимания 'жизнь': что такое смысл?",
        context="Под-вопрос 2/2 для: жизнь",
        cycle=10, complex_question="жизнь",
        sub_questions=["что такое жизнь?", "что такое смысл?"],
        sub_question_index=1,
        sub_answers={"что такое жизнь?": "Жизнь — это процесс"},
    )


@pytest.mark.asyncio
async def test_runner_answer_triggers_synthesis_and_reports_it():
    ui = UserInteraction("Тэсс")
    _chain_last_question(ui)
    agent = SimpleNamespace(
        name="Тэсс", cycle_count=20,
        naming_dialogue=SimpleNamespace(phase="completed"),
        user_interaction=ui,
        synthesize_complex_question=Mock(),
    )
    runner = _runner(agent)

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Смысл — это цель"})
    )

    agent.synthesize_complex_question.assert_called_once_with(
        "жизнь",
        {
            "что такое жизнь?": "Жизнь — это процесс",
            "что такое смысл?": "Смысл — это цель",
        },
    )
    runner.bus.publish.assert_awaited_once()
    text = runner.bus.publish.call_args.args[1]["text"]
    assert "свёл воедино" in text
    assert "жизнь" in text
    assert ui.get_pending_question() is None


@pytest.mark.asyncio
async def test_runner_without_synthesizer_still_answers():
    ui = UserInteraction("Тэсс")
    ui.ask_user("Как тебя поддержать?", context="самостоятельный вопрос", cycle=5)
    agent = SimpleNamespace(
        name="Тэсс", cycle_count=6,
        naming_dialogue=SimpleNamespace(phase="completed"),
        user_interaction=ui,
    )
    runner = _runner(agent)

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Просто будь рядом."})
    )

    runner.bus.publish.assert_awaited_once()
    assert "Ответ записан" in runner.bus.publish.call_args.args[1]["text"]
    assert ui.get_pending_question() is None


# ============================================================
# Фасад агента
# ============================================================

def test_agent_facade_delegates_to_thinking():
    stub = DigitalBeing.__new__(DigitalBeing)
    # Нет thinking — фасад не падает.
    assert DigitalBeing.synthesize_complex_question(stub, "жизнь", {}) is None

    stub.thinking = Mock()
    DigitalBeing.synthesize_complex_question(
        stub, "жизнь", {"что такое жизнь": "процесс"}
    )
    stub.thinking._synthesize_complex_question.assert_called_once_with(
        "жизнь", {"что такое жизнь": "процесс"}
    )


# ============================================================
# Синтез: буквальные ответы вместо отсутствующих узлов
# ============================================================

def _pipeline(encounter):
    tp = ThinkingPipeline.__new__(ThinkingPipeline)
    tp.agent = SimpleNamespace(
        cycle_count=5,
        mental_models=SimpleNamespace(concepts={}, encounter_concept=encounter),
        success_streak=0,
        intelligence=1,
    )
    return tp


def test_synthesize_uses_literal_user_answers_without_nodes():
    encounter = Mock(return_value=SimpleNamespace(confidence=0.5))
    tp = _pipeline(encounter)

    tp._synthesize_complex_question(
        "что такое жизнь и смысл?",
        {
            "что такое жизнь": "Жизнь — это процесс обмена",
            "что такое смысл": "Смысл — это цель движения",
        },
    )

    encounter.assert_called_once()
    kwargs = encounter.call_args.kwargs
    assert kwargs["concept_name"] == "что такое жизнь и смысл?"
    assert "процесс обмена" in kwargs["outcome"]
    assert "цель движения" in kwargs["outcome"]
    assert tp.agent.intelligence == 3


def test_synthesize_without_usable_answers_does_not_learn():
    encounter = Mock()
    tp = _pipeline(encounter)

    tp._synthesize_complex_question("что такое жизнь?", {})
    tp._synthesize_complex_question("что такое жизнь?", {"не в формате": "ответ"})

    encounter.assert_not_called()
    assert tp.agent.intelligence == 1
