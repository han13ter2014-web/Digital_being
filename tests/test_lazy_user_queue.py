"""
test_lazy_user_queue.py — тесты для ленивого создания _pending_user_messages.

Покрывает регрессию: раньше в ``_on_user_message`` сообщения, пришедшие
ДО ``start()``, молча отбрасывались с warning-логом (UX-баг:
пользователь мог отправить сообщение в окно чата ещё до того, как
AgentRunner стартовал, и оно исчезало бесследно).

Эти тесты проверяют, что:
1. Очередь создаётся лениво при первом сообщении (до start).
2. Сообщения, пришедшие до start(), НЕ теряются — они дожидаются первого тика.
3. start() НЕ пересоздаёт очередь, если она уже создана лениво.
4. start() создаёт очередь, если сообщений ещё не было.
5. Несколько сообщений до start() обрабатываются в правильном порядке.
"""
import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock

import pytest

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
        return {"energy": self._energy, "max_energy": 200,
                "percent": self._energy / 200 * 100, "level": "normal",
                "tick_interval_sec": 1.0}
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
async def test_message_before_start_is_not_lost():
    """Сообщение, пришедшее ДО start(), не теряется (race-condition fix)."""
    runner, agent, bus = _make_runner()

    # До start() — очереди НЕТ.
    assert not hasattr(runner, "_pending_user_messages") or \
           runner._pending_user_messages is None

    # Имитируем получение user_message ДО start().
    event = MagicMock()
    event.data = {"text": "привет"}
    await runner._on_user_message(event)

    # Очередь создалась лениво, сообщение внутри.
    assert runner._pending_user_messages is not None
    assert not runner._pending_user_messages.empty()
    # Правильный текст.
    msg = await runner._pending_user_messages.get()
    assert msg == "привет"


@pytest.mark.asyncio
async def test_multiple_messages_before_start_preserved():
    """Несколько сообщений до start() — все в очереди в правильном порядке."""
    runner, agent, bus = _make_runner()

    msgs = ["первое", "второе", "третье"]
    for m in msgs:
        event = MagicMock()
        event.data = {"text": m}
        await runner._on_user_message(event)

    # Все три в очереди, в порядке поступления.
    received = []
    while not runner._pending_user_messages.empty():
        received.append(await runner._pending_user_messages.get())
    assert received == msgs


@pytest.mark.asyncio
async def test_start_does_not_overwrite_existing_queue():
    """start() НЕ пересоздаёт очередь (если она уже лениво создана)."""
    runner, agent, bus = _make_runner()

    # Создаём ленивую очередь с сообщением.
    event = MagicMock()
    event.data = {"text": "до старта"}
    await runner._on_user_message(event)
    queue_before = runner._pending_user_messages
    assert not queue_before.empty()

    # start() не должен пересоздавать очередь.
    await runner.start()
    queue_after = runner._pending_user_messages
    assert queue_after is queue_before, (
        "start() пересоздал очередь — сообщения будут потеряны!"
    )
    # Сообщение осталось.
    assert not queue_after.empty()
    msg = await queue_after.get()
    assert msg == "до старта"


@pytest.mark.asyncio
async def test_start_creates_queue_if_not_exist():
    """start() создаёт очередь, если сообщений до этого не было."""
    runner, agent, bus = _make_runner()

    # Очереди нет.
    assert not hasattr(runner, "_pending_user_messages") or \
           runner._pending_user_messages is None

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
    assert not hasattr(runner, "_pending_user_messages") or \
           runner._pending_user_messages is None or \
           runner._pending_user_messages.empty()

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
    assert not hasattr(runner, "_pending_user_messages") or \
           runner._pending_user_messages is None or \
           runner._pending_user_messages.empty()

    # Cleanup.
    await runner.stop()


@pytest.mark.asyncio
async def test_message_after_start_uses_existing_queue():
    """Сообщение после start() использует существующую очередь."""
    runner, agent, bus = _make_runner()
    await runner.start()
    queue_after_start = runner._pending_user_messages

    event = MagicMock()
    event.data = {"text": "после старта"}
    await runner._on_user_message(event)

    # Та же очередь.
    assert runner._pending_user_messages is queue_after_start
    # Сообщение в ней.
    msg = await runner._pending_user_messages.get()
    assert msg == "после старта"

    # Cleanup.
    await runner.stop()