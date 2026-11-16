"""Музыкальная память: знакомство, значимость, границы и restart."""

from copy import deepcopy
import json

import pytest

from src.cognition.music_memory import (
    MAX_RECENT_REVISIONS,
    MAX_WORKS,
    MusicMemory,
    validate_music_memory,
)
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.memory.checkpoint_store import SQLiteCheckpointStore


WORK_ID = "a" * 32


def _observation(*, work_id=WORK_ID, revision=1, sha256=None):
    return {
        "schema_version": 1,
        "work_id": work_id,
        "theme": "тишина",
        "revision": revision,
        "sha256": sha256 or f"{revision:064x}",
        "features": {
            "mode": "major_pent",
            "tempo_bpm": 92,
            "note_count": 3,
            "rest_count": 1,
            "note_density": 0.75,
            "pause_ratio": 0.25,
            "pitch_low": 60,
            "pitch_high": 64,
            "pitch_span": 4,
            "repeated_note_ratio": 0.0,
            "phrase_change_ratio": 0.0,
        },
    }


def _episode(cycle=1):
    return {
        "cycle": cycle,
        "event": "novel_stimulus",
        "emotion": "curiosity",
        "intensity": 0.3,
    }


def test_neutral_repeats_build_familiarity_not_significance():
    memory = MusicMemory()
    observation = _observation()

    first = memory.record_observation(observation, cycle=10)
    duplicate = memory.record_observation(observation, cycle=10)
    second = memory.record_observation(observation, cycle=11)

    assert first["familiarity"] == pytest.approx(0.15)
    assert second["familiarity"] == pytest.approx(0.2775)
    assert second["personal_significance"] == 0.0
    assert second["listen_count"] == 2
    assert duplicate["listen_count"] == 1
    assert second["recent_revisions"][0]["listen_count"] == 2
    assert memory.has_listened(WORK_ID, 1, observation["sha256"])


def test_real_episode_adds_significance_once_and_survives_neutral_repeat():
    memory = MusicMemory()
    observation = _observation()
    memory.record_observation(observation, cycle=1)

    affected = memory.record_affect(observation, _episode(cycle=1))
    duplicate = memory.record_affect(observation, _episode(cycle=1))
    memory.record_observation(observation, cycle=2)
    restored = memory.get_work(WORK_ID)

    assert affected["personal_significance"] > 0.0
    assert duplicate["personal_significance"] == affected["personal_significance"]
    assert restored["personal_significance"] == affected["personal_significance"]
    assert len(restored["associations"]) == 1
    assert restored["last_response_by_kind"] == {"novel_stimulus": 1}


def test_affect_requires_actual_matching_listening_and_known_episode():
    memory = MusicMemory()
    observation = _observation()

    with pytest.raises(ValueError, match="ещё не прослушана"):
        memory.record_affect(observation, _episode())

    memory.record_observation(observation, cycle=1)
    with pytest.raises(ValueError, match="последнему прослушиванию"):
        memory.record_affect(observation, _episode(cycle=2))
    with pytest.raises(ValueError, match="не соответствует событию"):
        memory.record_affect(observation, {**_episode(), "emotion": "joy"})
    with pytest.raises(ValueError, match="неизвестное эмоциональное событие"):
        memory.record_affect(observation, {**_episode(), "event": "invented"})
    assert memory.get_work(WORK_ID)["personal_significance"] == 0.0


def test_revision_eviction_preserves_work_aggregates_and_significance():
    memory = MusicMemory()
    memory.record_observation(_observation(), cycle=0)
    memory.record_affect(_observation(), _episode(cycle=0))
    significant = memory.get_work(WORK_ID)["personal_significance"]

    for revision in range(2, MAX_RECENT_REVISIONS + 3):
        memory.record_observation(_observation(revision=revision), cycle=revision - 1)

    work = memory.get_work(WORK_ID)
    assert len(work["recent_revisions"]) == MAX_RECENT_REVISIONS
    assert not memory.has_listened(WORK_ID, 1, f"{1:064x}")
    assert work["listen_count"] == MAX_RECENT_REVISIONS + 2
    assert work["familiarity"] > 0.0
    assert work["personal_significance"] == significant


def test_work_catalog_is_bounded_by_least_recently_heard():
    memory = MusicMemory()
    for index in range(MAX_WORKS + 1):
        work_id = f"{index:032x}"
        memory.record_observation(_observation(work_id=work_id), cycle=index)

    checkpoint = memory.to_checkpoint()
    assert len(checkpoint["works"]) == MAX_WORKS
    assert f"{0:032x}" not in checkpoint["works"]
    assert f"{MAX_WORKS:032x}" in checkpoint["works"]
    validate_music_memory(checkpoint)


def test_checkpoint_json_roundtrip_and_legacy_empty_memory():
    memory = MusicMemory()
    observation = _observation()
    memory.record_observation(observation, cycle=4)
    memory.record_affect(observation, _episode(cycle=4))

    encoded = json.dumps(memory.to_checkpoint(), allow_nan=False)
    restored = MusicMemory.from_checkpoint(json.loads(encoded))

    assert restored.to_checkpoint() == memory.to_checkpoint()
    assert restored.has_listened(WORK_ID, 1, observation["sha256"])
    assert MusicMemory.from_checkpoint({}).to_checkpoint() == {
        "schema_version": 1,
        "works": {},
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state.update({"foreign": True}),
        lambda state: state["works"][WORK_ID].update({"familiarity": float("nan")}),
        lambda state: state["works"][WORK_ID].update({"personal_significance": -0.1}),
        lambda state: state["works"][WORK_ID]["last_features"].update({"foreign": 1}),
        lambda state: state["works"][WORK_ID]["associations"][0].update(
            {"event": "invented"}
        ),
    ],
)
def test_checkpoint_rejects_corrupt_or_foreign_fields(mutate):
    memory = MusicMemory()
    observation = _observation()
    memory.record_observation(observation, cycle=1)
    memory.record_affect(observation, _episode(cycle=1))
    state = memory.to_checkpoint()

    mutate(state)

    with pytest.raises(ValueError):
        validate_music_memory(state)


def test_agent_json_restart_and_legacy_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="MusicMemoryJson")
    agent.cycle_count = 5
    observation = _observation()
    agent.music_memory.record_observation(observation, cycle=5)
    agent.music_memory.record_affect(observation, _episode(cycle=5))
    state = build_state_from_agent(agent)

    restored = DigitalBeing(name="MusicMemoryJson")
    apply_state_to_agent(restored, state)
    assert restored.music_memory.to_checkpoint() == agent.music_memory.to_checkpoint()

    legacy = deepcopy(state)
    del legacy["music_memory"]
    old = DigitalBeing(name="MusicMemoryLegacy")
    apply_state_to_agent(old, legacy)
    assert old.music_memory.to_checkpoint() == {"schema_version": 1, "works": {}}


def test_agent_sqlite_restart_preserves_music_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    agent = DigitalBeing(name="MusicMemorySqlite")
    agent.cycle_count = 6
    observation = _observation()
    agent.music_memory.record_observation(observation, cycle=6)
    state = build_state_from_agent(agent)
    # Production-контур нормализует JSON-ключи перед записью в SQLite.
    state = json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False))
    store = SQLiteCheckpointStore(tmp_path / "checkpoints.sqlite3")

    snapshot_id = store.save(state, agent.name, agent.cycle_count)
    loaded = store.load(snapshot_id)
    restored = DigitalBeing(name="MusicMemorySqlite")
    apply_state_to_agent(restored, loaded)

    assert restored.music_memory.to_checkpoint() == state["music_memory"]


def test_invalid_music_memory_does_not_partially_replace_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="MusicMemoryAtomic")
    agent.cycle_count = 3
    agent.music_memory.record_observation(_observation(), cycle=3)
    before = agent.music_memory.to_checkpoint()
    state = build_state_from_agent(agent)
    state["music_memory"]["works"][WORK_ID]["familiarity"] = float("nan")

    with pytest.raises(ValueError):
        apply_state_to_agent(agent, state)

    assert agent.music_memory.to_checkpoint() == before
