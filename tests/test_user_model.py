"""UserModel: убеждения о человеке переживают реплики и рестарты.

Этап «Собеседник-2». До него «могу отлучаться надолго — не переживай,
если молчу» испарялось, а детектор тишины тревожился сразу после
ответа пользователя: счётчик контакта получал цикл ВОПРОСА, а не
ответа (user_interaction.py). Здесь проверяются: извлечение обещаний,
честная забота вместо ложной тревоги, счётчик контакта, раунд-трип
чекпоинта и терпимость к повреждённым данным.
"""

from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.subsystems.proactive_communication import ProactiveCommunication
from src.core.user_model import UserModel
from src.perception.user_interaction import UserInteraction


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


# ============================================================
# Извлечение
# ============================================================

def test_agent_has_user_model():
    agent = DigitalBeing(name="UM")
    assert agent.user_model is not None
    assert agent.user_model.promises == {}
    assert agent.user_model.traits == {}


def test_silence_promise_extracted_from_real_phrase():
    um = UserModel()
    recorded = um.observe(
        "Привет! Я рядом. Только учти: могу отлучаться надолго — "
        "не переживай, если молчу.",
        cycle=37,
    )
    assert "silence_tolerance" in recorded["promises"]
    assert um.has_silence_tolerance()
    assert um.silence_promise()["cycle"] == 37
    assert um.last_contact_cycle == 37


@pytest.mark.parametrize(
    "phrase",
    [
        "Не переживай, буду молчать пару дней.",
        "Завтра отлучусь по делам, не жди меня.",
        "Могу долго не писать — не волнуйся.",
    ],
)
def test_silence_promise_variants(phrase):
    um = UserModel()
    um.observe(phrase, cycle=1)
    assert um.has_silence_tolerance(), phrase


def test_traits_extracted_and_contact_updated():
    um = UserModel()
    recorded = um.observe("Я обычно работаю по ночам, я люблю тишину.", cycle=5)
    assert recorded["traits"]
    assert um.traits["я обычно"].startswith("я обычно работаю")
    assert um.last_contact_cycle == 5


def test_plain_text_records_nothing_and_keeps_contact_untouched():
    um = UserModel()
    um.observe("Тишина и покой.", cycle=3)
    assert um.promises == {}
    assert um.traits == {}
    assert um.last_contact_cycle is None


def test_latest_promise_overwrites_kind():
    um = UserModel()
    um.observe("Не переживай, буду молчать.", cycle=1)
    um.observe("Не переживай, отлучусь на неделю.", cycle=2)
    assert um.silence_promise()["cycle"] == 2
    assert "отлучусь" in um.silence_promise()["text"]


# ============================================================
# Сериализация
# ============================================================

def test_roundtrip_preserves_promises_and_traits():
    um = UserModel()
    um.observe("Не переживай, могу отлучаться надолго.", cycle=11)
    um.observe("Я учусь на программиста.", cycle=12)
    um.note_contact(15)

    restored = UserModel()
    restored.load_from(um.to_dict())

    assert restored.has_silence_tolerance()
    assert restored.silence_promise() == um.silence_promise()
    assert restored.traits == um.traits
    assert restored.last_contact_cycle == 15


def test_load_from_tolerates_garbage():
    um = UserModel()
    um.load_from(None)
    um.load_from("мусор")
    um.load_from({"promises": {"silence_tolerance": "не словарь"}})
    um.load_from({"traits": {"я обычно": 42}})
    um.load_from({"last_contact_cycle": "не число"})
    assert um.promises == {}
    assert um.traits == {}
    assert um.last_contact_cycle is None


# ============================================================
# Счётчик контакта: цикл ответа, а не цикл вопроса
# ============================================================

def test_submit_answer_records_answer_cycle_not_question_cycle():
    ui = UserInteraction(agent_name="T")
    assert ui.ask_user("Что такое время?", context="", cycle=5).get("status") == "queued"

    ui.submit_answer(1, "Идёт, пока мы говорим.", cycle=60)
    assert ui.get_last_user_message_cycle() == 60


def test_submit_answer_without_cycle_keeps_legacy_behavior():
    ui = UserInteraction(agent_name="T")
    ui.ask_user("Что такое время?", context="", cycle=5)
    ui.submit_answer(1, "Идёт.")
    assert ui.get_last_user_message_cycle() == 5


# ============================================================
# Забота с учётом обещания
# ============================================================

def _communication(agent, cycle, last_user_cycle):
    ui = UserInteraction(agent_name="T")
    ui._last_user_message_cycle = last_user_cycle
    pc = ProactiveCommunication(
        agent_name="T", user_interaction=ui, attachment=None
    )
    return pc.maybe_initiate(
        agent=agent,
        cycle=cycle,
        user_context={"should_interrupt": True},
    )


def test_silence_with_promise_is_care_not_alarm():
    um = UserModel()
    um.observe("Не переживай, могу отлучаться надолго.", cycle=1)
    agent = SimpleNamespace(user_model=um)

    msg = _communication(agent, cycle=100, last_user_cycle=40)

    assert msg is not None
    assert msg["context"] == "silence_with_promise"
    assert "не тревожу" in msg["content"]


def test_silence_without_promise_keeps_alarm():
    agent = SimpleNamespace(user_model=UserModel())
    msg = _communication(agent, cycle=100, last_user_cycle=40)

    assert msg is not None
    assert msg["context"] == "silence_detected"


# ============================================================
# Интеграция: социальная реплика через раннер наполняет модель
# ============================================================

@pytest.mark.asyncio
async def test_social_message_through_runner_fills_user_model():
    from types import SimpleNamespace as NS

    agent = DigitalBeing(name="UMRoute")
    runner = AgentRunner(agent, RecordingBus())

    await runner._on_user_message(
        NS(data={"text": "Могу долго не писать — не переживай, если молчу."})
    )

    assert agent.user_model.has_silence_tolerance()
    assert agent.user_model.last_contact_cycle == agent.cycle_count
