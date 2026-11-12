"""
test_lazy_user_queue.py — ленивое создание _pending_user_messages.

Исторический контракт (до «Собеседник-6»): нераспознанные сообщения
складывались в очередь стимулов и изучались как темы. С «Собеседника-6»
нераспознанный текст получает честный диалоговый отклик и НЕ заводится
темой: продюсера у очереди больше нет, она создаётся в ``start()`` и
остаётся пустой (потребитель в тике сохранён как legacy-путь).

Текущий контракт:
1. Нераспознанное сообщение до start() обрабатывается дверями
   синхронно: честный отклик, очередь не создаётся.
2. Несколько сообщений до start() — каждое получает отклик, порядок
   сохраняется, очередь не создаётся.
3. start() создаёт очередь и НЕ пересоздаёт её при сообщениях.
4. Пустые сообщения и data=None игнорируются.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

from src.core.event_bus import Events

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================
# Fake Agent (минимальный)
# ============================================================
class FakeEnergyPolicy:
    def __init__(self, energy=100.0):
        self._energy = energy

    def current_tick_interval_sec(self):
        return 1.0

    def regenerate(self, dt):
        pass

    def get_status(self):
        return {
            "energy": self._energy,
            "max_energy": 200,
            "percent": self._energy / 200 * 100,
            "level": "normal",
            "tick_interval_sec": 1.0,
        }

    def attach_setter(self, setter):
        self._setter = setter

    @property
    def energy_percent(self):
        return self._energy / 200 * 100

    def should_publish_critical(self):
        return False

    def should_publish_low(self):
        return False

    def should_publish_recovered(self):
        return False


class FakeAgent:
    def __init__(self, name="Test", energy=100.0):
        self.name = name
        self.energy = energy
        self.cycle_count = 0
        self.intelligence = 1
        # MentalModels с concepts dict
        self.mental_models = MagicMock()
        self.mental_models.concepts = {}
        self.energy_subsystem = MagicMock()
        self.energy_subsystem.energy = energy

    def perceive(self, stimulus):
        return stimulus

    def think(self, perceived):
        return f"Thought on '{perceived}'"

    def act(self, thought):
        return f"Action: {thought}"

    def evolve(self):
        pass

    def get_full_state(self):
        return {"agent": {"name": self.name, "energy": self.energy}}

    def get_goals_status(self):
        return {"active": "", "completed": 0, "total": 0}

    def get_mental_models_status(self):
        return {"total_concepts": 0, "concepts_with_high_confidence": 0}


class FakeBus:
    """Минимальная имитация EventBus для тестов."""

    def __init__(self):
        self.published = []

    def subscribe(self, event_name, callback):
        pass

    async def publish(self, name, data=None, **kwargs):
        """Async-публикация, как у настоящего EventBus."""
        self.published.append({"name": name, "data": data, **kwargs})

    def publish_sync(self, name, data=None, **kwargs):
        self.published.append({"name": name, "data": data, **kwargs})


# ============================================================
# Импорт AgentRunner
# ============================================================
def _make_runner():
    from src.core.agent_runner import AgentRunner

    agent = FakeAgent()
    bus = FakeBus()
    runner = AgentRunner(agent, bus)
    return runner, agent, bus


# ============================================================
# Тесты
# ============================================================
@pytest.mark.asyncio
async def test_message_before_start_gets_honest_reply_not_queue():
    """Сообщение до start() обработано дверями, а не очередью стимулов.

    «Собеседник-6»: нераспознанный текст получает честный диалоговый
    отклик и не заводится темой для изучения — очередь не создаётся.
    """
    runner, agent, bus = _make_runner()

    # До start() — очереди НЕТ.
    assert (
        not hasattr(runner, "_pending_user_messages")
        or runner._pending_user_messages is None
    )

    # Имитируем получение user_message ДО start().
    event = MagicMock()
    event.data = {"text": "анализ распределённых систем"}
    await runner._on_user_message(event)

    # Очередь не создалась: продюсера у неё больше нет.
    assert (
        not hasattr(runner, "_pending_user_messages")
        or runner._pending_user_messages is None
        or runner._pending_user_messages.empty()
    )
    # Сообщение не потеряно — получен честный отклик.
    thoughts = [p for p in bus.published if p["name"] == Events.AGENT_THOUGHT]
    assert any("не понимаю" in (p["data"] or {}).get("text", "") for p in thoughts)


@pytest.mark.asyncio
async def test_multiple_messages_before_start_each_gets_reply():
    """Несколько сообщений до start() — каждое получает отклик по порядку."""
    runner, agent, bus = _make_runner()

    msgs = ["первое непонятное", "второе непонятное", "третье непонятное"]
    for m in msgs:
        event = MagicMock()
        event.data = {"text": m}
        await runner._on_user_message(event)

    # Каждое сообщение обработано дверями: три отклика, очереди нет.
    thoughts = [p for p in bus.published if p["name"] == Events.AGENT_THOUGHT]
    replies = [(p["data"] or {}).get("text", "") for p in thoughts]
    assert len(replies) == len(msgs)
    assert (
        not hasattr(runner, "_pending_user_messages")
        or runner._pending_user_messages is None
        or runner._pending_user_messages.empty()
    )


@pytest.mark.asyncio
async def test_start_does_not_recreate_queue_on_messages():
    """start() создаёт очередь; сообщения её не пересоздают."""
    runner, agent, bus = _make_runner()

    await runner.start()
    queue_before = runner._pending_user_messages
    assert queue_before is not None

    event = MagicMock()
    event.data = {"text": "до старта непонятное"}
    await runner._on_user_message(event)

    queue_after = runner._pending_user_messages
    assert (
        queue_after is queue_before
    ), "очередь пересоздалась на сообщении — legacy-потребитель сломан!"
    # Очередь остаётся пустой: нераспознанное в стимулы не идёт.
    assert queue_after.empty()

    # Cleanup.
    await runner.stop()


@pytest.mark.asyncio
async def test_start_creates_queue_if_not_exist():
    """start() создаёт очередь, если сообщений до этого не было."""
    runner, agent, bus = _make_runner()

    # Очереди нет.
    assert (
        not hasattr(runner, "_pending_user_messages")
        or runner._pending_user_messages is None
    )

    await runner.start()
    # Очередь создана.
    assert runner._pending_user_messages is not None
    # И пуста (никто не успел отправить).
    assert runner._pending_user_messages.empty()

    # Cleanup.
    await runner.stop()


@pytest.mark.asyncio
async def test_empty_message_ignored():
    """Пустое сообщение не ставится в очередь."""
    runner, agent, bus = _make_runner()

    event = MagicMock()
    event.data = {"text": ""}
    await runner._on_user_message(event)
    # Очередь даже не создаётся.
    assert (
        not hasattr(runner, "_pending_user_messages")
        or runner._pending_user_messages is None
        or runner._pending_user_messages.empty()
    )

    # Cleanup.
    await runner.stop()


@pytest.mark.asyncio
async def test_message_with_none_data_ignored():
    """event.data=None — игнорируется."""
    runner, agent, bus = _make_runner()

    event = MagicMock()
    event.data = None
    await runner._on_user_message(event)
    # Очередь не создалась.
    assert (
        not hasattr(runner, "_pending_user_messages")
        or runner._pending_user_messages is None
        or runner._pending_user_messages.empty()
    )

    # Cleanup.
    await runner.stop()


@pytest.mark.asyncio
async def test_message_after_start_gets_reply_queue_stays_empty():
    """Сообщение после start() обработано дверями; очередь неизменна."""
    runner, agent, bus = _make_runner()
    await runner.start()
    queue_after_start = runner._pending_user_messages

    event = MagicMock()
    event.data = {"text": "после старта непонятное"}
    await runner._on_user_message(event)

    # Та же очередь, и она пуста: сообщения в стимулы не идут.
    assert runner._pending_user_messages is queue_after_start
    assert runner._pending_user_messages.empty()
    thoughts = [p for p in bus.published if p["name"] == Events.AGENT_THOUGHT]
    assert any("не понимаю" in (p["data"] or {}).get("text", "") for p in thoughts)

    # Cleanup.
    await runner.stop()
