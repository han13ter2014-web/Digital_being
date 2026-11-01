"""Маршрутизация USER_MESSAGE: социальная речь доходит до сущности.

До «Собеседника-1» любой текст при открытом вопросе сущности
превращался в ответ («Ответ записан.»), а вне вопроса — в учебный
материал («Не нашел файл для 'Я же уже отвечал тебе.'»). Теперь
социальный акт: фиксирует контакт (receive_user_message), получает
честный отклик и НЕ закрывает вопрос сущности. Настоящие ответы идут
прежним путём (регрессионные проверки внизу файла).
"""

from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import Events

QUESTION = "Я разбираюсь с темой «вопрос» и пока не уверен, что понимаю её правильно. Можешь объяснить своими словами?"
CONTEXT = "самостоятельный вопрос по теме: вопрос"


class RecordingBus:
    """Шина-записывалка: publish_sync и async publish пишут в список."""

    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner():
    agent = DigitalBeing(name="Router")
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    return agent, runner, bus


def _thoughts(bus):
    return [
        dict(data or {})
        for name, data in bus.published
        if name == Events.AGENT_THOUGHT
    ]


@pytest.mark.asyncio
async def test_repeat_protest_declines_question_and_mutes_topic():
    """«Собеседник-5»: «уже отвечал» при открытом вопросе — mute, не ответ.

    Живой прогон: сущность переспрашивала, человек протестовал — вопрос
    продолжал висеть. Теперь вопрос снимается как отклонённый (в
    историю ответов НЕ попадает), тема получает mute-штамп.
    """
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)
    assert ui.get_pending_question() is not None

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Я же уже отвечал тебе."})
    )

    # вопрос снят как отклонённый — не как ответ
    assert ui.get_pending_question() is None
    assert ui.question_history == []
    # тема замьючена — сущность сама к ней не вернётся
    assert agent._user_explained_topics == {"вопрос": agent.cycle_count}
    # контакт зафиксирован
    assert ui.get_last_user_message_cycle() == agent.cycle_count
    texts = [d.get("text", "") for d in _thoughts(bus)]
    assert any("вопрос снимаю" in t for t in texts)
    assert any("«вопрос»" in t for t in texts)


@pytest.mark.asyncio
async def test_social_presence_with_pending_keeps_question_open():
    """Социальная реплика без протеста НЕ снимает вопрос сущности."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Привет! Я рядом."})
    )

    assert ui.get_pending_question() is not None
    assert agent._user_explained_topics == {}
    texts = [d.get("text", "") for d in _thoughts(bus)]
    assert any("остаётся открытым" in t for t in texts)


@pytest.mark.asyncio
async def test_repeat_protest_without_pending_is_just_social():
    """Протест без открытого вопроса — обычная социальная реплика."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Ты повторяешь."})
    )

    assert ui.question_history == []
    assert agent._user_explained_topics == {}
    texts = [d.get("text", "") for d in _thoughts(bus)]
    assert any("Спасибо, что ты рядом" in t for t in texts)


@pytest.mark.asyncio
async def test_social_presence_without_pending_gets_neutral_reply():
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Привет! Я рядом."})
    )

    assert ui.get_last_user_message_cycle() == agent.cycle_count
    assert ui.question_history == []
    texts = [d.get("text", "") for d in _thoughts(bus)]
    assert any("Спасибо, что ты рядом" in t for t in texts)


@pytest.mark.asyncio
async def test_social_message_is_not_fed_to_learning_queue():
    agent, runner, bus = _make_runner()

    await runner._on_user_message(
        SimpleNamespace(
            data={"text": "Могу долго не писать — не переживай, если молчу."}
        )
    )

    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0


@pytest.mark.asyncio
async def test_plain_answer_still_closes_pending_question():
    """Регрессия: настоящий ответ закрывает вопрос сущности (baseline 2026-11-01).

    С «Собеседником-3» подтверждение цитирует записанное знание вместо
    безликого «Ответ записан.» — тема берётся из контекста вопроса.
    """
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(
        SimpleNamespace(
            data={"text": "Спокойно и тепло. А что тебя самого сейчас занимает?"}
        )
    )

    assert ui.get_pending_question() is None
    texts = [d.get("text", "") for d in _thoughts(bus)]
    assert any("Записал про «вопрос»" in t for t in texts)


@pytest.mark.asyncio
async def test_unknown_text_without_pending_still_goes_to_learning_queue():
    """Регрессия: нераспознанный текст без вопроса — учебный материал."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Квантовая запутанность и коллапс волновой функции."})
    )

    assert len(ui.message_history) == 0
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is not None
    assert queue.qsize() == 1


@pytest.mark.asyncio
async def test_ask_about_self_gets_honest_reply_not_learning_material():
    """«Собеседник-5»: «чем занимаешься?» — честный ответ, не материал."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Чем занимаешься?"})
    )

    assert ui.get_last_user_message_cycle() == agent.cycle_count
    assert ui.question_history == []
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    texts = [d.get("text", "") for d in _thoughts(bus)]
    reply = next(t for t in texts if "Меня зовут" in t)
    assert agent.name in reply
    assert "циклов" in reply


@pytest.mark.asyncio
async def test_ask_about_self_reports_occupation_and_memory():
    agent, runner, bus = _make_runner()
    agent._exploration_history = ["квантовая запутанность"]
    agent.user_model.observe(
        "могу отлучаться надолго — не переживай", cycle=1
    )
    agent.user_model.observe("я работаю по ночам", cycle=2)

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Чем ты занята?"})
    )

    texts = [d.get("text", "") for d in _thoughts(bus)]
    reply = next(t for t in texts if "Меня зовут" in t)
    assert "квантовая запутанность" in reply
    assert "не тревожу" in reply
    assert "я работаю по ночам" in reply


@pytest.mark.asyncio
async def test_definition_without_question_becomes_knowledge():
    """«X — это Y» без вопроса сущности — свидетельство, не материал."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Git — это система контроля версий."})
    )

    assert "Git" in agent._user_explained_topics
    node = agent.mental_models.concepts["Git"]
    assert node.experiences[-1]["evidence_kind"] == "testimony"
    assert node.experiences[-1]["source"] == "user"
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    texts = [d.get("text", "") for d in _thoughts(bus)]
    reply = next(t for t in texts if "Записал" in t)
    assert "Git" in reply
    assert "переспрашивать не буду" in reply


@pytest.mark.asyncio
async def test_definition_of_unlearnable_topic_falls_back_to_queue():
    """Незаписанное определение идёт старым путём — в очередь стимулов."""
    agent, runner, bus = _make_runner()

    await runner._on_user_message(
        SimpleNamespace(data={"text": "_внутреннее — это служебный узел"})
    )

    assert agent._user_explained_topics == {}
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is not None
    assert queue.qsize() == 1


@pytest.mark.asyncio
async def test_social_door_respects_naming_phase_priority(monkeypatch):
    """В фазе именования имя по-прежнему главнее социальных маркеров."""
    import random

    # 30% контрпредложений (naming_dialogue) — не про этот тест.
    monkeypatch.setattr(random, "random", lambda: 0.99)

    agent, runner, bus = _make_runner()
    agent.naming_dialogue.phase = "awaiting_name"

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Привет, пусть тебя зовут Мелория"})
    )

    assert agent.name == "Мелория"
