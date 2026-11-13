"""Ограничение входящих очередей и честная доставка при переполнении/остановке."""

import asyncio
from types import SimpleNamespace

import pytest

from main import Runtime
from src.core.agent_runner import AgentRunner, PersistentMessageQueue
from src.core.event_bus import EventBus, Events


class FakeAgent:
    def __init__(self):
        self.name = "BackpressureTest"
        self.energy = 100.0
        self.cycle_count = 0
        self.life_id = None
        self._profile_managed = False
        self._pending_message_texts = []
        self._deferred_stimulus = None

    def save_state(self, force=False):
        return True


class FakeBus:
    def subscribe(self, name, callback):
        pass

    async def publish(self, *args, **kwargs):
        return True

    def publish_sync(self, *args, **kwargs):
        return True


@pytest.mark.asyncio
async def test_persistent_queue_is_bounded_without_silent_drop():
    queue = PersistentMessageQueue(FakeAgent(), maxsize=2, put_timeout=0.05)
    queue.put_nowait("one")
    queue.put_nowait("two")

    with pytest.raises(asyncio.QueueFull):
        queue.put_nowait("three")

    assert list(queue._queue) == ["one", "two"]
    blocked = asyncio.create_task(queue.put("three"))
    await asyncio.sleep(0.01)
    assert not blocked.done()
    assert queue.get_nowait() == "one"
    assert await blocked is None
    assert queue.get_nowait() == "two"
    assert queue.get_nowait() == "three"


@pytest.mark.parametrize("existing", [None, "kept"])
def test_failed_message_journal_write_rolls_back_new_item(
    tmp_path, monkeypatch, existing
):
    agent = FakeAgent()
    agent._profile_managed = True
    agent.life_id = "queue-rollback"
    agent.checkpoint_dir = str(tmp_path)
    queue = PersistentMessageQueue(agent)
    if existing is not None:
        queue.put_nowait(existing)
    journal_path = tmp_path / "pending_messages.json"
    journal_before = journal_path.read_bytes() if journal_path.exists() else None

    def fail_journal_write():
        raise OSError("injected disk full")

    monkeypatch.setattr(queue, "_persist_journal", fail_journal_write)
    with pytest.raises(OSError, match="injected disk full"):
        queue.put_nowait("must not be processed")

    expected = [] if existing is None else [existing]
    assert list(queue._queue) == expected
    assert agent._pending_message_texts == expected
    assert queue.qsize() == len(expected)
    assert (journal_path.read_bytes() if journal_path.exists() else None) == (
        journal_before
    )
    assert [queue.get_nowait() for _ in expected] == expected
    assert queue.empty()


@pytest.mark.asyncio
async def test_pre_start_buffer_is_bounded_and_fifo():
    bus = EventBus(max_queue_size=2)
    assert bus.publish_sync("message", {"n": 1})
    assert bus.publish_sync("message", {"n": 2})
    assert not bus.publish_sync("message", {"n": 3})

    await bus.start()
    assert bus.drain_pre_start() == 2
    assert [event.data["n"] for event in bus._queue._queue] == [1, 2]
    assert bus.get_stats()["dropped_count"] == 1


@pytest.mark.asyncio
async def test_async_publish_waits_for_capacity_instead_of_dropping():
    bus = EventBus(max_queue_size=1, publish_timeout=0.2)
    await bus.start()
    assert await bus.publish("message", {"n": 1})

    blocked = asyncio.create_task(bus.publish("message", {"n": 2}))
    await asyncio.sleep(0.01)
    assert not blocked.done()
    assert await bus.dispatch_once() == 1
    assert await blocked
    assert await bus.dispatch_once() == 1
    assert bus.get_stats()["dropped_count"] == 0


@pytest.mark.asyncio
async def test_sync_publish_reports_full_queue_to_caller():
    bus = EventBus(max_queue_size=1)
    await bus.start()

    assert bus.publish_sync("message", {"n": 1})
    assert not bus.publish_sync("message", {"n": 2})
    assert bus.get_stats()["dropped_count"] == 1
    assert await bus.dispatch_once() == 1


@pytest.mark.asyncio
async def test_sync_event_history_is_not_duplicated_by_dispatch():
    bus = EventBus()
    received = []

    async def receive(event):
        received.append(event)

    bus.subscribe("message", receive)
    await bus.start()
    assert bus.publish_sync("message", {"n": 1})
    accepted_history = bus.get_history()
    assert len(accepted_history) == 1

    assert await bus.dispatch_once() == 1
    assert received == accepted_history
    assert bus.get_history() == accepted_history
    stats = bus.get_stats()
    assert stats["history_size"] == 1
    assert stats["events_by_name"] == {"message": 1}


@pytest.mark.asyncio
async def test_pre_start_event_is_counted_once_when_drained_and_dispatched():
    bus = EventBus()
    assert bus.publish_sync("message", {"n": 1})
    accepted_history = bus.get_history()
    assert bus.get_stats()["events_by_name"] == {"message": 1}

    await bus.start()
    assert bus.drain_pre_start() == 1
    assert bus.drain_pre_start() == 0
    assert bus.get_stats()["events_by_name"] == {"message": 1}

    assert await bus.dispatch_once() == 1
    assert bus.get_history() == accepted_history
    stats = bus.get_stats()
    assert stats["history_size"] == 1
    assert stats["events_by_name"] == {"message": 1}


@pytest.mark.asyncio
async def test_runtime_starts_consumer_then_drains_messages_on_shutdown():
    bus = EventBus(max_queue_size=8)
    received = []
    order = []

    class DrainRunner:
        def __init__(self):
            self._stop_requested = False
            self.started = False

        async def start(self):
            self.started = True
            order.append("runner_started")
            bus.subscribe(Events.USER_MESSAGE, self.on_message)

        async def on_message(self, event):
            if event.data["text"] == "one":
                await asyncio.sleep(0.05)
            received.append(event.data["text"])

        def set_speed(self, mode):
            pass

        def save_now(self):
            return False

        async def run_forever(self):
            while not self._stop_requested:
                await asyncio.sleep(0.005)

        async def stop(self):
            self._stop_requested = True

    runner = DrainRunner()
    original_drain = bus.drain_pre_start

    def recording_drain():
        order.append("pre_start_drained")
        assert runner.started
        return original_drain()

    bus.drain_pre_start = recording_drain
    runtime = Runtime(SimpleNamespace(name="test"), bus, runner)
    for text in ("one", "two", "three"):
        assert bus.publish_sync(Events.USER_MESSAGE, {"text": text})
    runtime.shutdown.set()

    await asyncio.wait_for(runtime._main("step"), timeout=2)

    assert order[:2] == ["runner_started", "pre_start_drained"]
    assert received == ["one", "two", "three"]
    assert "сохранить" in runtime.error


@pytest.mark.asyncio
async def test_runner_stop_drains_accepted_persistent_messages():
    agent = FakeAgent()
    runner = AgentRunner(agent, FakeBus())
    await runner.start()
    queue = PersistentMessageQueue(agent, maxsize=3)
    runner._pending_user_messages = queue
    for text in ("one", "two", "three"):
        queue.put_nowait(text)
    received = []

    async def drain_tick(*, wait_for_user):
        while not queue.empty():
            received.append(queue.get_nowait())

    runner._tick_once = drain_tick
    await runner.stop()

    assert received == ["one", "two", "three"]
    assert agent._pending_message_texts == []


@pytest.mark.asyncio
async def test_sync_publish_from_worker_returns_actual_enqueue_result():
    bus = EventBus(max_queue_size=1)
    await bus.start()
    bus.attach_loop(asyncio.get_running_loop())

    assert await asyncio.to_thread(bus.publish_sync, "message", {"n": 1})
    assert not await asyncio.to_thread(bus.publish_sync, "message", {"n": 2})
    assert await bus.dispatch_once() == 1


@pytest.mark.asyncio
async def test_sync_publish_from_other_running_loop_enqueues_on_core_thread(
    monkeypatch,
):
    import queue
    import threading

    bus = EventBus(max_queue_size=1)
    await bus.start()
    bus.attach_loop(asyncio.get_running_loop())
    core_thread_id = threading.get_ident()
    enqueue_thread_ids = []
    original_enqueue = bus._enqueue_event_sync

    def recording_enqueue(event):
        enqueue_thread_ids.append(threading.get_ident())
        return original_enqueue(event)

    monkeypatch.setattr(bus, "_enqueue_event_sync", recording_enqueue)
    outcome = queue.Queue()

    def publish_from_foreign_loop():
        foreign_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(foreign_loop)
        try:

            async def publish_inside_foreign_loop():
                return bus.publish_sync("message", {"n": 1})

            accepted = foreign_loop.run_until_complete(publish_inside_foreign_loop())
            outcome.put((True, accepted))
        except BaseException as exc:
            outcome.put((False, exc))
        finally:
            foreign_loop.close()

    foreign_thread = threading.Thread(target=publish_from_foreign_loop)
    foreign_thread.start()
    try:
        completed, result = await asyncio.to_thread(outcome.get, timeout=2)
        if not completed:
            raise result
        assert result is True
        assert await bus.dispatch_once() == 1
        assert enqueue_thread_ids == [core_thread_id]
    finally:
        foreign_thread.join(timeout=2)
        assert not foreign_thread.is_alive()


def test_sync_publish_timeout_cannot_enqueue_later():
    callbacks = []

    class SuspendedLoop:
        def is_closed(self):
            return False

        def call_soon_threadsafe(self, callback):
            callbacks.append(callback)

    bus = EventBus(max_queue_size=1, publish_timeout=0.01)
    bus._queue = asyncio.Queue(maxsize=1)
    bus.attach_loop(SuspendedLoop())

    assert not bus.publish_sync("message", {"n": 1})
    callbacks.pop()()
    assert bus._queue.empty()
    assert bus.get_stats()["dropped_count"] == 1


@pytest.mark.asyncio
async def test_drain_pre_start_preserves_overflow_for_later_delivery():
    bus = EventBus(max_queue_size=1)
    assert bus.publish_sync("message", {"n": 1})
    await bus.start()
    assert bus.publish_sync("message", {"n": 2})

    assert bus.drain_pre_start() == 0
    assert [event.data["n"] for event in bus._pending_pre_start] == [1]
    assert await bus.dispatch_once() == 1
    assert bus.drain_pre_start() == 1
    assert bus._pending_pre_start == []
    assert await bus.dispatch_once() == 1


@pytest.mark.asyncio
async def test_stop_attempt_budget_includes_deferred_stimulus():
    from src.core.agent_runner import MAX_STIMULUS_RETRIES

    agent = FakeAgent()
    agent._deferred_stimulus = {"text": "poison", "user_initiated": True}
    runner = AgentRunner(agent, FakeBus())
    await runner.start()
    queue = PersistentMessageQueue(agent, maxsize=1)
    runner._pending_user_messages = queue
    queue.put_nowait("queued")
    attempts = []
    received = []

    async def drain_tick(*, wait_for_user):
        attempts.append(1)
        if agent._deferred_stimulus is not None:
            if len(attempts) == MAX_STIMULUS_RETRIES:
                agent._deferred_stimulus = None
            return
        received.append(queue.get_nowait())

    runner._tick_once = drain_tick
    await runner.stop()

    assert len(attempts) == MAX_STIMULUS_RETRIES + 1
    assert received == ["queued"]
