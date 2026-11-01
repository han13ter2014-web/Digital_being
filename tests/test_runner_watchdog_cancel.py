"""П.6 — отмена цикла не оставляет watchdog с незакрытым циклом.

``CancelledError`` — BaseException: прежний «except Exception» рядом с
циклом агента его не ловил. Отмена на середине цикла (пауза, остановка,
закрытие приложения) пропускала ``watchdog.on_cycle_end()``: отметка
старта становилась мёртвой, и следующий ``on_cycle_end`` считал время
от неё, рождая ложные slow_cycle-алерты.

Теперь закрытие цикла — в ``finally``: оно происходит в любой развилке.
"""

import asyncio
import os

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner, PersistentMessageQueue
from src.core.event_bus import EventBus
from src.core.watchdog import Watchdog


@pytest.fixture()
def runtime():
    """Агент + шина + раннер, как в реальном запуске (см. test_runner_speed)."""
    from src.core.paths import data_path

    for name in ("life_state.json", "life_requests.json"):
        try:
            os.unlink(data_path(name))
        except OSError:
            pass

    agent = DigitalBeing(name="WatchdogCancelTest")
    searcher = getattr(agent, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    bus = EventBus(max_queue_size=200, history_size=100)
    # Свежий watchdog вместо глобального синглтона: ассерты изолированы.
    runner = AgentRunner(
        agent, bus, watchdog=Watchdog(), name="WatchdogCancelRunner"
    )
    # Очередь сообщений создаётся лениво в start() — здесь нужен сразу.
    runner._pending_user_messages = PersistentMessageQueue(agent)
    return agent, bus, runner


def _cancel_in_worker(runner):
    """Цикл агента «отменяют» в worker-потоке — как при остановке раннера."""

    def cancelled_cycle(*args, **kwargs):
        # asyncio.to_thread прокидывает исключение потока в ожидающую
        # корутину — await получает настоящую CancelledError.
        raise asyncio.CancelledError()

    runner._do_one_agent_cycle = cancelled_cycle


async def test_cancelled_cycle_still_closes_for_watchdog(runtime):
    agent, bus, runner = runtime
    # Свежий агент получает None из _next_stimulus и уходит в отдых —
    # форсируем стимул, чтобы выполнялся именно цикл агента.
    runner._next_stimulus = lambda: "стимул для отмены"
    _cancel_in_worker(runner)

    with pytest.raises(asyncio.CancelledError):
        await runner._tick_once(wait_for_user=False)

    # Цикл закрыт: мёртвой отметки старта нет.
    assert runner.watchdog._last_cycle_started is None


async def test_normal_cycle_closes_watchdog_exactly_once(runtime):
    agent, bus, runner = runtime

    await runner._tick_once(wait_for_user=False)

    assert runner.watchdog._last_cycle_started is None
    # finally — единственный владелец закрытия: повторный end при
    # незакрытом цикле изменил бы _cycle_count или алерты, а guard
    # on_cycle_end при закрытом цикле — нет.
    assert runner.watchdog.get_status()["cycle_count"] >= 1


async def test_cancelled_wait_still_closes_watchdog(runtime):
    agent, bus, runner = runtime
    runner.current_interval_sec = lambda: 30  # ждём сообщение — await-точка
    task = asyncio.ensure_future(runner._tick_once(wait_for_user=True))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert runner.watchdog._last_cycle_started is None
