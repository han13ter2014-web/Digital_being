"""Read-only восприятие собственной мелодии: структура и provenance."""

from copy import deepcopy

import pytest

from src.cognition import local_music
from src.cognition.local_music import MOODS, _compose_score, music_step, observe_music
from src.core.activity_workspace import ActivityWorkspace


def _work(tmp_path, *, revision=1):
    workspace = ActivityWorkspace(root=tmp_path)
    state = music_step(None, mood="calm", theme="тишина", workspace=workspace)
    for _ in range(1, revision):
        state = music_step(state, workspace=workspace)
    return workspace, state


def test_observation_reads_full_score_and_features(tmp_path):
    workspace, state = _work(tmp_path, revision=3)

    observation = observe_music(state, workspace=workspace)
    bars = _compose_score(state["theme"], state["mood"], state["revision"])
    events = [event for bar in bars for event in bar]
    notes = [midi for midi, _duration in events if midi is not None]
    features = observation["features"]

    assert observation["schema_version"] == 1
    assert observation["work_id"] == state["id"]
    assert observation["theme"] == state["theme"]
    assert observation["revision"] == 3
    assert observation["sha256"] == state["sha256"]
    assert features["mode"] == MOODS[state["mood"]][0]
    assert features["tempo_bpm"] == MOODS[state["mood"]][2]
    assert features["note_count"] == len(notes)
    assert features["rest_count"] == len(events) - len(notes)
    assert features["note_count"] + features["rest_count"] == len(events)
    assert features["note_density"] == len(notes) / len(events)
    assert features["pause_ratio"] == (len(events) - len(notes)) / len(events)
    assert features["pitch_low"] == min(notes)
    assert features["pitch_high"] == max(notes)
    assert features["pitch_span"] == max(notes) - min(notes)
    expected_repeats = sum(a == b for a, b in zip(notes, notes[1:]))
    assert features["repeated_note_ratio"] == expected_repeats / (len(notes) - 1)
    expected_changes = sum(a != b for a, b in zip(bars, bars[1:]))
    assert features["phrase_change_ratio"] == expected_changes / (len(bars) - 1)


def test_observation_is_deterministic_and_does_not_change_work(tmp_path):
    workspace, state = _work(tmp_path, revision=2)
    before = deepcopy(state)
    target = tmp_path / f"{state['id']}.wav"
    content = target.read_bytes()

    first = observe_music(state, workspace=workspace)
    second = observe_music(state, workspace=workspace)

    assert first == second
    assert state == before
    assert target.read_bytes() == content


def test_observation_rejects_stale_candidate_revision_and_hash(tmp_path):
    workspace, state = _work(tmp_path)

    with pytest.raises(ValueError, match="редакция мелодии изменилась"):
        observe_music(state, workspace=workspace, expected_revision=2)
    with pytest.raises(ValueError, match="ожидалась другая версия"):
        observe_music(state, workspace=workspace, expected_sha256="0" * 64)

    matched = observe_music(
        state,
        workspace=workspace,
        expected_revision=state["revision"],
        expected_sha256=state["sha256"],
    )
    assert matched["work_id"] == state["id"]


def test_observation_rejects_tampered_wav_without_repairing_it(tmp_path):
    workspace, state = _work(tmp_path)
    target = tmp_path / f"{state['id']}.wav"
    target.write_bytes(target.read_bytes() + b"intruder")

    with pytest.raises(ValueError, match="изменена извне"):
        observe_music(state, workspace=workspace)
    assert target.read_bytes().endswith(b"intruder")


def test_observation_requires_existing_wav(tmp_path):
    workspace, state = _work(tmp_path)
    target = tmp_path / f"{state['id']}.wav"
    target.unlink()

    with pytest.raises(FileNotFoundError):
        observe_music(state, workspace=workspace)


@pytest.mark.parametrize(
    "bars",
    [
        [],
        [[]],
        [[(60, 0.0)]],
        [[(True, 1.0)]],
        [[(60, float("nan"))]],
        [[(128, 1.0)]],
    ],
)
def test_observation_rejects_empty_or_invalid_score(tmp_path, monkeypatch, bars):
    workspace, state = _work(tmp_path)
    monkeypatch.setattr(local_music, "_compose_score", lambda *_args: bars)

    with pytest.raises(ValueError, match="local_music.observation"):
        observe_music(state, workspace=workspace)


def test_observation_of_all_rest_score_has_no_invented_pitch(tmp_path, monkeypatch):
    workspace, state = _work(tmp_path)
    monkeypatch.setattr(local_music, "_compose_score", lambda *_args: [[(None, 4.0)]])

    features = observe_music(state, workspace=workspace)["features"]

    assert features["note_count"] == 0
    assert features["rest_count"] == 1
    assert features["note_density"] == 0.0
    assert features["pause_ratio"] == 1.0
    assert features["pitch_low"] is None
    assert features["pitch_high"] is None
    assert features["pitch_span"] is None
    assert features["repeated_note_ratio"] == 0.0
    assert features["phrase_change_ratio"] == 0.0
