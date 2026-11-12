"""SQLite-контур LifeGuard: атомарность, восстановление и обязательный backup."""

from pathlib import Path
from uuid import uuid4

import pytest

from src.core.life_guard import (
    KIND_DREAM,
    KIND_TERMINATE,
    STATE_ALIVE,
    STATE_DORMANT,
    STATE_TERMINATED,
    ConfirmationError,
    LifeGuard,
    get_policy,
)
from src.memory.profile_backup import verify_backup


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


@pytest.fixture()
def sql_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    clock = FakeClock()
    guard = LifeGuard(
        agent_name="SQLiteLife",
        clock=clock,
        life_id=str(uuid4()),
        snapshot_root=str(tmp_path / "snapshots"),
    )
    return guard, clock, tmp_path


def confirmed_request(guard, clock, kind):
    request = guard.request(kind, reason="изолированный тест")
    clock.advance(get_policy(kind).cooldown_sec + 0.1)
    phrase = "SQLiteLife" if kind == KIND_DREAM else "SQLiteLife НАВСЕГДА"
    guard.confirm(request.request_id, phrase)
    return request


def test_sqlite_dream_requests_events_and_state_survive_reopen(sql_guard):
    guard, clock, root = sql_guard
    request = confirmed_request(guard, clock, KIND_DREAM)

    result = guard.execute_confirmed(request.request_id, seed_folder="seed-test")

    assert result["state"] == STATE_DORMANT
    assert guard.get_request(request.request_id) is None
    assert [item["event"] for item in guard.recent_events()] == [
        "requested", "confirmed", "state_changed", "executed",
    ]
    assert not (root / "life_state.json").exists()
    assert not (root / "life_requests.json").exists()
    assert not (root / "life_events.log").exists()

    reopened = LifeGuard(agent_name="SQLiteLife", life_id=guard.life_id)
    assert reopened.load_state() == STATE_DORMANT
    assert reopened.state_details()["seed_folder"] == "seed-test"
    assert reopened.wake()["state"] == STATE_ALIVE
    assert reopened.load_state() == STATE_ALIVE


def test_sqlite_termination_is_blocked_when_backup_fails(sql_guard, monkeypatch):
    guard, clock, _root = sql_guard
    request = confirmed_request(guard, clock, KIND_TERMINATE)
    monkeypatch.setattr(guard, "create_snapshot", lambda tag: None)

    with pytest.raises(ConfirmationError, match="резервный снимок"):
        guard.execute_confirmed(request.request_id)

    assert guard.load_state() == STATE_ALIVE
    assert guard.get_request(request.request_id).confirmed is True
    assert "executed" not in {item["event"] for item in guard.recent_events()}


def test_sqlite_execute_rolls_back_all_changes_on_event_error(sql_guard, monkeypatch):
    guard, clock, _root = sql_guard
    request = confirmed_request(guard, clock, KIND_DREAM)
    original = guard._log_event

    def fail_executed(event, *, connection=None, **fields):
        if event == "executed":
            raise RuntimeError("искусственный сбой до commit")
        return original(event, connection=connection, **fields)

    monkeypatch.setattr(guard, "_log_event", fail_executed)
    with pytest.raises(RuntimeError, match="до commit"):
        guard.execute_confirmed(request.request_id)

    assert guard.load_state() == STATE_ALIVE
    assert guard.get_request(request.request_id).confirmed is True
    assert "executed" not in {item["event"] for item in guard.recent_events()}


def test_sqlite_termination_creates_verified_backup(sql_guard):
    guard, clock, root = sql_guard
    request = confirmed_request(guard, clock, KIND_TERMINATE)

    result = guard.execute_confirmed(request.request_id)

    assert result["state"] == STATE_TERMINATED
    assert result["snapshot"] is not None
    verify_backup(result["snapshot"])
    assert guard.get_request(request.request_id) is None
    reopened = LifeGuard(agent_name="SQLiteLife", life_id=guard.life_id)
    assert reopened.load_state() == STATE_TERMINATED
    assert Path(result["snapshot"]).parent == root / "snapshots"


def test_managed_agent_rebinds_guard_to_restored_life(tmp_path, monkeypatch):
    from src.core.agent import DigitalBeing
    from src.core.checkpoint_serializer import (
        apply_state_to_agent,
        build_state_from_agent,
    )

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing("ManagedLife", profile_managed=True)
    original_id = agent.life_id
    assert agent.life_guard.database.life_id == original_id

    restored_id = str(uuid4())
    state = build_state_from_agent(agent)
    state["life_id"] = restored_id
    apply_state_to_agent(agent, state)

    assert agent.life_id == restored_id
    assert agent.life_guard.life_id == restored_id
    assert agent.life_guard.database.life_id == restored_id
    assert agent.life_guard.load_state() == STATE_ALIVE
