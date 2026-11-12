"""Managed-журнал диалогов живёт в SQLite; ошибка записи диагностируется."""

from contextlib import closing
import json
from types import SimpleNamespace
from uuid import uuid4

from config.simulation_config import LR_CONFIG
from src.core.agent_runner import AgentRunner
from src.core.watchdog import Watchdog
from src.memory.life_database import LifeDatabase


class RecordingBus:
    def subscribe(self, name, callback):
        pass


class Interaction:
    OUTGOING_TRACE_MAX = 100

    def __init__(self):
        self.message_history = [
            {"sender": "user", "content": "Привет"},
            {"sender": "agent", "content": "Здравствуй"},
        ]

    def to_checkpoint_dict(self):
        return {"pending_question": {"topic": "память"}, "outgoing_trace": ["след"]}


def _runner(database):
    agent = SimpleNamespace(
        name="DialogueSQL",
        cycle_count=12,
        energy=80.0,
        user_interaction=Interaction(),
        life_guard=SimpleNamespace(database=database),
    )
    runner = AgentRunner(
        agent,
        RecordingBus(),
        watchdog=Watchdog(max_rss_mb=1000, check_interval_cycles=1000),
    )
    runner._tick_count = 34
    runner._last_tick_ledger = {"kind": "user", "completed": True}
    return runner


def _records(database):
    with closing(database.connect(readonly=True)) as connection:
        rows = connection.execute(
            "SELECT ts, cycle, tick, agent_name, payload_json "
            "FROM dialogue_cycles ORDER BY id"
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def test_managed_dialogue_roundtrip_and_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    database = LifeDatabase(tmp_path / "life.sqlite3", str(uuid4()))
    runner = _runner(database)
    monkeypatch.setattr(LR_CONFIG, "DIALOGUE_CYCLES_MAX_ENTRIES", 2)

    for cycle in (12, 13, 14):
        runner.agent.cycle_count = cycle
        runner._save_dialogue_cycle_snapshot()

    records = _records(database)
    assert [record["cycle"] for record in records] == [13, 14]
    latest = records[-1]
    assert latest["tick"] == 34
    assert latest["agent_name"] == "DialogueSQL"
    assert latest["ledger"] == {"kind": "user", "completed": True}
    assert latest["dialogue"]["pending_question"] == {"topic": "память"}
    assert latest["dialogue"]["outgoing_trace"] == ["след"]
    assert (
        latest["dialogue"]["messages"] == runner.agent.user_interaction.message_history
    )
    assert not (tmp_path / "logs" / "dialogue_cycles.jsonl").exists()
    assert runner.get_status()["dialogue_journal"] == {
        "backend": "sqlite",
        "last_error": None,
    }

    reopened = LifeDatabase(database.path, database.life_id)
    assert _records(reopened) == records


def test_dialogue_sql_failure_is_visible_and_does_not_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    database = LifeDatabase(tmp_path / "life.sqlite3", str(uuid4()))
    runner = _runner(database)

    def fail(*args, **kwargs):
        raise RuntimeError("injected dialogue failure")

    monkeypatch.setattr(database, "append_dialogue_cycle", fail)
    runner._save_dialogue_cycle_snapshot()

    status = runner.get_status()["dialogue_journal"]
    assert status["backend"] == "sqlite"
    assert "injected dialogue failure" in status["last_error"]
    assert _records(database) == []
    assert not (tmp_path / "logs" / "dialogue_cycles.jsonl").exists()
