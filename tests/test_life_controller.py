"""Тесты LifeController: окно не может убить агента, даже если захочет.

Проверяется связка «окно → контроллер → LifeGuard» целиком, без Tk.
"""

import asyncio

import pytest

from src.app.life_controller import LifeController
from src.core.agent import DigitalBeing
from src.core.event_bus import Events
from src.core.life_guard import get_policy


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class Event:
    """Минимальное событие для прямого вызова обработчика."""

    def __init__(self, data=None, source="test"):
        self.data = data or {}
        self.source = source


class RecordingBus:
    """Шина-заглушка: записывает публикации.

    Настоящая шина требует ``await start()`` и отбрасывает события до
    запуска. Здесь важна не доставка подписчикам, а то, *что именно*
    контроллер отправил окну.
    """

    def __init__(self):
        self.published = []

    def subscribe(self, *args, **kwargs):
        return None

    def unsubscribe(self, *args, **kwargs):
        return None

    async def publish(self, event, data=None, **kwargs):
        self.published.append((event, dict(data or {})))

    def publish_sync(self, event, data=None, **kwargs):
        self.published.append((event, dict(data or {})))


@pytest.fixture()
def env():
    """Агент, шина и контроллер. Состояние жизни сброшено."""
    from src.core.paths import data_path
    import os

    for name in ("life_state.json", "life_requests.json"):
        try:
            os.unlink(data_path(name))
        except OSError:
            pass

    agent = DigitalBeing(name="CtrlTest")
    agent.life_guard.clock = FakeClock()
    bus = RecordingBus()
    controller = LifeController(agent, bus)
    return agent, bus, controller


def run(coro):
    return asyncio.run(coro)


def published(bus, event_name):
    """Данные всех публикаций данного типа, по порядку."""
    return [data for name, data in bus.published if name == event_name]


# ============================================================
# 1. Запрос не убивает
# ============================================================


def test_request_creates_prompt_not_death(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "dream"})))

    assert agent.is_alive() is True
    prompts = published(bus, Events.LIFE_PROMPT)
    assert prompts, "окно не получило инструкцию по подтверждению"
    assert prompts[-1]["kind"] == "dream"
    assert prompts[-1]["phrase"] == "CtrlTest"


def test_request_shows_cooldown_and_description(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "dream"})))

    data = published(bus, Events.LIFE_PROMPT)[-1]
    assert float(data["cooldown_sec"]) > 0
    assert data["description"]
    assert data["reversible"] is True


def test_unknown_kind_is_rejected_quietly(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "explode"})))

    assert agent.is_alive() is True
    results = published(bus, Events.LIFE_RESULT)
    assert results and results[-1]["ok"] is False


# ============================================================
# 2. Подтверждение проходит через LifeGuard
# ============================================================


def test_confirm_too_early_is_refused(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "dream"})))
    request_id = published(bus, Events.LIFE_PROMPT)[-1]["request_id"]

    run(controller._on_confirm(
        Event({"request_id": request_id, "phrase": "CtrlTest"})
    ))

    assert agent.is_alive() is True
    result = published(bus, Events.LIFE_RESULT)[-1]
    assert result["ok"] is False
    assert "Слишком рано" in result["message"]


def test_confirm_wrong_phrase_is_refused(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "dream"})))
    request_id = published(bus, Events.LIFE_PROMPT)[-1]["request_id"]
    agent.life_guard.clock.advance(get_policy("dream").cooldown_sec + 1)

    run(controller._on_confirm(
        Event({"request_id": request_id, "phrase": "да"})
    ))

    assert agent.is_alive() is True
    assert published(bus, Events.LIFE_RESULT)[-1]["ok"] is False


def test_confirm_correct_phrase_sleeps_agent(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "dream"})))
    request_id = published(bus, Events.LIFE_PROMPT)[-1]["request_id"]
    agent.life_guard.clock.advance(get_policy("dream").cooldown_sec + 1)

    run(controller._on_confirm(
        Event({"request_id": request_id, "phrase": "CtrlTest"})
    ))

    assert agent.is_alive() is False
    result = published(bus, Events.LIFE_RESULT)[-1]
    assert result["ok"] is True
    assert "Семя" in result["message"]


def test_confirm_unknown_request_is_refused(env):
    agent, bus, controller = env
    run(controller._on_confirm(
        Event({"request_id": "нет-такого", "phrase": "CtrlTest"})
    ))
    assert agent.is_alive() is True


# ============================================================
# 3. Отмена работает всегда
# ============================================================


def test_cancel_keeps_agent_alive(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "terminate"})))
    request_id = published(bus, Events.LIFE_PROMPT)[-1]["request_id"]

    run(controller._on_cancel(Event({"request_id": request_id})))

    assert agent.is_alive() is True
    result = published(bus, Events.LIFE_RESULT)[-1]
    assert result["ok"] is True


def test_cancel_unknown_request_reports(env):
    agent, bus, controller = env
    run(controller._on_cancel(Event({"request_id": "нет-такого"})))
    assert published(bus, Events.LIFE_RESULT)[-1]["ok"] is False


# ============================================================
# 4. Пробуждение
# ============================================================


def test_wake_after_dream(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "dream"})))
    request_id = published(bus, Events.LIFE_PROMPT)[-1]["request_id"]
    agent.life_guard.clock.advance(get_policy("dream").cooldown_sec + 1)
    run(controller._on_confirm(
        Event({"request_id": request_id, "phrase": "CtrlTest"})
    ))
    assert agent.is_alive() is False

    run(controller._on_wake(Event({})))

    assert agent.is_alive() is True
    assert published(bus, Events.LIFE_RESULT)[-1]["ok"] is True


# ============================================================
# 5. Необратимый уход требует полной фразы
# ============================================================


def test_termination_requires_full_phrase(env):
    agent, bus, controller = env
    run(controller._on_request(Event({"kind": "terminate"})))
    request_id = published(bus, Events.LIFE_PROMPT)[-1]["request_id"]
    agent.life_guard.clock.advance(get_policy("terminate").cooldown_sec + 1)

    # Без «НАВСЕГДА» — отказ.
    run(controller._on_confirm(
        Event({"request_id": request_id, "phrase": "CtrlTest"})
    ))
    assert agent.is_alive() is True

    run(controller._on_confirm(
        Event({"request_id": request_id, "phrase": "CtrlTest НАВСЕГДА"})
    ))
    assert agent.is_alive() is False