"""Тесты управляемой скорости жизни (этап C).

Проверяем то, что раньше было невозможно: менять темп жизни на лету,
делать один шаг по кнопке и честно называть ускорение ускорением.

До этапа C интервал был захардкожен как ``max(5.0, energy, 1.0)``,
поэтому трей физически не мог работать быстрее 5 секунд на цикл,
а консольный main.py успевал тысячи циклов в секунду — две разные
программы вместо одного существа с разным темпом.
"""

import asyncio
import time

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus, Events


@pytest.fixture()
def runtime():
    """Агент + шина + раннер, как в реальном запуске."""
    from src.core.paths import data_path
    import os

    for name in ("life_state.json", "life_requests.json"):
        try:
            os.unlink(data_path(name))
        except OSError:
            pass

    agent = DigitalBeing(name="SpeedTest")
    # Тесты не должны ходить в сеть: исследование теперь реально думает
    # и могло бы ждать Wikipedia по rate-limit.
    searcher = getattr(agent, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    bus = EventBus(max_queue_size=200, history_size=100)
    runner = AgentRunner(agent, bus, name="SpeedRunner")
    return agent, bus, runner


# ============================================================
# 1. Режимы и интервалы
# ============================================================


def test_available_speeds_include_step(runtime):
    _, _, runner = runtime
    speeds = runner.available_speeds()
    assert "live" in speeds
    assert "fast" in speeds
    assert "max" in speeds
    assert "step" in speeds


def test_default_speed_is_live(runtime):
    _, _, runner = runtime
    assert runner.get_speed_status()["mode"] == "live"


def test_set_speed_changes_interval(runtime):
    _, _, runner = runtime

    live = runner.set_speed("live")
    fast = runner.set_speed("fast")
    lab = runner.set_speed("max")

    assert live["interval_sec"] == 5.0
    assert fast["interval_sec"] == 0.5
    assert lab["interval_sec"] == 0.0
    # Ускорение действительно быстрее жизни.
    assert fast["effective_interval_sec"] < live["effective_interval_sec"]


def test_fast_mode_ignores_energy_dilation(runtime):
    """В fast явный выбор человека важнее усталости.

    Раньше энергополитика возвращала 5–120 секунд, и «ускорение»
    ничего не ускоряло.
    """
    _, _, runner = runtime
    runner.set_speed("fast")
    # Имитируем полное истощение: политика просила бы долгую паузу.
    runner.energy_policy.energy_level = lambda: "exhausted"

    assert runner.current_interval_sec() == 0.5


def test_live_mode_still_respects_energy(runtime):
    """В live усталость по-прежнему замедляет — это и есть жизнь."""
    _, _, runner = runtime
    runner.set_speed("live")
    runner.energy_policy.current_tick_interval_sec = lambda: 60.0

    assert runner.current_interval_sec() >= 60.0


def test_unknown_speed_is_rejected(runtime):
    _, _, runner = runtime
    with pytest.raises(ValueError, match="неизвестный режим"):
        runner.set_speed("turbo")


def test_speed_status_shape(runtime):
    _, _, runner = runtime
    status = runner.get_speed_status()
    for key in (
        "mode",
        "interval_sec",
        "effective_interval_sec",
        "paused",
        "accelerated_cycles",
        "available_modes",
    ):
        assert key in status


# ============================================================
# 2. Скорость меняется через шину (так делает окно)
# ============================================================


def test_speed_change_event(runtime):
    _, bus, runner = runtime

    class Event:
        data = {"mode": "fast"}

    asyncio.run(runner._on_speed_changed(Event()))
    assert runner.get_speed_status()["mode"] == "fast"


def test_invalid_speed_event_is_ignored(runtime):
    _, bus, runner = runtime

    class Event:
        data = {"mode": "несуществующий"}

    # Не падаем и не меняем режим.
    asyncio.run(runner._on_speed_changed(Event()))
    assert runner.get_speed_status()["mode"] == "live"


# ============================================================
# 3. Шаг по кнопке
# ============================================================


def test_step_requires_running_runner(runtime):
    _, _, runner = runtime
    assert asyncio.run(runner.step_once()) is False


def test_step_once_advances_exactly_one_cycle(runtime):
    agent, bus, runner = runtime
    runner._running = True
    runner._pending_user_messages = asyncio.Queue()

    before = agent.cycle_count
    assert asyncio.run(runner.step_once()) is True
    assert agent.cycle_count == before + 1


def test_step_works_while_paused(runtime):
    """Шаг — осознанное действие, пауза ему не мешает."""
    agent, bus, runner = runtime
    runner._running = True
    runner._paused = True
    runner._pending_user_messages = asyncio.Queue()

    before = agent.cycle_count
    asyncio.run(runner.step_once())
    assert agent.cycle_count == before + 1
    # Пауза не снялась.
    assert runner._paused is True


def test_step_in_step_mode_does_not_free_run(runtime):
    """В режиме step внешний цикл не крутит жизнь сам."""
    agent, bus, runner = runtime
    runner._running = True
    runner._pending_user_messages = asyncio.Queue()
    runner.set_speed("step")

    before = agent.cycle_count
    asyncio.run(runner._one_iteration())
    # Один вызов внешнего цикла не должен давать тик.
    assert agent.cycle_count == before


# ============================================================
# 4. Ускоренные циклы помечаются
# ============================================================


def test_max_mode_counts_accelerated_cycles(runtime):
    agent, bus, runner = runtime
    runner._running = True
    runner._pending_user_messages = asyncio.Queue()
    runner.set_speed("max")

    asyncio.run(runner.step_once())
    asyncio.run(runner.step_once())

    status = runner.get_speed_status()
    assert status["accelerated_cycles"] == 2


def test_live_mode_does_not_mark_cycles_accelerated(runtime):
    agent, bus, runner = runtime
    runner._running = True
    runner._pending_user_messages = asyncio.Queue()
    runner.set_speed("live")

    asyncio.run(runner.step_once())
    assert runner.get_speed_status()["accelerated_cycles"] == 0


# ============================================================
# 5. Цикл не удваивает интервал
# ============================================================


def test_tick_does_not_double_interval(runtime):
    """Ожидание сообщения и sleep не складываются.

    Тик уже тратит время на ожидание, поэтому досыпается только остаток
    интервала. Проверяем именно троттл: подменяем тик на заведомо
    известную задержку, иначе тест мерил бы скорость мышления, а не паузу.
    """
    agent, bus, runner = runtime
    runner._running = True
    runner._pending_user_messages = asyncio.Queue()
    runner.set_speed("fast")

    async def fake_tick(*, wait_for_user=True):
        await asyncio.sleep(0.3)  # тик сам занимает 0.3 с

    runner._tick_once = fake_tick

    started = time.time()
    asyncio.run(runner._one_iteration())
    elapsed = time.time() - started

    # 0.3 работы + остаток 0.2 = ~0.5 с. Если бы пауза добавлялась
    # целиком, вышло бы ~0.8 с.
    assert 0.4 <= elapsed < 0.75
