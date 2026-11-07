"""«Собеседник-7»: саморазвитие диалоговых таблиц.

До этой ступени таблицы маркеров расширял только разработчик: каждая
нераспознанная фраза оставалась мёртвой зоной навсегда. Теперь повторная
нераспознанная фраза порождает вопрос-уточнение человеку, и после его
явного подтверждения фраза становится маркером одного из существующих
актов (social / about_self / request). Границы: без автообучения, без
ACT_ANSWER, статические таблицы сильнее обученных, обученное не пишет
в ценности и мотивацию.
"""

from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.dialogue_acts import (
    ACT_ASK_ABOUT_SELF,
    ACT_REQUEST,
    ACT_SOCIAL,
    ACT_UNKNOWN,
    classify_user_text,
)
from src.core.dialogue_learning import (
    BUFFER_MAX,
    PROPOSAL_COOLDOWN_CYCLES,
    DialogueLearning,
)
from src.core.event_bus import Events

PHRASE = "ну ты понимаешь о чём я"


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


def _make_runner(name="Learner"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


def _replies(bus):
    return [
        dict(data or {}) for name, data in bus.published if name == Events.AGENT_MESSAGE
    ]


def _questions(bus):
    return [
        dict(data or {})
        for name, data in bus.published
        if name == Events.AGENT_QUESTION
    ]


async def _say(runner, text):
    await runner._on_user_message(SimpleNamespace(data={"text": text}))


# === Модуль: сбор ===


def test_observe_returns_candidate_on_threshold():
    dl = DialogueLearning()
    assert dl.observe(PHRASE, 10) is None
    assert dl.observe(PHRASE, 11) == PHRASE


def test_observe_normalizes_case_and_spaces():
    dl = DialogueLearning()
    dl.observe("  Ну ТЫ  понимаешь  о чём я ", 1)
    assert dl.observe(PHRASE, 2) == PHRASE


def test_observe_skips_noise_short_long_and_known():
    dl = DialogueLearning()
    assert dl.observe("🙂🙂🙂", 1) is None
    assert dl.observe("🙂🙂🙂", 2) is None
    assert dl.observe("аб", 1) is None
    assert dl.observe("аб", 2) is None
    long_text = "слово " * 30
    assert dl.observe(long_text, 1) is None
    assert dl.observe(long_text, 2) is None
    # выученное и запрещённое не собирается повторно
    dl.resolve(PHRASE, "1", 5)
    assert dl.observe(PHRASE, 6) is None
    dl2 = DialogueLearning()
    dl2.resolve(PHRASE, "не учи", 5)
    assert dl2.observe(PHRASE, 6) is None
    assert dl2.buffer == {}


def test_observe_respects_proposal_cooldown():
    dl = DialogueLearning()
    dl.observe(PHRASE, 0)
    assert dl.observe(PHRASE, 1) == PHRASE
    dl.mark_proposed(2)  # вопрос задан — кулдаун включился
    dl.observe(PHRASE, 3)
    assert dl.observe(PHRASE, 4) is None  # кулдаун не истёк
    dl.observe(PHRASE, 2 + PROPOSAL_COOLDOWN_CYCLES)
    assert dl.observe(PHRASE, 3 + PROPOSAL_COOLDOWN_CYCLES) == PHRASE


def test_buffer_trims_oldest():
    dl = DialogueLearning()
    for index in range(BUFFER_MAX + 5):
        dl.observe(f"фраза номер {index}", index)
    assert len(dl.buffer) == BUFFER_MAX
    assert "фраза номер 0" not in dl.buffer
    assert "фраза номер 1" not in dl.buffer
    assert f"фраза номер {BUFFER_MAX + 4}" in dl.buffer


# === Модуль: предложение и обучающий ответ ===


def test_proposal_carries_phrase_in_context():
    dl = DialogueLearning()
    dl.observe(PHRASE, 1)
    dl.observe(PHRASE, 2)
    proposal = dl.build_proposal(PHRASE, 3)
    assert PHRASE in proposal["question"]
    assert DialogueLearning.is_proposal_context(proposal["context"])
    assert DialogueLearning.phrase_from_context(proposal["context"]) == PHRASE
    # build_proposal кулдаун не ставит: вопрос ещё не задан, ask_user
    # может отказать. Отметка — только через mark_proposed.
    assert dl.last_proposal_cycle == -PROPOSAL_COOLDOWN_CYCLES
    dl.mark_proposed(3)
    assert dl.last_proposal_cycle == 3


def test_resolve_learns_by_digit_and_by_words():
    for answer, expected in (
        ("1", ACT_SOCIAL),
        ("2", ACT_ASK_ABOUT_SELF),
        ("3", ACT_REQUEST),
        ("это обычный разговор", ACT_SOCIAL),
        ("это вопрос к тебе", ACT_ASK_ABOUT_SELF),
        ("это просьба", ACT_REQUEST),
    ):
        dl = DialogueLearning()
        outcome = dl.resolve(PHRASE, answer, 7)
        assert outcome["status"] == "learned", answer
        assert outcome["act"] == expected, answer
        assert dl.learned[PHRASE]["act"] == expected
        assert PHRASE not in dl.buffer


def test_resolve_suppress_wins_over_other_words():
    dl = DialogueLearning()
    outcome = dl.resolve(PHRASE, "4", 7)
    assert outcome["status"] == "suppressed"
    assert PHRASE in dl.suppressed
    # «не учи» сильнее «вопрос» в том же ответе
    dl2 = DialogueLearning()
    outcome2 = dl2.resolve(PHRASE, "не учи, это не вопрос", 7)
    assert outcome2["status"] == "suppressed"


def test_resolve_unclear_answer_teaches_nothing():
    dl = DialogueLearning()
    dl.observe(PHRASE, 1)
    dl.observe(PHRASE, 2)
    outcome = dl.resolve(PHRASE, "сложно сказать что-то", 7)
    assert outcome["status"] == "unclear"
    assert dl.learned == {}
    assert dl.suppressed == {}


# === Модуль: классификатор и приоритеты ===


def test_classifier_uses_learned_markers_after_static():
    dl = DialogueLearning()
    dl.resolve(PHRASE, "1", 1)
    learned = dl.classifier_entries()
    act = classify_user_text(PHRASE, learned=learned)
    assert act.kind == ACT_SOCIAL
    assert act.matched_marker == PHRASE
    # фраза без обучения — по-прежнему unknown
    assert (
        classify_user_text("совсем другие слова", learned=learned).kind == ACT_UNKNOWN
    )
    # вызов без learned — поведение прежнее
    assert classify_user_text(PHRASE).kind == ACT_UNKNOWN


def test_static_tables_win_over_learned():
    learned = {"привет": ACT_REQUEST}
    act = classify_user_text("привет", learned=learned)
    assert act.kind == ACT_SOCIAL  # статика сильнее обученного


def test_classifier_longest_learned_phrase_first():
    dl = DialogueLearning()
    dl.resolve("добрый вечер", "3", 1)
    dl.resolve("добрый вечер друг", "1", 2)
    entries = dl.classifier_entries()
    act = classify_user_text("добрый вечер друг", learned=entries)
    assert act.kind == ACT_SOCIAL  # длинная фраза побеждает свою подстроку


# === Модуль: забвение ===


def test_forget_command_parsing():
    assert DialogueLearning.parse_forget_command("забудь фразу ну ты") == "ну ты"
    assert DialogueLearning.parse_forget_command("Забудь фразу «ну ты»!") == "ну ты"
    assert DialogueLearning.parse_forget_command("забудь фразу") is None
    assert DialogueLearning.parse_forget_command("обычный текст") is None


def test_forget_removes_and_suppresses():
    dl = DialogueLearning()
    dl.resolve(PHRASE, "1", 1)
    assert dl.forget(PHRASE) is True
    assert dl.learned == {}
    assert PHRASE in dl.suppressed
    assert dl.forget(PHRASE) is False  # второй раз — нечего забывать


# === Модуль: сериализация ===


def test_serialization_roundtrip():
    dl = DialogueLearning()
    dl.observe(PHRASE, 10)
    dl.observe(PHRASE, 11)
    dl.build_proposal(PHRASE, 12)
    dl.mark_proposed(12)
    dl.resolve(PHRASE, "2", 13)
    dl.resolve("другая фраза тут", "не учи", 14)

    clone = DialogueLearning()
    clone.load_from(dl.to_dict())
    assert clone.learned == dl.learned
    assert clone.suppressed == dl.suppressed
    assert clone.last_proposal_cycle == 12  # ставится в mark_proposed


def test_load_from_tolerates_corruption():
    dl = DialogueLearning()
    dl.load_from(None)
    dl.load_from({"buffer": "не словарь", "learned": ["не", "словарь"]})
    dl.load_from(
        {
            "buffer": {"фраза": {"count": "мусор"}, "ок": {"count": 2}},
            "learned": {"фраза": {"act": "answer"}, "ок": {"act": "social"}},
            "suppressed": {"фраза": "мусор", "ок": 5},
        }
    )
    assert dl.buffer == {"ок": {"count": 2, "first_cycle": 0, "last_cycle": 0}}
    assert dl.learned == {"ок": {"act": "social", "cycle": 0}}
    assert dl.suppressed == {"ок": 5}


# === Интеграция: контур диалога ===


@pytest.mark.asyncio
async def test_first_unknown_phrase_produces_proposal_question():
    """K13: первая нераспознанная фраза — вопрос-уточнение, не отклик."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction

    await _say(runner, PHRASE)
    pending = ui.get_pending_question()
    assert pending is not None
    assert DialogueLearning.is_proposal_context(pending["context"])
    assert DialogueLearning.phrase_from_context(pending["context"]) == PHRASE
    assert _questions(bus)
    assert _replies(bus) == []


@pytest.mark.asyncio
async def test_teaching_answer_digit_not_swallowed_by_noise_door():
    """«2» — без букв, но это обучающий ответ, а не шум (регрессия)."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    await _say(runner, PHRASE)
    assert ui.get_pending_question() is not None

    await _say(runner, "2")

    assert ui.get_pending_question() is None  # вопрос закрыт
    assert agent.dialogue_learning.learned[PHRASE]["act"] == ACT_ASK_ABOUT_SELF
    contexts = [r["context"] for r in _replies(bus)]
    assert "noise_input" not in contexts
    assert contexts[-1] == "dialogue_learning"


@pytest.mark.asyncio
async def test_learned_social_phrase_routes_to_social_door():
    """Выученная фраза классифицируется и получает социальный отклик."""
    agent, runner, bus = _make_runner()
    await _say(runner, PHRASE)
    await _say(runner, "1")
    assert agent.dialogue_learning.learned[PHRASE]["act"] == ACT_SOCIAL

    await _say(runner, PHRASE)

    assert _replies(bus)[-1]["context"] in {"social_reply", "repeat_protest"}
    assert agent.dialogue_learning.buffer == {}  # не копится снова


@pytest.mark.asyncio
async def test_suppressed_phrase_never_proposed_again():
    """«4 — не учить»: фраза остаётся непонятной, но не переспрашивается."""
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    await _say(runner, PHRASE)
    await _say(runner, "4")

    assert PHRASE in agent.dialogue_learning.suppressed
    assert agent.dialogue_learning.learned == {}
    assert ui.get_pending_question() is None

    questions_before = len(_questions(bus))
    await _say(runner, PHRASE)
    await _say(runner, PHRASE)
    assert len(_questions(bus)) == questions_before  # новых предложений нет
    assert _replies(bus)[-1]["context"] == "unknown_reply"


@pytest.mark.asyncio
async def test_unclear_teaching_answer_learns_nothing():
    agent, runner, bus = _make_runner()
    ui = agent.user_interaction
    await _say(runner, PHRASE)
    await _say(runner, "сложно объяснить это словами")

    assert agent.dialogue_learning.learned == {}
    assert agent.dialogue_learning.suppressed == {}
    assert ui.get_pending_question() is None  # вопрос честно закрыт


@pytest.mark.asyncio
async def test_forget_command_reaches_door_despite_social_marker():
    """«забудь фразу привет» содержит социальный маркер «привет», но
    команда забвения проверяется раньше социальной двери."""
    agent, runner, bus = _make_runner()
    agent.dialogue_learning.learned["моя фраза"] = {
        "act": ACT_SOCIAL,
        "cycle": 1,
    }

    await _say(runner, "забудь фразу моя фраза")

    assert agent.dialogue_learning.learned == {}
    assert "моя фраза" in agent.dialogue_learning.suppressed
    assert _replies(bus)[-1]["context"] == "dialogue_forget"

    await _say(runner, "забудь фразу моя фраза")
    assert "не учила" in _replies(bus)[-1]["content"]


@pytest.mark.asyncio
async def test_no_autolearning_without_confirmation():
    """Без явного ответа человека фраза маркером не становится."""
    agent, runner, bus = _make_runner()
    for _ in range(4):
        await _say(runner, PHRASE)
    assert agent.dialogue_learning.learned == {}
    assert classify_user_text(PHRASE).kind == ACT_UNKNOWN


# === Персистентность ===


def test_dialogue_learning_survives_checkpoint():
    """Выученное переживает рестарт: секция dialogue_learning в чекпоинте."""
    original = DigitalBeing(name="DL1")
    original.dialogue_learning.resolve(PHRASE, "1", 42)
    original.dialogue_learning.resolve("другая фраза тут", "не учи", 43)
    original.dialogue_learning.observe("ещё одна фраза", 44)

    state = build_state_from_agent(original)
    validate_checkpoint_state(state)
    assert state["dialogue_learning"]["learned"][PHRASE]["act"] == ACT_SOCIAL

    restored = DigitalBeing(name="DL2")
    apply_state_to_agent(restored, state)
    learning = restored.dialogue_learning
    assert learning.learned[PHRASE]["act"] == ACT_SOCIAL
    assert "другая фраза тут" in learning.suppressed
    assert "ещё одна фраза" in learning.buffer


def test_old_checkpoint_without_section_restores_cleanly():
    """Чекпоинт без секции dialogue_learning — дефолты, без ошибок."""
    original = DigitalBeing(name="DL3")
    state = build_state_from_agent(original)
    state.pop("dialogue_learning", None)

    restored = DigitalBeing(name="DL4")
    apply_state_to_agent(restored, state)
    assert restored.dialogue_learning.learned == {}
    assert restored.dialogue_learning.buffer == {}


def test_validation_rejects_foreign_act_in_learned():
    """Маркер с необучаемым актом (answer) не пройдёт валидацию."""
    original = DigitalBeing(name="DL5")
    state = build_state_from_agent(original)
    state["dialogue_learning"]["learned"]["фраза"] = {
        "act": "answer",
        "cycle": 1,
    }
    with pytest.raises(ValueError, match="learnable act"):
        validate_checkpoint_state(state)
