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
    # «Собеседник-6»: реплики идут через UserInteraction.send_reply →
    # AGENT_MESSAGE; без attach_bus запись в шину молча не происходит.
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


def _thoughts(bus):
    return [
        dict(data or {}) for name, data in bus.published if name == Events.AGENT_THOUGHT
    ]


def _replies(bus):
    """Реплики канала диалога (AGENT_MESSAGE от UserInteraction.send_reply)."""
    return [
        dict(data or {}) for name, data in bus.published if name == Events.AGENT_MESSAGE
    ]


def _reply_texts(bus):
    return [d.get("content", "") for d in _replies(bus)]


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
    texts = _reply_texts(bus)
    assert any("вопрос снимаю" in t for t in texts)
    assert any("«вопрос»" in t for t in texts)
    # «Собеседник-6»: реплика — в канале диалога, не в мыслях
    assert not _thoughts(bus)
    assert ui.message_history[-1]["context"] == "repeat_protest"


@pytest.mark.asyncio
async def test_social_presence_with_pending_keeps_question_open():
    """Социальная реплика без протеста НЕ снимает вопрос сущности."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(SimpleNamespace(data={"text": "Привет! Я рядом."}))

    assert ui.get_pending_question() is not None
    assert agent._user_explained_topics == {}
    texts = _reply_texts(bus)
    assert any("остаётся открытым" in t for t in texts)


@pytest.mark.asyncio
async def test_repeat_protest_without_pending_is_just_social():
    """Протест без открытого вопроса — обычная социальная реплика."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(SimpleNamespace(data={"text": "Ты повторяешь."}))

    assert ui.question_history == []
    assert agent._user_explained_topics == {}
    texts = _reply_texts(bus)
    assert any("Спасибо, что ты рядом" in t for t in texts)


@pytest.mark.asyncio
async def test_social_presence_without_pending_gets_neutral_reply():
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(SimpleNamespace(data={"text": "Привет! Я рядом."}))

    assert ui.get_last_user_message_cycle() == agent.cycle_count
    assert ui.question_history == []
    texts = _reply_texts(bus)
    assert any("Спасибо, что ты рядом" in t for t in texts)
    # «Собеседник-6»: реплика записана в message_history и переживает
    # рестарт (персистентность user_interaction).
    assert ui.message_history[-1]["sender"] == "agent"
    assert "Спасибо, что ты рядом" in ui.message_history[-1]["content"]


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
    texts = _reply_texts(bus)
    assert any("Записала про «вопрос»" in t for t in texts)


@pytest.mark.asyncio
async def test_question_with_pending_does_not_close_question():
    """Регрессия диалоговой очереди: вопрос человека — не ответ.

    Живая сессия: «Что тебе сейчас важно?» при открытом вопросе про
    «обучение» записывалось как «Записал про "обучение"», и вопрос
    сущности закрывался чужими словами. Нераспознанный вопрос идёт
    мимо двери ответа: висящий вопрос остаётся открытым, человек
    получает честный отклик вместо ложного «Записал про…».
    """
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Почему небо голубое?"})
    )

    assert ui.get_pending_question() is not None
    assert ui.question_history == []
    texts = _reply_texts(bus)
    assert not any("Записала про" in t for t in texts)
    assert any("не понимаю" in t for t in texts)


@pytest.mark.asyncio
async def test_about_self_question_with_pending_gets_honest_reply():
    """Вопрос о сущности при висящем вопросе — честный
    ответ о себе; висящий вопрос не перебивает разговор."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Чем ты сейчас занята?"})
    )

    assert ui.get_pending_question() is not None
    texts = _reply_texts(bus)
    assert any("Меня зовут" in t for t in texts)
    assert not any("Записала про" in t for t in texts)


@pytest.mark.asyncio
async def test_unknown_text_asks_clarification_not_learning_material():
    """Непонятая реплика сразу вызывает протокол уточнения 1–4.

    Автообучения и постановки фразы в стимулы по-прежнему нет: сначала
    человек выбирает категорию, и лишь его ответ разрешает дальнейший путь.
    """
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(
            data={"text": "Квантовая запутанность и коллапс волновой функции."}
        )
    )

    assert agent._user_explained_topics == {}
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    pending = ui.get_pending_question()
    assert pending is not None
    assert "1 — обычный разговор" in pending["question"]
    assert "4 — неважно, не учить" in pending["question"]
    assert _reply_texts(bus) == []
    assert not _thoughts(bus)


@pytest.mark.asyncio
async def test_unknown_text_is_remembered_as_dialogue_turn():
    """«Собеседник-8»: нераспознанная реплика — тоже реплика диалога.

    Дверь ACT_UNKNOWN была единственной, кто не писал в память диалога:
    care застревала на последней РАСПОЗНАННОЙ теме, хотя свежий
    содержательный разговор — как раз нераспознанный (живой зонд
    2026-11-03: тема care не обновлялась после новой фразы человека).
    """
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(
            data={"text": "Квантовая запутанность и коллапс волновой функции."}
        )
    )

    history = ui.get_history(5)
    user_texts = [
        str(entry.get("content") or "")
        for entry in history
        if entry.get("sender") == "user"
    ]
    assert any("Квантовая запутанность" in t for t in user_texts)


@pytest.mark.asyncio
async def test_user_contact_is_felt_as_joy():
    """«Эмоции-1»: контакт с человеком — реальная причина радости.

    Событие записывается в эмоциональный контур до всех дверей:
    неважно, что сказано — важно, что человек рядом.
    """
    agent, runner, bus = _make_runner()

    await runner._on_user_message(SimpleNamespace(data={"text": "привет"}))

    state = agent.emotional_state
    assert state.levels["joy"] > 0.0
    assert state.episodes[-1]["event"] == "user_contact"


@pytest.mark.asyncio
async def test_orphan_answer_formula_gets_honest_reply():
    """Явный «ответ» без вопроса сущности — записывать некуда."""
    agent, runner, bus = _make_runner()

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Мой ответ: сорок два."})
    )

    assert agent._user_explained_topics == {}
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    texts = _reply_texts(bus)
    assert any("нет вопроса" in t for t in texts)


@pytest.mark.asyncio
async def test_ask_about_self_gets_honest_reply_not_learning_material():
    """«Собеседник-5»: «чем занимаешься?» — честный ответ, не материал."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(SimpleNamespace(data={"text": "Чем занимаешься?"}))

    assert ui.get_last_user_message_cycle() == agent.cycle_count
    assert ui.question_history == []
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    texts = _reply_texts(bus)
    reply = next(t for t in texts if "Меня зовут" in t)
    assert agent.name in reply
    assert "циклов" in reply


@pytest.mark.asyncio
async def test_ask_about_self_reports_occupation_and_memory():
    agent, runner, bus = _make_runner()
    agent._exploration_history = ["квантовая запутанность"]
    agent.user_model.observe("могу отлучаться надолго — не переживай", cycle=1)
    agent.user_model.observe("я работаю по ночам", cycle=2)

    await runner._on_user_message(SimpleNamespace(data={"text": "Чем ты занята?"}))

    texts = _reply_texts(bus)
    reply = next(t for t in texts if "Меня зовут" in t)
    assert "квантовая запутанность" in reply
    assert "не тревожу" in reply
    assert "я работаю по ночам" in reply


@pytest.mark.asyncio
async def test_identity_recognition_confirms_actual_name():
    """Узнавание имени: «Ты Нова?» при совпадении имени — «Да», не unknown."""
    agent, runner, bus = _make_runner()
    agent.name = "Нова"

    await runner._on_user_message(SimpleNamespace(data={"text": "Ты Нова?"}))

    texts = _reply_texts(bus)
    assert any("Да, меня зовут Нова" in t for t in texts)


@pytest.mark.asyncio
async def test_identity_recognition_denies_wrong_name():
    """Узнавание имени: «Ты Нова?» при другом имени — честное «Нет» и имя."""
    agent, runner, bus = _make_runner()
    agent.name = "Ола"

    await runner._on_user_message(SimpleNamespace(data={"text": "Ты Нова?"}))

    texts = _reply_texts(bus)
    reply = next(t for t in texts if "Нет, я не Нова" in t)
    assert "меня зовут Ола" in reply


@pytest.mark.asyncio
async def test_identity_questions_follow_rename():
    """Узнавание имени: после переименования «кто ты?» и «ты X?» — новое имя."""
    agent, runner, bus = _make_runner()
    agent.name = "Омелла"

    await runner._on_user_message(SimpleNamespace(data={"text": "Кто ты?"}))
    await runner._on_user_message(SimpleNamespace(data={"text": "Ты Ола?"}))

    texts = _reply_texts(bus)
    assert any("Меня зовут Омелла" in t for t in texts)
    assert any("Нет, я не Ола" in t and "Омелла" in t for t in texts)


@pytest.mark.asyncio
async def test_non_identity_text_keeps_unknown_path():
    """Узнавание имени: не-идентификационный текст — прежний путь (уточнение)."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(
            data={"text": "Квантовая запутанность и коллапс волновой функции."}
        )
    )

    assert ui.get_pending_question() is not None
    assert _reply_texts(bus) == []


@pytest.mark.asyncio
async def test_social_greeting_gets_greeting_reply():
    """Социальный отклик: чистое приветствие — каркас приветствия, не нейтральный."""
    agent, runner, bus = _make_runner()

    await runner._on_user_message(SimpleNamespace(data={"text": "Привет!"}))

    texts = _reply_texts(bus)
    assert any("Привет. Рада тебя слышать." in t for t in texts)
    assert not any("Спасибо, что ты рядом" in t for t in texts)


@pytest.mark.asyncio
async def test_social_state_question_gets_state_reply():
    """Социальный отклик: «Как дела?» — каркас состояния без выдуманных деталей."""
    agent, runner, bus = _make_runner()

    await runner._on_user_message(SimpleNamespace(data={"text": "Как дела?"}))

    texts = _reply_texts(bus)
    assert any("всё ровно" in t for t in texts)
    assert not any("Спасибо, что ты рядом" in t for t in texts)


@pytest.mark.asyncio
async def test_social_warmth_keeps_neutral_reply():
    """Социальный отклик: прочее социальное (тепло) — прежний нейтральный каркас."""
    agent, runner, bus = _make_runner()

    await runner._on_user_message(SimpleNamespace(data={"text": "Скучаю по тебе."}))

    texts = _reply_texts(bus)
    assert any("Я слышу тебя. Спасибо, что ты рядом." in t for t in texts)


@pytest.mark.asyncio
async def test_social_with_pending_keeps_open_question_note():
    """Социальный отклик: социальная реплика при висящем вопросе — прежняя заметка."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(SimpleNamespace(data={"text": "Привет!"}))

    texts = _reply_texts(bus)
    assert any("остаётся открытым" in t for t in texts)


@pytest.mark.asyncio
async def test_definition_without_question_becomes_knowledge():
    """«X — это Y» без вопроса сущности — свидетельство, не материал."""
    agent, runner, bus = _make_runner()

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Git — это система контроля версий."})
    )

    assert "Git" in agent._user_explained_topics
    node = agent.mental_models.concepts["Git"]
    assert node.experiences[-1]["evidence_kind"] == "testimony"
    assert node.experiences[-1]["source"] == "user"
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    texts = _reply_texts(bus)
    reply = next(t for t in texts if "Записала" in t)
    assert "Git" in reply
    assert "переспрашивать не буду" in reply
    assert not _thoughts(bus)


@pytest.mark.asyncio
async def test_unlearnable_definition_gets_honest_refusal_not_queue():
    """«Собеседник-6»: незаписанное определение — отказ, не материал."""
    agent, runner, bus = _make_runner()

    await runner._on_user_message(
        SimpleNamespace(data={"text": "_внутреннее — это служебный узел"})
    )

    assert agent._user_explained_topics == {}
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    texts = _reply_texts(bus)
    assert any("не буду" in t for t in texts)


@pytest.mark.asyncio
async def test_definition_with_polite_prefix_records_topic():
    """«Запомни, пожалуйста: X — это Y» — тема X, без префикса.

    Живой день 2026-11-02: «оптики» штамповалась как «понимать».
    """
    agent, runner, bus = _make_runner()

    await runner._on_user_message(
        SimpleNamespace(
            data={"text": "Запомни, пожалуйста: оптика — это раздел физики о свете."}
        )
    )

    assert "оптика" in agent._user_explained_topics
    assert "понимать" not in agent._user_explained_topics
    texts = _reply_texts(bus)
    assert any("Записала" in t and "оптика" in t for t in texts)


@pytest.mark.asyncio
async def test_definition_with_unrelated_pending_diverts_to_definition_door():
    """«X — это Y» про чужую тему — не ответ на вопрос сущности.

    Живой день 2026-11-02: определение погоды при вопросе про «сильный
    ИИ vs слабый ИИ» записалось как знание о вопросе. Теперь объяснение
    уходит в дверь определений, вопрос сущности остаётся открытым.
    """
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(
        "Как ты думаешь, чем сильный ИИ отличается от слабого?",
        context="самостоятельный вопрос по теме: сильный ИИ vs слабый ИИ",
        cycle=1,
    )

    await runner._on_user_message(
        SimpleNamespace(
            data={"text": "Погода — это состояние атмосферы в данное время."}
        )
    )

    assert "Погода" in agent._user_explained_topics
    assert "сильный ИИ vs слабый ИИ" not in agent._user_explained_topics
    # вопрос сущности не съеден чужим определением
    assert ui.get_pending_question() is not None
    texts = _reply_texts(bus)
    assert any("Записала" in t and "Погода" in t for t in texts)


@pytest.mark.asyncio
async def test_definition_of_pending_topic_still_answers_pending():
    """Регрессия ступени 1: «Git — это …» при вопросе про Git — ответ."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(
        "Что такое Git?",
        context="самостоятельный вопрос по теме: Git",
        cycle=1,
    )

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Git — это система контроля версий."})
    )

    assert "Git" in agent._user_explained_topics
    assert ui.get_pending_question() is None


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


@pytest.mark.asyncio
async def test_request_gets_honest_refusal_not_learning_material():
    """Границы просьб: «Нарисуй кота» — честное «не умею», не концепт и не выдумка."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Нарисуй кота, пожалуйста."})
    )

    assert ui.get_last_user_message_cycle() == agent.cycle_count
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    texts = _reply_texts(bus)
    reply = next(t for t in texts if "не умею" in t)
    assert "тела" in reply
    assert "Не нашел файл" not in reply


@pytest.mark.asyncio
async def test_request_with_pending_keeps_question_open():
    """Границы просьб: просьба о невозможном не закрывает вопрос сущности."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(SimpleNamespace(data={"text": "Спой песню!"}))

    assert ui.get_pending_question() is not None
    assert agent._user_explained_topics == {}
    texts = _reply_texts(bus)
    assert any("не умею" in t for t in texts)


@pytest.mark.asyncio
async def test_noise_input_gets_honest_reply_not_learning_material():
    """Границы просьб: «🙂🙂🙂» — честный ответ «нет букв», не материал для изучения."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(SimpleNamespace(data={"text": "🙂🙂🙂"}))

    # вопрос сущности остаётся открытым — эмодзи не ответ
    assert ui.get_pending_question() is not None
    assert ui.get_last_user_message_cycle() == agent.cycle_count
    queue = getattr(runner, "_pending_user_messages", None)
    assert queue is None or queue.qsize() == 0
    texts = _reply_texts(bus)
    reply = next(t for t in texts if "нет букв" in t)
    assert "Напиши текстом" in reply
