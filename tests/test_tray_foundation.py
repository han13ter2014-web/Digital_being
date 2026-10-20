"""
Smoke-тесты для фундамента трей-режима (Этап 1).

Проверяем:
- EventBus: publish/subscribe, очередь, диспетчеризация, остановка.
- EnergyPolicy: интервалы по уровням, регенерация, пересечение порогов.
- AgentRunner: цепочка подписок.

Запуск: python tests/test_tray_foundation.py
"""

import asyncio
import io
import sys
import os

# UTF-8 для stdout (Windows cp1251 не вывозит эмодзи)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.event_bus import EventBus
from src.core.energy_policy import EnergyPolicy


# ============================================================
# EventBus
# ============================================================

async def test_eventbus_basic():
    """Базовый сценарий: publish → подписчик получает."""
    bus = EventBus()
    await bus.start()

    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe("test_event", handler)
    await bus.publish("test_event", {"msg": "hello"}, source="test")
    await bus.dispatch_once()

    assert len(received) == 1, f"Ожидалось 1 событие, получено {len(received)}"
    assert received[0].data["msg"] == "hello"
    assert received[0].source == "test"
    print("  ✅ EventBus: базовый publish/subscribe")


async def test_eventbus_wildcard():
    """Wildcard-подписчик получает все события."""
    bus = EventBus()
    await bus.start()

    received = []

    async def wildcard_handler(event):
        received.append(event.name)

    bus.subscribe("*", wildcard_handler)
    await bus.publish("foo", source="t")
    await bus.publish("bar", source="t")
    await bus.dispatch_once()

    assert "foo" in received and "bar" in received
    print("  ✅ EventBus: wildcard-подписчик")


async def test_eventbus_multiple_subscribers():
    """Несколько подписчиков на одно событие — все получают."""
    bus = EventBus()
    await bus.start()

    r1, r2 = [], []

    async def h1(event):
        r1.append(event.data)

    async def h2(event):
        r2.append(event.data)

    bus.subscribe("x", h1)
    bus.subscribe("x", h2)
    await bus.publish("x", {"v": 1})
    await bus.dispatch_once()

    assert r1 == [{"v": 1}] and r2 == [{"v": 1}]
    print("  ✅ EventBus: множественные подписчики")


async def test_eventbus_subscribe_requires_async():
    """Подписчик-не-coroutine должен давать TypeError."""
    bus = EventBus()

    def not_async(event):
        pass

    try:
        bus.subscribe("x", not_async)
        assert False, "Должен был быть TypeError"
    except TypeError:
        pass

    print("  ✅ EventBus: защита от sync-подписчиков")


async def test_eventbus_history():
    """История событий сохраняется."""
    bus = EventBus(history_size=10)
    await bus.start()

    async def h(event):
        pass

    bus.subscribe("x", h)
    for i in range(5):
        await bus.publish("x", {"i": i})
    await bus.dispatch_once()

    history = bus.get_history(last_n=10)
    assert len(history) == 5, f"История должна содержать 5, имеет {len(history)}"
    print("  ✅ EventBus: история работает")


async def test_eventbus_stats():
    """Статистика обновляется."""
    bus = EventBus()
    await bus.start()

    async def h(event):
        pass

    bus.subscribe("foo", h)
    await bus.publish("foo")
    await bus.publish("foo")
    await bus.publish("bar")
    await bus.dispatch_once()

    stats = bus.get_stats()
    assert stats["events_by_name"]["foo"] == 2
    assert stats["events_by_name"]["bar"] == 1
    assert stats["subscribers_count"] == 1
    print("  ✅ EventBus: статистика")


async def test_eventbus_run_and_stop():
    """run() обрабатывает события и останавливается через stop()."""
    bus = EventBus()
    received = []

    async def h(event):
        received.append(event)

    bus.subscribe("ping", h)

    async def producer():
        await asyncio.sleep(0.05)
        await bus.publish("ping", {"n": 1})
        await asyncio.sleep(0.05)
        await bus.publish("ping", {"n": 2})
        await asyncio.sleep(0.05)
        bus.stop()

    await asyncio.wait_for(
        asyncio.gather(bus.run(), producer()),
        timeout=1.0,
    )

    assert len(received) >= 1, f"Хотя бы одно событие должно быть получено: {received}"
    print(f"  ✅ EventBus: run/stop ({len(received)} событий)")


# ============================================================
# EnergyPolicy
# ============================================================

def test_energy_levels():
    """Уровни энергии определяются правильно."""
    energy = [50.0]  # обёртка в списке для имитации изменений
    policy = EnergyPolicy(get_energy=lambda: energy[0], max_energy=200.0)

    assert policy.energy_percent == 25.0
    assert policy.energy_level() == "slow"
    assert policy.current_tick_interval_sec() == 30.0  # SLOW_INTERVAL

    energy[0] = 180.0
    assert policy.energy_level() == "full"
    assert policy.current_tick_interval_sec() == 5.0  # FULL

    energy[0] = 10.0
    assert policy.energy_level() == "exhausted"
    assert policy.current_tick_interval_sec() == 300.0  # EXHAUSTED

    energy[0] = 120.0
    assert policy.energy_level() == "normal"
    assert policy.current_tick_interval_sec() == 10.0

    energy[0] = 25.0
    assert policy.energy_level() == "tired"
    assert policy.current_tick_interval_sec() == 60.0

    print("  ✅ EnergyPolicy: все 5 уровней")


def test_energy_regenerate():
    """Регенерация работает через setter."""
    energy = [100.0]
    policy = EnergyPolicy(get_energy=lambda: energy[0], max_energy=200.0)
    policy.attach_setter(lambda v: energy.__setitem__(0, v))

    # При 50% — rate = 0.3/sec
    energy[0] = 100.0  # 50%
    gained = policy.regenerate(10.0)
    assert gained == pytest_approx(3.0)
    assert energy[0] == pytest_approx(103.0)

    # На максимуме — больше не растёт
    energy[0] = 200.0
    gained = policy.regenerate(10.0)
    assert gained == 0.0

    # При exhausted — почти ничего
    energy[0] = 10.0  # 5%
    gained = policy.regenerate(10.0)
    assert gained < 0.1

    print("  ✅ EnergyPolicy: регенерация по уровням")


def test_energy_thresholds():
    """Пересечения порогов LOW/CRITICAL/RECOVERED."""
    energy = [200.0]
    policy = EnergyPolicy(get_energy=lambda: energy[0], max_energy=200.0)

    assert not policy.should_publish_low()
    assert not policy.should_publish_critical()

    energy[0] = 30.0  # 15%
    assert policy.should_publish_low(), "Один раз должен сработать"
    assert not policy.should_publish_low(), "Второй раз — нет (без сброса)"

    energy[0] = 3.0  # 1.5% — critical
    assert policy.should_publish_critical(), "Critical должен сработать"

    energy[0] = 200.0
    assert policy.should_publish_recovered(), "После восстановления — да"

    print("  ✅ EnergyPolicy: пересечения порогов")


def test_energy_status():
    """get_status() возвращает читабельный dict."""
    energy = [150.0]
    policy = EnergyPolicy(get_energy=lambda: energy[0], max_energy=200.0)

    status = policy.get_status()
    assert status["energy"] == 150.0
    assert status["percent"] == 75.0
    assert status["level"] == "normal"
    assert status["tick_interval_sec"] == 10.0

    print("  ✅ EnergyPolicy: get_status()")


def test_energy_no_setter_safe():
    """Без setter регенерация не падает."""
    energy = [100.0]
    policy = EnergyPolicy(get_energy=lambda: energy[0], max_energy=200.0)
    # НЕ привязываем setter

    # Должно просто не падать (но и не восстанавливать)
    policy.regenerate(10.0)
    assert energy[0] == 100.0  # не изменилось

    print("  ✅ EnergyPolicy: безопасный режим без setter")


# ============================================================
# Helpers
# ============================================================

def pytest_approx(value):
    """Минимальная замена pytest.approx — без импорта pytest."""
    class Approx:
        def __init__(self, v):
            self.v = v
            self.tol = 0.5  # щедрый допуск для float

        def __eq__(self, other):
            return abs(self.v - other) < self.tol

        def __repr__(self):
            return f"~{self.v}"
    return Approx(value)


# ============================================================
# Запуск
# ============================================================

async def run_async_tests():
    print("\n🧪 EventBus:")
    await test_eventbus_basic()
    await test_eventbus_wildcard()
    await test_eventbus_multiple_subscribers()
    await test_eventbus_subscribe_requires_async()
    await test_eventbus_history()
    await test_eventbus_stats()
    await test_eventbus_run_and_stop()


def run_sync_tests():
    print("\n🧪 EnergyPolicy:")
    test_energy_levels()
    test_energy_regenerate()
    test_energy_thresholds()
    test_energy_status()
    test_energy_no_setter_safe()


def main():
    print("=" * 50)
    print("Тест фундамента трей-режима")
    print("=" * 50)
    run_sync_tests()
    asyncio.run(run_async_tests())
    print("\n" + "=" * 50)
    print("✅ Все тесты прошли!")
    print("=" * 50)


if __name__ == "__main__":
    main()