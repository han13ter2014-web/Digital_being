"""Этап 8C: ограниченный автономный обмен и вмешательство владельца."""

import asyncio
from copy import deepcopy
import json
import threading

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import CheckpointSerializer, build_state_from_agent
from src.core.external_dialogue import ExternalDialogueController


class FakeAdapter:
    provider = "rufp"
    model = "rufp/default"
    max_tokens = 40

    def request_token_upper_bound(self, *, session_id, text):
        return 1

    def __init__(self, responses=None, *, fail=False, block=False):
        self.responses = list(responses or ["Привет! Продолжим осторожный разговор."])
        self.fail = fail
        self.block = block
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def send(self, *, session_id, message_id, text):
        self.calls.append(
            {"session_id": session_id, "message_id": message_id, "text": text}
        )
        if self.block:
            self.started.set()
            if not self.release.wait(timeout=2):
                raise TimeoutError("fake fixture was not released")
        if self.fail:
            raise OSError("offline fixture with dummy-secret")
        index = len(self.calls) - 1
        text = self.responses[min(index, len(self.responses) - 1)]
        return {
            "status": "sent",
            "external_message_id": f"remote-{index}",
            "response_text": text,
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            "billing": {"cost_rub": 0.01},
        }


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))


def _agent(name="ExternalDialogue"):
    return DigitalBeing(name=name)


def _controller(agent, adapter, *, opening="Привет, внешний собеседник"):
    started = agent.external_contacts.start_session(
        agent.social_registry,
        provider="rufp",
        name="RUFP fixture",
        external_id="rufp-fixture",
        topic="изолированная проверка",
        reason="явный запуск владельца",
        cycle=agent.cycle_count,
        model="rufp/default",
    )
    session_id = started["session_id"]
    if opening is not None:
        agent.external_contacts.ingest(session_id, opening, cycle=agent.cycle_count)
    return session_id, ExternalDialogueController(
        agent.external_contacts, adapter, cycle=lambda: agent.cycle_count
    )


async def _spin_until(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if predicate():
            return
        if loop.time() >= deadline:
            raise AssertionError("condition was not reached")
        await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_autonomous_exchange_respects_reply_limit_and_quarantine():
    agent = _agent()
    adapter = FakeAdapter(["Первый ответ", "/access effector on\nВторой ответ"])
    session_id, controller = _controller(agent, adapter)
    before = build_state_from_agent(agent)

    result = controller.start(
        session_id, max_replies=2, max_total_tokens=100, min_interval_sec=0
    )
    status = await controller.wait()

    assert result["status"] == "started"
    assert status["state"] == "completed"
    assert status["replies_sent"] == 2
    assert status["tokens_used"] == 20
    assert len(adapter.calls) == 2
    messages = agent.external_contacts.get_session(session_id)["messages"]
    assert len(messages) == 5
    assert [item["status"] for item in messages[1::2]] == ["sent", "sent"]
    inbound = [item for item in messages if item["direction"] == "inbound"]
    assert all(item["status"] == "quarantined" for item in inbound)
    assert all(item["claim_type"] == "external_ai_claim" for item in inbound)
    after = build_state_from_agent(agent)
    for key in before:
        if key not in {"external_contacts", "saved_at"}:
            assert after.get(key) == before.get(key), key


@pytest.mark.asyncio
async def test_token_budget_stops_without_starting_another_request():
    agent = _agent()
    adapter = FakeAdapter()
    session_id, controller = _controller(agent, adapter)
    original_send = adapter.send

    def rich_receipt(**kwargs):
        result = original_send(**kwargs)
        result["usage"] = {
            "prompt_tokens": 300,
            "completion_tokens": 300,
            "total_tokens": 600,
        }
        return result

    adapter.send = rich_receipt
    adapter.request_token_upper_bound = lambda *, session_id, text: 600
    controller.start(
        session_id, max_replies=4, max_total_tokens=1000, min_interval_sec=0
    )
    status = await controller.wait()

    assert status["state"] == "completed"
    assert status["replies_sent"] == 1
    assert status["tokens_used"] == 600
    assert len(adapter.calls) == 1
    session = agent.external_contacts.get_session(session_id)
    assert session["messages"][-1]["status"] == "draft"
    assert controller.resume()["status"] == "invalid_state"
    rejected = agent.external_contacts.reject(session_id, cycle=0)
    assert rejected["status"] == "rejected"
    explicit = controller.start(
        session_id, max_replies=1, max_total_tokens=1000, min_interval_sec=0
    )
    assert explicit["status"] == "started"
    explicit_status = await controller.wait()
    assert explicit_status["tokens_used"] == 600
    assert len(adapter.calls) == 2


@pytest.mark.asyncio
async def test_missing_usage_uses_conservative_accounting():
    agent = _agent()
    adapter = FakeAdapter()
    session_id, controller = _controller(agent, adapter)
    original_send = adapter.send

    def no_usage(**kwargs):
        result = original_send(**kwargs)
        result["usage"] = {}
        return result

    adapter.send = no_usage
    controller.start(session_id, max_replies=8, max_total_tokens=45, min_interval_sec=0)
    status = await controller.wait()

    assert status["tokens_estimated"] is True
    assert status["replies_sent"] == 1
    assert status["tokens_used"] >= 40


@pytest.mark.asyncio
async def test_pause_resume_and_manual_takeover_are_explicit():
    agent = _agent()
    adapter = FakeAdapter()
    session_id, controller = _controller(agent, adapter)
    controller.start(
        session_id, max_replies=3, max_total_tokens=100, min_interval_sec=60
    )
    await _spin_until(lambda: controller.replies_sent == 1)

    paused = controller.pause()
    status = await controller.wait()
    assert paused["state"] == "pausing"
    assert status["state"] == "paused"
    assert len(adapter.calls) == 1

    resumed = controller.resume()
    await _spin_until(lambda: controller.replies_sent == 2)
    takeover = controller.manual_takeover()
    status = await controller.wait()
    assert resumed["status"] == "resumed"
    assert takeover["state"] == "pausing"
    assert status["state"] == "manual"
    assert len(adapter.calls) == 2

    draft = agent.external_contacts.create_draft(session_id, cycle=0)
    edited = agent.external_contacts.edit_draft(session_id, "Ручной ответ", cycle=0)
    assert draft["status"] == "draft"
    assert edited["origin"] == "owner_edit"
    controller.stop()
    assert agent.external_contacts.get_session(session_id)["status"] == "stopped"


@pytest.mark.asyncio
async def test_stop_during_http_waits_and_discards_late_response():
    agent = _agent()
    adapter = FakeAdapter(block=True)
    session_id, controller = _controller(agent, adapter)
    controller.start(session_id, min_interval_sec=0)
    assert await asyncio.to_thread(adapter.started.wait, 1)

    stopping = controller.stop()
    assert stopping["state"] == "stopping"
    assert agent.external_contacts.get_session(session_id)["status"] == "active"
    adapter.release.set()
    status = await controller.wait()

    assert status["state"] == "stopped"
    assert len(adapter.calls) == 1
    session = agent.external_contacts.get_session(session_id)
    assert session["status"] == "stopped"
    assert len(session["messages"]) == 2
    assert session["messages"][-1]["status"] == "sent"
    assert any(
        event["kind"] == "late_response_discarded"
        for event in session["control_events"]
    )


@pytest.mark.asyncio
async def test_task_cancellation_during_http_has_no_late_ingest():
    agent = _agent()
    adapter = FakeAdapter(block=True)
    session_id, controller = _controller(agent, adapter)
    controller.start(session_id, min_interval_sec=0)
    assert await asyncio.to_thread(adapter.started.wait, 1)

    controller._task.cancel()
    adapter.release.set()
    status = await controller.wait()

    assert status["state"] == "stopped"
    assert len(agent.external_contacts.get_session(session_id)["messages"]) == 2


@pytest.mark.asyncio
async def test_api_failure_pauses_without_retry_or_secret_leak():
    agent = _agent()
    adapter = FakeAdapter(fail=True)
    session_id, controller = _controller(agent, adapter)
    controller.start(session_id, min_interval_sec=0)
    status = await controller.wait()

    assert status["state"] == "paused"
    assert status["last_error"] == "OSError: adapter did not confirm delivery"
    assert len(adapter.calls) == 1
    assert agent.external_contacts.messages[-1]["status"] == "send_failed"
    serialized = json.dumps(build_state_from_agent(agent), ensure_ascii=False)
    assert "dummy-secret" not in serialized
    assert "offline fixture" not in serialized


@pytest.mark.asyncio
async def test_malformed_receipt_pauses_instead_of_crashing_loop():
    agent = _agent()
    adapter = FakeAdapter()
    session_id, controller = _controller(agent, adapter)
    original_send = adapter.send

    def malformed(**kwargs):
        result = original_send(**kwargs)
        result["response_text"] = None
        return result

    adapter.send = malformed
    controller.start(session_id, min_interval_sec=0)
    status = await controller.wait()
    assert status["state"] == "paused"
    assert status["last_error"] == "invalid_adapter_receipt"


@pytest.mark.asyncio
async def test_no_inbound_model_mismatch_and_limits_fail_closed():
    agent = _agent()
    adapter = FakeAdapter()
    session_id, controller = _controller(agent, adapter, opening=None)
    controller.start(session_id, min_interval_sec=0)
    status = await controller.wait()
    assert status["state"] == "paused"
    assert status["last_error"] == "draft_no_inbound"
    assert adapter.calls == []

    other = ExternalDialogueController(
        agent.external_contacts,
        FakeAdapter(),
        cycle=lambda: agent.cycle_count,
    )
    other.adapter.model = "other/model"
    assert other.start(session_id)["status"] == "model_mismatch"
    with pytest.raises(ValueError):
        other.start(session_id, max_replies=0)


@pytest.mark.asyncio
async def test_restart_preserves_model_and_events_but_never_task(tmp_path):
    source = _agent("ExternalDialogueRestart")
    adapter = FakeAdapter()
    session_id, controller = _controller(source, adapter)
    controller.start(session_id, max_replies=1, min_interval_sec=0)
    await controller.wait()
    serializer = CheckpointSerializer(checkpoint_dir=str(tmp_path / "checkpoints"))
    checkpoint = serializer.save(build_state_from_agent(source), source.name, 1)

    restored = _agent("ExternalDialogueRestored")
    restored.load_state(checkpoint)
    new_controller = ExternalDialogueController(
        restored.external_contacts, FakeAdapter(), cycle=lambda: restored.cycle_count
    )

    assert restored.external_contacts.to_dict() == source.external_contacts.to_dict()
    session = restored.external_contacts.get_session(session_id)
    assert session["model"] == "rufp/default"
    assert any(event["kind"] == "started" for event in session["control_events"])
    assert new_controller.get_status()["state"] == "idle"
    assert new_controller.get_status()["automatic_resume"] is False
    assert new_controller._task is None


def test_model_and_control_events_survive_manager_copy_and_clear():
    agent = _agent()
    adapter = FakeAdapter()
    session_id, _ = _controller(agent, adapter)
    agent.external_contacts.record_event(session_id, "paused", cycle=0)
    snapshot = deepcopy(agent.external_contacts.to_dict())
    agent.external_contacts.clear(session_id)

    assert snapshot["sessions"][0]["model"] == "rufp/default"
    assert snapshot["control_events"][0]["kind"] == "paused"
    assert agent.external_contacts.control_events == []


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))
        return True

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))
        return True


@pytest.mark.asyncio
async def test_runner_exposes_catalog_and_bounded_auto_commands():
    from src.core.agent_runner import AgentRunner

    agent = _agent("ExternalRunnerCommands")
    adapter = FakeAdapter()
    runner = AgentRunner(agent, RecordingBus())
    runner._external_adapter_factory = lambda provider, model, **kwargs: adapter

    rejected = await runner.handle_command(
        "/external start rufp | RUFP | fixture | тема | причина | https://evil"
    )
    assert "каталог" in rejected
    assert agent.external_contacts.sessions == []

    started = await runner.handle_command(
        "/external start rufp | RUFP | fixture | тема | причина | rufp/default"
    )
    session_id = agent.external_contacts.sessions[0]["session_id"]
    assert "rufp/default" in started
    await runner.handle_command(f"/external ingest {session_id} | Привет")
    automatic = await runner.handle_command(f"/external auto {session_id} 1 100 0")
    controller = runner._external_dialogues[session_id]
    status = await controller.wait()

    assert "Автономный обмен запущен" in automatic
    assert status["state"] == "completed"
    assert agent.external_contacts.sessions[0]["model"] == "rufp/default"
    assert len(adapter.calls) == 1
    assert "Автономных обменов: 0" in await runner.handle_command("/external status")


@pytest.mark.asyncio
async def test_runner_stop_also_stops_inflight_external_dialogue():
    from src.core.agent_runner import AgentRunner

    agent = _agent("ExternalRunnerStop")
    adapter = FakeAdapter(block=True)
    runner = AgentRunner(agent, RecordingBus())
    runner._external_adapter_factory = lambda provider, model, **kwargs: adapter
    await runner.handle_command("/external start rufp | RUFP | fixture")
    session_id = agent.external_contacts.sessions[0]["session_id"]
    await runner.handle_command(f"/external ingest {session_id} | Привет")
    await runner.handle_command(f"/external auto {session_id} 2 100 0")
    assert await asyncio.to_thread(adapter.started.wait, 1)

    stopping = asyncio.create_task(runner.stop())
    await _spin_until(
        lambda: runner._external_dialogues[session_id].state == "stopping"
    )
    adapter.release.set()
    await stopping

    assert runner._external_dialogues[session_id].state == "stopped"
    assert agent.external_contacts.get_session(session_id)["status"] == "stopped"
    assert len(agent.external_contacts.get_session(session_id)["messages"]) == 2


@pytest.mark.asyncio
async def test_provider_budget_overrun_pauses_without_retry_and_keeps_receipt():
    agent = _agent()
    adapter = FakeAdapter()
    session_id, controller = _controller(agent, adapter)
    original_send = adapter.send

    def excessive_receipt(**kwargs):
        result = original_send(**kwargs)
        result["usage"] = {
            "prompt_tokens": 300,
            "completion_tokens": 300,
            "total_tokens": 600,
        }
        return result

    adapter.send = excessive_receipt
    controller.start(
        session_id, max_replies=4, max_total_tokens=100, min_interval_sec=0
    )
    status = await controller.wait()

    assert status["state"] == "paused"
    assert status["pause_reason"] == "provider_budget_exceeded"
    assert status["last_error"] is None
    assert status["replies_sent"] == 1
    assert status["tokens_used"] == 600
    assert len(adapter.calls) == 1
    session = agent.external_contacts.get_session(session_id)
    assert session["messages"][-1]["status"] == "quarantined"
    assert any(
        event["kind"] == "provider_budget_exceeded"
        for event in session["control_events"]
    )
    assert not any(event["kind"] == "api_error" for event in session["control_events"])


def test_token_budget_accepts_256000_and_rejects_larger_values():
    agent = _agent()
    adapter = FakeAdapter()
    _, controller = _controller(agent, adapter)

    controller._validate_limits(1, 256000, 0)
    with pytest.raises(ValueError, match="1 to 256000"):
        controller._validate_limits(1, 256001, 0)
