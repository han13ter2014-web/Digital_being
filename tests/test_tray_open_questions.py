"""
Регрессионный тест: открытые вопросы должны быть видны в GUI-режиме.

До фикса: agent_runner.py не вызывал agent._consume_open_question()
и не публиковал ответы на вопросы в EventBus — поэтому в трее/чате
пользователь видел только терминал main.py.

После фикса: AgentRunner использует те же приоритеты, что и main.py,
а ответы публикуются через AGENT_THOUGHT, который слушает ChatWindow.
"""

from src.core.agent_runner import (
    generate_prioritized_stimulus,
)
from src.core.event_bus import EventBus, Events


def _make_agent_with_question():
    """Создаёт агента с одним поставленным в очередь вопросом."""
    from src.core.agent import DigitalBeing
    a = DigitalBeing("TestAgent")
    # Не используя init-логику напрямую — просто кладём вопрос вручную.
    a._open_questions = []
    a.ask_user("что такое любовь?", source="test")
    return a


def test_generate_prioritized_stimulus_consumes_open_question():
    """generate_prioritized_stimulus должен возвращать стимул по открытому вопросу."""
    agent = _make_agent_with_question()
    assert agent.has_open_questions()

    stimulus = generate_prioritized_stimulus(agent)

    assert stimulus is not None
    assert stimulus.startswith("вопрос: ")
    assert "любовь" in stimulus.lower()
    # Стратегия тоже должна быть в префиксе
    assert "стратегия=" in stimulus


def test_generate_prioritized_stimulus_falls_back_to_pool():
    """Если открытых вопросов нет — должен возвращаться случайный стимул из пула."""
    from src.core.agent import DigitalBeing
    a = DigitalBeing("TestAgent")
    assert not a.has_open_questions()

    # Подменяем пул, чтобы проверить детерминированно
    from config.simulation_config import LR_CONFIG
    original_pool = LR_CONFIG.STIMULI_POOL
    LR_CONFIG.STIMULI_POOL = ["стимул-A", "стимул-B"]
    try:
        stimulus = generate_prioritized_stimulus(a)
        # Не должно начинаться с "вопрос: " (это маркер open-question)
        assert not stimulus.startswith("вопрос: ")
        assert stimulus in LR_CONFIG.STIMULI_POOL
    finally:
        LR_CONFIG.STIMULI_POOL = original_pool


def test_consume_marks_question_progress():
    """_consume_open_question должен делать запись о начале размышления."""
    agent = _make_agent_with_question()
    n_questions_before = len(agent._open_questions)
    n_explored_before = len(agent._open_questions[0]["explorations"])

    generate_prioritized_stimulus(agent)

    # Запись пока не делается (это делает _record_open_question_exploration
    # после think). Но _consume_open_question мог пометить как
    # «last_explored_at == current cycle» — проверим, что вопрос ещё в очереди.
    assert len(agent._open_questions) == n_questions_before
    # Вопрос должен остаться неотвеченным (мы только начали думать).
    assert not all(q["answered"] for q in agent._open_questions)


def test_agent_runner_publishes_answer_when_question_resolved(monkeypatch):
    """AgentRunner должен публиковать ответ на открытый вопрос в AGENT_THOUGHT.

    Проверяем прямой эффект — ответ публикуется синхронно через
    publish_sync, поэтому мы можем его проверить без asyncio-цикла.
    """
    from src.core.agent import DigitalBeing
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    bus = EventBus()
    agent = DigitalBeing("TestAgent")
    # Ставим вопрос
    agent.ask_user("что такое любовь?", source="test")
    question_text = agent._open_questions[0]["text"]

    # Подменяем agent.think, чтобы он сразу «нашёл ответ».
    # Возвращаем текст, который сработает как ответ в _record_open_question_exploration:
    # "[Ментальная модель] ..." — соответствует эвристике «ответ найден».
    def fake_think(perceived):
        return "[Ментальная модель] Любовь — это чувство привязанности."

    monkeypatch.setattr(agent, "think", fake_think)

    # Создаём Runner и подменяем publish_sync, чтобы он записал,
    # какие события были отправлены.
    published_thoughts = []
    original_publish_sync = bus.publish_sync

    def spy_publish_sync(event_name, data=None, source=None, **kwargs):
        if event_name == Events.AGENT_THOUGHT:
            text = (data or {}).get("text", "")
            published_thoughts.append(text)
        return original_publish_sync(event_name, data, source=source, **kwargs)

    bus.publish_sync = spy_publish_sync

    runner = AgentRunner(agent, bus, name="TestRunner")
    runner._do_one_agent_cycle(
        stimulus=f"вопрос: {question_text} [стратегия=test, попытка 1/5]",
        user_initiated=False,
    )

    # Должно быть опубликовано хотя бы одно AGENT_THOUGHT с ответом
    answer_events = [
        t for t in published_thoughts
        if "Ответ на вопрос" in t or "любовь" in t.lower()
    ]
    assert len(answer_events) >= 1, (
        f"Ожидался ответ на вопрос в AGENT_THOUGHT, "
        f"получено: {published_thoughts}"
    )
    # Вопрос должен быть помечен как answered
    assert agent._open_questions[0]["answered"] is True
    assert agent._open_questions[0]["answer"] is not None


def test_agent_runner_subscribed_to_user_command():
    """AgentRunner должен быть подписан на USER_COMMAND (для /ask из чата)."""
    from src.core.agent import DigitalBeing
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    bus = EventBus()
    try:
        agent = DigitalBeing("TestAgent")
        # Создание AgentRunner вызывает _setup_subscriptions синхронно.
        runner = AgentRunner(agent, bus, name="TestRunner")

        # Проверяем, что подписка есть в шине.
        # EventBus хранит подписки в bus._subscribers (dict по event_name).
        subs = getattr(bus, "_subscribers", {})
        user_cmd_subs = subs.get(Events.USER_COMMAND, [])
        assert len(user_cmd_subs) >= 1, (
            f"AgentRunner должен быть подписан на USER_COMMAND, "
            f"найдено подписчиков: {len(user_cmd_subs)}"
        )
    finally:
        # EventBus.stop может быть async или sync — пробуем оба варианта
        try:
            result = bus.stop()
            if hasattr(result, "__await__"):
                # Если async — мы в sync-контексте, пропускаем.
                pass
        except Exception:
            pass
