"""Этап 4: музыкальные аффекты имеют наблюдаемую причину и cooldown."""

from copy import deepcopy

import pytest

from src.cognition.music_affect import select_music_affect
from src.cognition.music_attention import listening_candidate
from src.cognition.music_memory import MusicMemory
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent


WORK_ID = "a" * 32


def _observation(revision=1):
    return {
        "schema_version": 1,
        "work_id": WORK_ID,
        "theme": "тишина",
        "revision": revision,
        "sha256": f"{revision:064x}",
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


def _selection(candidate):
    return {**deepcopy(candidate), "verdict": "proceed", "reasoning": "test"}


def _compose(agent):
    agent.act("compose_music")
    return dict(agent._music_work)


def _listen(agent):
    before = len(agent.emotional_state.episodes)
    text = agent.act("listen_music", intention=_selection(listening_candidate(agent)))
    new_episodes = agent.emotional_state.episodes[before:]
    assert len(new_episodes) <= 1
    return {
        "text": text,
        "affect": new_episodes[-1] if new_episodes else None,
    }


def test_first_listen_creates_one_real_curiosity_episode(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="MusicFirstAffect")
    work = _compose(agent)

    result = _listen(agent)

    episode = result["affect"]
    assert episode["event"] == "novel_stimulus"
    assert episode["emotion"] == "curiosity"
    assert episode["intensity"] == pytest.approx(0.3)
    remembered = agent.music_memory.get_work(work["id"])
    assert remembered["personal_significance"] == pytest.approx(0.075)
    assert remembered["associations"] == [
        {
            "cycle": 0,
            "event": "novel_stimulus",
            "emotion": "curiosity",
            "intensity": pytest.approx(0.3),
            "revision": work["revision"],
            "sha256": work["sha256"],
        }
    ]


def test_immediate_repeats_do_not_farm_novelty_or_significance(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="MusicNoAffectFarm")
    work = _compose(agent)
    _listen(agent)
    initial = agent.music_memory.get_work(work["id"])

    for cycle in range(1, 5):
        agent.cycle_count = cycle
        assert _listen(agent)["affect"] is None

    remembered = agent.music_memory.get_work(work["id"])
    assert remembered["listen_count"] == 5
    assert remembered["familiarity"] > initial["familiarity"]
    assert remembered["personal_significance"] == initial["personal_significance"]
    assert remembered["associations"] == initial["associations"]
    assert (
        len(
            [
                episode
                for episode in agent.emotional_state.episodes
                if episode["event"] == "novel_stimulus"
            ]
        )
        == 1
    )


def test_changed_revision_surprises_only_against_real_expectation(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="MusicExpectedRevision")
    work = _compose(agent)
    _listen(agent)
    agent.cycle_count = 1
    revised = _compose(agent)
    assert revised["id"] == work["id"]
    assert revised["revision"] == work["revision"] + 1
    agent.cycle_count = 2

    result = _listen(agent)

    assert result["affect"]["event"] == "unexpected_outcome"
    assert result["affect"]["emotion"] == "surprise"
    remembered = agent.music_memory.get_work(work["id"])
    assert remembered["associations"][-1]["event"] == "unexpected_outcome"
    assert remembered["last_revision"] == revised["revision"]


def test_revision_number_alone_is_not_evidence_of_surprise():
    memory = MusicMemory()
    memory.record_observation(_observation(), cycle=0)
    previous = memory.get_work(WORK_ID)

    affect = select_music_affect(_observation(revision=2), previous, cycle=1)

    assert affect["event"] == "novel_stimulus"
    assert affect["event"] != "unexpected_outcome"


def test_novelty_cooldown_applies_to_quick_successive_revisions():
    memory = MusicMemory()
    observation = _observation()
    memory.record_observation(observation, cycle=0)
    memory.record_affect(
        observation,
        {
            "cycle": 0,
            "event": "novel_stimulus",
            "emotion": "curiosity",
            "intensity": 0.3,
        },
    )
    previous = memory.get_work(WORK_ID)

    assert select_music_affect(_observation(revision=2), previous, cycle=1) is None
    later = select_music_affect(_observation(revision=2), previous, cycle=12)
    assert later["event"] == "novel_stimulus"


def test_nostalgia_requires_old_real_association_not_listen_count():
    neutral = MusicMemory()
    for cycle in range(30):
        neutral.record_observation(_observation(), cycle=cycle)
    assert (
        select_music_affect(_observation(), neutral.get_work(WORK_ID), cycle=100)
        is None
    )

    affected = MusicMemory()
    observation = _observation()
    affected.record_observation(observation, cycle=0)
    affected.record_affect(
        observation,
        {
            "cycle": 0,
            "event": "novel_stimulus",
            "emotion": "curiosity",
            "intensity": 0.3,
        },
    )
    remembered = affected.get_work(WORK_ID)
    assert select_music_affect(observation, remembered, cycle=23) is None

    affect = select_music_affect(observation, remembered, cycle=24)
    assert affect["event"] == "remembered_past"
    assert "из цикла 0" in affect["cause"]


def test_restart_preserves_association_and_response_cooldown(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="MusicAffectRestart")
    work = _compose(agent)
    _listen(agent)
    state = build_state_from_agent(agent)
    restored = DigitalBeing(name="MusicAffectRestart")
    apply_state_to_agent(restored, state)
    initial = restored.music_memory.get_work(work["id"])

    restored.cycle_count = 1
    assert _listen(restored)["affect"] is None
    restored.cycle_count = 24
    remembered = _listen(restored)
    assert remembered["affect"]["event"] == "remembered_past"
    assert remembered["affect"]["emotion"] == "nostalgia"
    after_memory = restored.music_memory.get_work(work["id"])
    assert after_memory["personal_significance"] > initial["personal_significance"]

    cooled = DigitalBeing(name="MusicAffectRestart")
    apply_state_to_agent(cooled, build_state_from_agent(restored))
    cooled.cycle_count = 25
    significance = after_memory["personal_significance"]
    assert _listen(cooled)["affect"] is None
    assert (
        cooled.music_memory.get_work(work["id"])["personal_significance"]
        == significance
    )

    cooled.cycle_count = 36
    assert _listen(cooled)["affect"]["event"] == "remembered_past"
