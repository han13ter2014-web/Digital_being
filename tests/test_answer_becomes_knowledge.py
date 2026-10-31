"""Свидетельство пользователя — знание (участок «Собеседник-3»).

До этого этапа ответ человека на вопрос сущности заканчивался
безликим «Ответ записан.», а тема через 50 циклов спрашивалась
снова: знание не записывалось. Теперь ответ становится опытом-
свидетельством концепта (kind=testimony, source="user", сила 0.4),
тема получает штамп цикла и не переспрашивается, а подтверждение
цитирует, что именно сущность записала.
"""

from types import SimpleNamespace

import pytest

from config.simulation_config import LR_CONFIG
from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.event_bus import Events
from src.core.open_questions import OpenQuestionsManager, _topic_from_question

QUESTION = "Я разбираюсь с темой «вопрос» и пока не уверен, что понимаю её правильно. Можешь объяснить своими словами?"
CONTEXT = "самостоятельный вопрос по теме: вопрос"
ANSWER = "Вопрос — это форма мысли, которая что-то спрашивает и ищет ответ."


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner():
    agent = DigitalBeing(name="KN")
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    return agent, runner, bus


def _thoughts(bus):
    return [
        dict(data or {})
        for name, data in bus.published
        if name == Events.AGENT_THOUGHT
    ]


# ============================================================
# Извлечение темы из вопроса
# ============================================================

def test_topic_from_question_what_is_pattern():
    assert _topic_from_question("что такое любовь?") == "любовь"
    assert _topic_from_question("Что такое простое число") == "простое число"


def test_topic_from_question_quoted_topic_pattern():
    assert (
        _topic_from_question("Я разбираюсь с темой «вопрос» и пока не уверен")
        == "вопрос"
    )
    assert _topic_from_question("тему «модуль math»") == "модуль math"


def test_topic_from_question_unrecognized():
    assert _topic_from_question("расскажи о закатах") is None
    assert _topic_from_question("") is None
    assert _topic_from_question(None) is None


# ============================================================
# Колбэк очереди открытых вопросов
# ============================================================

def test_open_question_answer_fires_callback():
    calls = []
    mgr = OpenQuestionsManager(on_user_answer=lambda q, a: calls.append((q, a)))
    mgr.ask("что такое простое число?", source="user")

    mgr.answer("Оно делится только на единицу и на себя")

    assert calls == [
        ("что такое простое число?", "Оно делится только на единицу и на себя")
    ]


def test_open_question_unknown_answer_does_not_fire_callback():
    calls = []
    mgr = OpenQuestionsManager()
    mgr.on_user_answer = lambda q, a: calls.append((q, a))
    mgr.ask("что такое простое число?", source="user")

    mgr.answer("не знаю")

    assert calls == []
    assert mgr.queue[0]["answered"] is True
    assert mgr.queue[0]["answer_kind"] == "unknown"


# ============================================================
# record_user_answer: свидетельство + штамп
# ============================================================

def test_record_user_answer_creates_testimony_knowledge():
    agent = DigitalBeing(name="KN")

    returned = agent.record_user_answer(
        "простое число", "Число делится только на единицу и на себя", cycle=13
    )

    assert returned == "простое число"
    assert agent._user_explained_topics == {"простое число": 13}
    node = agent.mental_models.concepts["простое число"]
    experience = node.experiences[-1]
    assert experience["evidence_kind"] == "testimony"
    assert experience["source"] == "user"
    assert experience["evidence_strength"] == 0.4
    # Свидетельство поднимает уверенность, но она остаётся ниже порога
    # «я знаю»: доверие слову — ещё не собственное наблюдение.
    assert 0.1 < node.confidence < 0.4


def test_record_user_answer_rejects_junk():
    agent = DigitalBeing(name="KN")

    assert agent.record_user_answer("", "ответ", 1) is None
    assert agent.record_user_answer("_bootstrap_loaded", "ответ", 1) is None
    assert agent.record_user_answer("тема", "   ", 1) is None

    assert agent._user_explained_topics == {}
    assert "тема" not in agent.mental_models.concepts


def test_stamps_capped_at_fifty():
    agent = DigitalBeing(name="KN")
    for i in range(55):
        agent.record_user_answer(f"тема{i}", f"объяснение {i}", cycle=i)

    assert len(agent._user_explained_topics) == 50
    assert "тема0" not in agent._user_explained_topics
    assert "тема54" in agent._user_explained_topics


# ============================================================
# Объяснённая тема не переспрашивается
# ============================================================

def test_recently_explained_by_user_boundary():
    agent = DigitalBeing(name="KN")
    agent._user_explained_topics["тема"] = 100

    agent.cycle_count = 100
    assert agent._recently_explained_by_user("тема") is True
    agent.cycle_count = 100 + LR_CONFIG.USER_EXPLAINED_COOLDOWN_CYCLES - 1
    assert agent._recently_explained_by_user("тема") is True
    agent.cycle_count = 100 + LR_CONFIG.USER_EXPLAINED_COOLDOWN_CYCLES
    assert agent._recently_explained_by_user("тема") is False
    assert agent._recently_explained_by_user("другое") is False


def test_explained_topic_is_not_exploration_target(monkeypatch):
    """Штамп исключает тему из выбора цели, пока кулдаун не истёк."""
    monkeypatch.setattr(LR_CONFIG, "EXPLORATION_DEPTH_RATIO", 0.0)
    monkeypatch.setattr(LR_CONFIG, "STIMULI_POOL", [])
    agent = DigitalBeing(name="KN")
    # Чистим bootstrap-концепты: интересует только тема со штампом.
    for name in list(agent.mental_models.concepts):
        if agent._is_learnable(name):
            del agent.mental_models.concepts[name]
    agent.cycle_count = 300
    agent.record_user_answer("простое число", "объяснение пользователя", cycle=300)

    assert agent._pick_exploration_target() is None

    agent.cycle_count += LR_CONFIG.USER_EXPLAINED_COOLDOWN_CYCLES
    assert agent._pick_exploration_target() == "простое число"


def test_ask_user_action_respects_stamp_even_with_explicit_target():
    """Продолжение намерения передаёт target напрямую, минуя селекторы.

    Живой прогон 2026-11-01 (ребёнок Тэсс): «спросил человека про
    'вопрос'» повторно на ~23-м цикле после объяснения — цель пришла
    параметром намерения, а не из _pick_exploration_target. Guard
    обязан стоять в самом действии.
    """
    agent = DigitalBeing(name="KN")
    agent.cycle_count = 300
    agent.record_user_answer("вопрос", "объяснение пользователя", cycle=280)

    result = agent._act_ask_user(target="вопрос")

    assert "не переспрашиваю" in result.get("text", "")
    assert agent.user_interaction.pending_questions == []


def test_ask_user_action_still_asks_fresh_topic():
    agent = DigitalBeing(name="KN")
    agent.cycle_count = 300

    result = agent._act_ask_user(target="новая тема")

    assert "спросил человека про 'новая тема'" in result.get("text", "")
    pending = agent.user_interaction.pending_questions
    assert len(pending) == 1
    assert pending[0]["context"] == (
        "самостоятельный вопрос по теме: новая тема"
    )


# ============================================================
# Прямой вопрос сущности через runner
# ============================================================

@pytest.mark.asyncio
async def test_direct_answer_becomes_knowledge_with_citation():
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)

    await runner._on_user_message(SimpleNamespace(data={"text": ANSWER}))

    node = agent.mental_models.concepts["вопрос"]
    experience = node.experiences[-1]
    assert experience["evidence_kind"] == "testimony"
    assert experience["source"] == "user"
    assert agent._user_explained_topics == {"вопрос": agent.cycle_count}

    texts = [d.get("text", "") for d in _thoughts(bus)]
    reply = next(t for t in texts if "Записал про" in t)
    assert "«вопрос»" in reply
    assert ANSWER in reply


@pytest.mark.asyncio
async def test_unknown_answer_is_not_recorded_as_knowledge():
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    ui.ask_user(QUESTION, context=CONTEXT, cycle=1)
    node_before = agent.mental_models.concepts.get("вопрос")
    experiences_before = len(node_before.experiences) if node_before else 0

    await runner._on_user_message(SimpleNamespace(data={"text": "не знаю"}))

    assert agent._user_explained_topics == {}
    node = agent.mental_models.concepts.get("вопрос")
    assert node is None or len(node.experiences) == experiences_before
    texts = [d.get("text", "") for d in _thoughts(bus)]
    assert any("не знаю" in t for t in texts)


# ============================================================
# Открытый вопрос через runner (колбэк моста)
# ============================================================

@pytest.mark.asyncio
async def test_open_question_answer_becomes_knowledge_via_callback():
    agent, runner, bus = _make_runner()
    agent.ask_user("что такое любовь?", source="user")
    assert agent.has_open_questions()

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Любовь — это забота и внимание к другому"})
    )

    assert not agent.has_open_questions()
    node = agent.mental_models.concepts["любовь"]
    assert node.experiences[-1]["evidence_kind"] == "testimony"
    assert agent._user_explained_topics["любовь"] == agent.cycle_count
    texts = [d.get("text", "") for d in _thoughts(bus)]
    assert any("Ответ записан к вопросу" in t for t in texts)


# ============================================================
# Цитата
# ============================================================

def test_short_quote_normalizes_and_truncates():
    assert AgentRunner._short_quote("  Привет   мир  ") == "Привет мир"
    quote = AgentRunner._short_quote("а" * 200)
    assert len(quote) == 80
    assert quote.endswith("…")


# ============================================================
# Чекпоинт
# ============================================================

def test_explained_topics_survive_checkpoint():
    original = DigitalBeing(name="KN")
    original.cycle_count = 77
    original.record_user_answer("простое число", "объяснение", cycle=70)

    state = build_state_from_agent(original)
    validate_checkpoint_state(state)
    assert state["user_explained_topics"] == {"простое число": 70}

    restored = DigitalBeing(name="KN")
    restored.cycle_count = 77
    apply_state_to_agent(restored, state)
    assert restored._user_explained_topics == {"простое число": 70}


def test_validation_rejects_bad_explained_topics():
    with pytest.raises(ValueError):
        validate_checkpoint_state({"user_explained_topics": {"тема": "недавно"}})
    with pytest.raises(ValueError):
        validate_checkpoint_state({"user_explained_topics": {"тема": -1}})
    with pytest.raises(ValueError):
        validate_checkpoint_state({"user_explained_topics": {42: 1}})
