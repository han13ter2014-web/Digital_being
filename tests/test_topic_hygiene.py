"""Гигиена тем («Собеседник-5»): метаслова диалога — не темы мира.

До этого этапа пайплайн «Собеседника» сам создавал темы вроде
«вопрос» и «диалог», а потом «исследовал» их и спрашивал человека
про «вопрос» — разговор о разговоре вместо разговора о мире. Теперь:
метаслова не выбираются целями (но остаются изучаемыми из слов
человека), социальные реплики не попадают в темы care-сообщения,
а «ты повторяешься» замьючивает реально заданную тему.
"""

from types import SimpleNamespace

from config.simulation_config import LR_CONFIG
from src.core.agent import DigitalBeing
from src.core.subsystems.proactive_communication import ProactiveCommunication

QUESTION = "Я разбираюсь с темой «вопрос» и пока не уверен, что понимаю её правильно. Можешь объяснить своими словами?"
CONTEXT = "самостоятельный вопрос по теме: вопрос"


class FakeHistory:
    def __init__(self, entries):
        self._entries = entries

    def get_history(self, limit):
        return self._entries[:limit]


# ============================================================
# Метаслова: распознавание
# ============================================================

def test_is_meta_topic_recognizes_dialogue_words():
    agent = DigitalBeing(name="HY")
    assert agent._is_meta_topic("вопрос") is True
    assert agent._is_meta_topic("открытый вопрос") is True
    assert agent._is_meta_topic("вопросы") is True
    assert agent._is_meta_topic("диалог") is True
    assert agent._is_meta_topic("разговоры") is True
    assert agent._is_meta_topic("сообщение") is True


def test_is_meta_topic_keeps_world_words():
    agent = DigitalBeing(name="HY")
    assert agent._is_meta_topic("кот") is False
    # целые слова: «ответственный» — не метаслово «ответ»
    assert agent._is_meta_topic("ответственный") is False
    assert agent._is_meta_topic("простое число") is False


def test_is_meta_topic_empty_string_is_meta():
    agent = DigitalBeing(name="HY")
    assert agent._is_meta_topic("") is True
    assert agent._is_meta_topic(None) is True


# ============================================================
# Метаслова: не выбираются целями исследования
# ============================================================

def _strip_bootstrap(agent):
    for name in list(agent.mental_models.concepts):
        if agent._is_learnable(name):
            del agent.mental_models.concepts[name]


def test_pick_shallow_concept_skips_meta_topics():
    agent = DigitalBeing(name="HY")
    weak = SimpleNamespace(experiences=[1], confidence=0.3)
    concepts = {"вопрос": weak, "диалоги": weak, "кот": weak}
    assert agent._pick_shallow_concept(concepts) == "кот"
    assert agent._pick_shallow_concept({"вопрос": weak}) is None


def test_pick_exploration_target_skips_meta_topics(monkeypatch):
    monkeypatch.setattr(LR_CONFIG, "EXPLORATION_DEPTH_RATIO", 0.0)
    monkeypatch.setattr(LR_CONFIG, "STIMULI_POOL", [])
    agent = DigitalBeing(name="HY")
    _strip_bootstrap(agent)
    weak = SimpleNamespace(experiences=[1], confidence=0.3)
    agent.mental_models.concepts["вопрос"] = weak
    agent.mental_models.concepts["сообщение"] = weak

    assert agent._pick_exploration_target() is None

    agent.mental_models.concepts["кот"] = weak
    assert agent._pick_exploration_target() == "кот"


def test_meta_topic_still_learnable_from_user():
    """Фильтр только в выборе целей: свидетельство человека пишется."""
    agent = DigitalBeing(name="HY")
    returned = agent.record_user_answer("диалог", "обмен репликами", cycle=3)
    assert returned == "диалог"
    assert "диалог" in agent.mental_models.concepts
    assert agent.mental_models.concepts["диалог"].experiences[-1][
        "evidence_kind"
    ] == "testimony"


# ============================================================
# Mute: «ты повторяешься» закрывает реально заданную тему
# ============================================================

def test_mute_topic_stamps_actually_asked_topic():
    agent = DigitalBeing(name="HY")
    agent.user_interaction.ask_user(QUESTION, context=CONTEXT, cycle=1)

    returned = agent.mute_topic("вопрос", cycle=5)

    assert returned == "вопрос"
    assert agent._user_explained_topics == {"вопрос": 5}


def test_mute_topic_refuses_topic_never_asked():
    agent = DigitalBeing(name="HY")

    assert agent.mute_topic("квантовая механика", cycle=5) is None
    assert agent.mute_topic("_внутреннее", cycle=5) is None
    assert agent.mute_topic("", cycle=5) is None
    assert agent._user_explained_topics == {}


def test_muted_topic_is_not_asked_again():
    agent = DigitalBeing(name="HY")
    agent.user_interaction.ask_user(QUESTION, context=CONTEXT, cycle=1)
    assert agent.mute_topic("вопрос", cycle=0) == "вопрос"

    result = agent._act_ask_user(target="вопрос")

    assert "не переспрашиваю" in result.get("text", "")


def test_mute_has_no_concept_testimony():
    """Mute — только штамп тишины, знания из него не появляется."""
    agent = DigitalBeing(name="HY")
    _strip_bootstrap(agent)
    agent.user_interaction.ask_user(QUESTION, context=CONTEXT, cycle=1)

    agent.mute_topic("вопрос", cycle=5)

    assert "вопрос" not in agent.mental_models.concepts


# ============================================================
# Память диалога: социальные реплики — не темы
# ============================================================

def test_recent_dialogue_topics_excludes_social_acts():
    pc = ProactiveCommunication("HY")
    agent = SimpleNamespace(
        user_interaction=FakeHistory([
            {"sender": "agent", "content": "Я изучил тему."},
            {"sender": "user", "content": "Привет! Я рядом с тобой."},
            {
                "sender": "user",
                "content": "Квантовая запутанность и коллапс волновой функции.",
            },
        ])
    )

    topics = pc._recent_dialogue_topics(agent)

    assert len(topics) == 1
    assert topics[0].startswith("Квантовая запутанность")
    assert topics[0].endswith("…")


def test_care_with_promise_quotes_content_not_smalltalk():
    pc = ProactiveCommunication("HY")
    agent = SimpleNamespace(
        user_interaction=FakeHistory([
            {"sender": "user", "content": "Скучаю по тебе, как дела?"},
            {
                "sender": "user",
                "content": "Модуль math умеет логарифмы и тригонометрию.",
            },
        ])
    )

    message = pc._compose_care_with_promise(agent, cycle=100)

    assert message["msg_type"] == "care"
    assert "Модуль math" in message["content"]
    assert "Скучаю по тебе" not in message["content"]
