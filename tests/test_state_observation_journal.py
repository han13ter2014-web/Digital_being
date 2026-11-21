"""Sanitized longitudinal journal: isolation, privacy, gaps and export."""

from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4
import zipfile

import pytest

from src.core.agent_runner import AgentRunner
from src.core.emotional_state import EmotionalState
from src.core.event_bus import Events
from src.core.state_observation import (
    EPISODE_NAME,
    GAP_NAME,
    OBSERVATION_NAME,
    emotion_episode_records,
    export_state_observations,
    metric_record,
    observation_from_snapshot,
)
from src.memory.life_database import LifeDatabase


def _snapshot(cycle=7):
    return {
        "name": "Секретное имя не нужно",
        "life": {"cycle": cycle, "energy": 107.0, "speed_mode": "live"},
        "body": {
            "fatigue": 0.4,
            "fatigue_level": "tired",
            "atp": 51.2,
            "needs_rest": True,
            "error": "C:\\private\\body.txt",
        },
        "emotions": {
            "levels": {"joy": 0.7, "sadness": 0.15, "nostalgia": 0.998},
            "dominant": {
                "emotion": "nostalgia",
                "cause": "личная фраза, которую нельзя экспортировать",
            },
            "mixture": {"total_intensity": 1.2, "valence": 0.45, "arousal": 0.2},
        },
        "motivation": {
            "needs": {
                "curiosity": {
                    "current_level": 0.8,
                    "base_level": 0.9,
                    "pressing": False,
                    "label": "свободный текст",
                }
            },
            "drives": {
                "creativity": {
                    "current_level": 0.6,
                    "threshold": 0.35,
                    "active": True,
                }
            },
            "goals_generated": 3,
        },
        "now": {
            "activity": {
                "action": "draw",
                "status": "started",
                "cycle": cycle,
                "target": "секретная тема рисунка",
            }
        },
        "intentions": {
            "last_finished": {
                "action": "compose_music",
                "status": "performed",
                "cycle": cycle - 1,
                "target": "секретная тема музыки",
            }
        },
        "activities": {"creative": {"count": 2, "text": "секретный стих"}},
        "hardware": {
            "initialized": True,
            "mode": "shadow",
            "episode_count": 4,
            "recent_events": [{"path": "C:\\private\\disk"}],
        },
        "hormonal_projection": {
            "initialized": True,
            "mode": "shadow_interoception",
            "time_model": "tick_only",
            "levels": {"dopamine": 0.4, "cortisol": 0.1},
            "profile": {
                "dopamine": {
                    "baseline": 0.35,
                    "sensitivity": 1.1,
                    "sample_count": 4,
                }
            },
        },
        "goals": {"total": 4, "completed": 2, "active": "секретная цель"},
        "dialogue": {"messages": [{"text": "секретный диалог"}]},
    }


def _database(tmp_path, life_id=None):
    life_id = life_id or str(uuid4())
    return LifeDatabase(tmp_path / "lives" / life_id / "life.sqlite3", life_id)


def _append_observation(database, cycle=7):
    observation = observation_from_snapshot(
        _snapshot(cycle), observed_at=f"2026-11-22T00:00:{cycle:02d}+00:00"
    )
    record = metric_record(
        observation, name=OBSERVATION_NAME, record_id=f"observation:{cycle}"
    )
    assert database.append_metric_samples([record]) == 1
    return observation


def test_snapshot_whitelist_excludes_text_paths_and_unknown_fields():
    observation = observation_from_snapshot(_snapshot())

    assert observation["cycle"] == 7
    assert observation["body"]["energy"] == 107.0
    assert observation["behavior"]["current_activity"] == {
        "action": "draw",
        "status": "started",
        "cycle": 7,
    }
    assert observation["emotions"]["dominant"] == "nostalgia"
    assert observation["goals"] == {"total": 4.0, "completed": 2.0}
    assert "dialogue" not in observation
    serialized = json.dumps(observation, ensure_ascii=False)
    for forbidden in (
        "секрет",
        "личная фраза",
        "C:\\private",
        "свободный текст",
    ):
        assert forbidden not in serialized


def test_episode_ids_are_stable_and_preserve_same_cycle_repeats():
    state = EmotionalState()
    state.handle_event("remembered_past", cycle=4, cause="приватная причина")
    state._record("nostalgia", 0.25, "remembered_past", 4, "другая причина")

    first = emotion_episode_records(state, observed_at="2026-11-22T00:00:00+00:00")
    second = emotion_episode_records(state, observed_at="2026-11-22T00:00:00+00:00")

    assert len(first) == 2
    assert len({item["record_id"] for item in first}) == 2
    assert [item["record_id"] for item in first] == [
        item["record_id"] for item in second
    ]
    assert all(item["action"] is None and item["outcome"] is None for item in first)
    assert "приватная причина" not in json.dumps(first, ensure_ascii=False)


def test_metric_append_dedupes_and_two_lives_are_isolated(tmp_path):
    first = _database(tmp_path)
    second = _database(tmp_path)
    observation = _append_observation(first, 7)
    record = metric_record(
        observation, name=OBSERVATION_NAME, record_id="observation:7"
    )

    assert first.append_metric_samples([record]) == 0
    assert len(first.read_metric_samples(names=[OBSERVATION_NAME])) == 1
    assert second.read_metric_samples(names=[OBSERVATION_NAME]) == []
    with closing(sqlite3.connect(first.path)) as connection:
        owners = connection.execute(
            "SELECT value_json FROM meta WHERE key='life_id'"
        ).fetchone()
    assert json.loads(owners[0]) == first.life_id != second.life_id


def test_export_has_valid_jsonl_hashes_html_and_no_private_payload(tmp_path):
    database = _database(tmp_path)
    _append_observation(database, 7)
    state = EmotionalState()
    state.handle_event("remembered_past", cycle=7, cause="секретный диалог")
    episodes = emotion_episode_records(state)
    database.append_metric_samples(
        metric_record(item, name=EPISODE_NAME, record_id=item["record_id"])
        for item in episodes
    )
    destination = tmp_path / "export.zip"

    manifest = export_state_observations(
        database, destination, fresh_snapshot=True, writer_status={"dropped_events": 0}
    )

    assert manifest["readiness"] == "available"
    assert manifest["counts"]["observations"] == 1
    assert manifest["counts"]["episodes"] == 1
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "observations.jsonl",
            "episodes.jsonl",
            "interventions.jsonl",
            "report.html",
        }
        packed_manifest = json.loads(archive.read("manifest.json"))
        assert packed_manifest == manifest
        for name, evidence in manifest["files"].items():
            payload = archive.read(name)
            assert len(payload) == evidence["bytes"]
            assert hashlib.sha256(payload).hexdigest() == evidence["sha256"]
        observations = [
            json.loads(line)
            for line in archive.read("observations.jsonl").decode("utf-8").splitlines()
        ]
        episodes_out = [
            json.loads(line)
            for line in archive.read("episodes.jsonl").decode("utf-8").splitlines()
        ]
        assert len(observations) == len(episodes_out) == 1
        assert archive.read("interventions.jsonl") == b""
        report = archive.read("report.html").decode("utf-8")
        assert "не медицинское заключение" in report
        assert "default-src 'none'" in report
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8")
            assert "секрет" not in text
            assert "C:\\private" not in text


def test_period_filter_and_empty_corrupt_history_are_honest(tmp_path):
    database = _database(tmp_path)
    _append_observation(database, 7)
    _append_observation(database, 30)
    with database.write() as connection:
        connection.execute(
            "INSERT INTO metric_samples(ts, cycle, name, value_json, metadata_json) "
            "VALUES ('broken', 30, ?, '{broken', '{}')",
            (OBSERVATION_NAME,),
        )

    filtered = tmp_path / "filtered.zip"
    filtered_manifest = export_state_observations(
        database, filtered, start_cycle=10, end_cycle=40, fresh_snapshot=False
    )
    assert filtered_manifest["counts"]["observations"] == 1
    assert filtered_manifest["counts"]["invalid_records_excluded"] == 1
    assert filtered_manifest["period"] == {
        "first_cycle": 30,
        "last_cycle": 30,
        "first_observed_at": "2026-11-22T00:00:30+00:00",
        "last_observed_at": "2026-11-22T00:00:30+00:00",
    }
    assert (
        "fresh_snapshot_unavailable" in filtered_manifest["completeness"]["limitations"]
    )

    empty = _database(tmp_path)
    empty_manifest = export_state_observations(
        empty, tmp_path / "empty.zip", fresh_snapshot=False
    )
    assert empty_manifest["readiness"] == "insufficient_data"
    assert empty_manifest["counts"]["observations"] == 0
    assert empty_manifest["interventions"] == {"status": "unavailable", "count": 0}


class RecordingBus:
    def __init__(self):
        self.subscriptions = {}
        self.published = []

    def subscribe(self, name, callback):
        self.subscriptions[name] = callback

    async def publish(self, name, data=None, source="system"):
        self.published.append(SimpleNamespace(name=name, data=data, source=source))
        return True


def _runner(database, monkeypatch, *, standalone=False):
    agent = SimpleNamespace(
        name="ObservationRunner",
        cycle_count=1,
        energy=100.0,
        emotional_state=EmotionalState(),
        life_guard=SimpleNamespace(database=None if standalone else database),
        goals={"unchanged": True},
    )
    bus = RecordingBus()
    runner = AgentRunner(agent, bus, watchdog=SimpleNamespace(get_status=lambda: {}))
    monkeypatch.setattr(
        "src.ui.life_snapshot.build_life_snapshot",
        lambda current, current_runner: _snapshot(current.cycle_count),
    )
    return runner, bus


def _rows(database, name):
    return database.read_metric_samples(names=[name])


def test_runner_sampling_episodes_and_restart_have_no_duplicates(tmp_path, monkeypatch):
    database = _database(tmp_path)
    runner, _ = _runner(database, monkeypatch)

    assert runner._save_state_observation() is True
    assert runner._save_state_observation() is True
    assert len(_rows(database, OBSERVATION_NAME)) == 1

    runner.agent.cycle_count = 4
    runner.agent.emotional_state.handle_event("remembered_past", cycle=4)
    runner._save_state_observation()
    runner.agent.cycle_count = 15
    runner.agent.emotional_state.handle_event("remembered_past", cycle=15)
    runner._save_state_observation()
    assert len(_rows(database, OBSERVATION_NAME)) == 1
    assert [row["cycle"] for row in _rows(database, EPISODE_NAME)] == [4, 15]

    runner.agent.cycle_count = 30
    runner._save_state_observation()
    assert len(_rows(database, OBSERVATION_NAME)) == 2

    restarted, _ = _runner(database, monkeypatch)
    restarted.agent = runner.agent
    assert restarted._save_state_observation() is True
    assert len(_rows(database, OBSERVATION_NAME)) == 2
    assert len(_rows(database, EPISODE_NAME)) == 2
    assert restarted.get_status()["state_observation_journal"]["backend"] == "sqlite"


def test_writer_failure_is_fail_open_visible_and_recovered_with_gap(
    tmp_path, monkeypatch
):
    database = _database(tmp_path)
    runner, _ = _runner(database, monkeypatch)
    runner._save_state_observation()
    original = database.append_metric_samples

    def fail(_records):
        raise RuntimeError("injected observation writer failure")

    monkeypatch.setattr(database, "append_metric_samples", fail)
    runner.agent.cycle_count = 2
    assert runner._save_state_observation(force=True) is False
    status = runner.get_status()["state_observation_journal"]
    assert status["last_error_type"] == "RuntimeError"
    assert status["dropped_events"] >= 1

    degraded = runner.export_state_observation(tmp_path / "degraded.zip")
    assert degraded["fresh_snapshot"] is False
    assert degraded["manifest"]["counts"]["observations"] == 1
    assert (
        "writer_dropped_events" in degraded["manifest"]["completeness"]["limitations"]
    )

    monkeypatch.setattr(database, "append_metric_samples", original)
    assert runner._save_state_observation(force=True) is True
    assert len(_rows(database, GAP_NAME)) == 1
    assert runner.get_status()["state_observation_journal"]["last_error"] is None


def test_export_registers_artifact_without_mutating_agent(tmp_path, monkeypatch):
    database = _database(tmp_path)
    runner, bus = _runner(database, monkeypatch)
    before = deepcopy(runner.agent.emotional_state.get_status())
    goals_before = deepcopy(runner.agent.goals)

    result = runner.export_state_observation()

    assert result["fresh_snapshot"] is True
    assert result["artifact_id"]
    assert database.get_artifact(result["artifact_id"])["relative_path"].endswith(
        ".zip"
    )
    assert runner.agent.emotional_state.get_status() == before
    assert runner.agent.goals == goals_before
    assert result["manifest"]["life_id"] == database.life_id


@pytest.mark.asyncio
async def test_export_event_returns_actual_result(tmp_path, monkeypatch):
    database = _database(tmp_path)
    runner, bus = _runner(database, monkeypatch)
    destination = tmp_path / "chosen.zip"

    await runner._on_state_export(
        SimpleNamespace(
            data={"request_id": "req-state", "destination": str(destination)}
        )
    )

    result = bus.published[-1]
    assert result.name == Events.STATE_EXPORT_RESULT
    assert result.data["request_id"] == "req-state"
    assert result.data["ok"] is True
    assert result.data["path"] == str(destination)
    assert result.data["artifact_id"] is None
    assert destination.is_file()


def test_two_runner_exports_and_standalone_are_isolated(tmp_path, monkeypatch):
    first = _database(tmp_path)
    second = _database(tmp_path)
    first_runner, _ = _runner(first, monkeypatch)
    second_runner, _ = _runner(second, monkeypatch)
    first_runner._save_state_observation()
    second_runner.agent.cycle_count = 8
    second_runner._save_state_observation()

    first_export = first_runner.export_state_observation()
    second_export = second_runner.export_state_observation()
    assert first_export["manifest"]["life_id"] == first.life_id
    assert second_export["manifest"]["life_id"] == second.life_id
    assert first.life_id != second.life_id
    assert first_export["manifest"]["period"]["last_cycle"] == 1
    assert second_export["manifest"]["period"]["last_cycle"] == 8

    sandbox = tmp_path / "standalone-data"
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(sandbox))
    standalone, _ = _runner(None, monkeypatch, standalone=True)
    assert standalone._save_state_observation() is False
    assert (
        standalone.get_status()["state_observation_journal"]["backend"] == "unavailable"
    )
    with pytest.raises(RuntimeError, match="managed LifeDatabase"):
        standalone.export_state_observation()
    assert not list(sandbox.rglob("*.zip")) if sandbox.exists() else True
