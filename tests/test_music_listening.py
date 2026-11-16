"""Прослушивание собственной мелодии: жизненный цикл и нейтральные повторы."""

from copy import deepcopy
from unittest.mock import patch

from src.cognition.music_attention import listening_candidate
from src.core.activity_workspace import workspace_for
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent


def _compose(agent):
    agent.act("compose_music")
    return dict(agent._music_work)


def _selection(candidate):
    return {**deepcopy(candidate), "verdict": "proceed", "reasoning": "test"}


def test_without_own_music_there_is_no_listen_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ListenWithoutMusic")

    assert agent._normalize_action("listen_music") == "listen_music"
    assert listening_candidate(agent) is None
    assert not agent._is_action_available("listen_music")
    result = agent.act("listen_music")

    assert "нет собственной мелодии" in result
    assert agent.music_memory.to_checkpoint()["works"] == {}
    assert not agent._last_action_outcome.had_effect


def test_compose_marks_unheard_revision_but_does_not_force_listening(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ListenOptional")
    work = _compose(agent)
    expected = {
        "work_id": work["id"],
        "revision": work["revision"],
        "sha256": work["sha256"],
    }

    assert agent._unheard_music_revision == expected
    assert agent.music_memory.get_work(work["id"]) is None
    captured = {}

    def choose_wait(candidates, _context):
        captured["candidates"] = deepcopy(candidates)
        return {"action": "wait", "source": "test", "verdict": "proceed"}

    with patch.object(
        agent.decision_arbitrator, "choose_action", side_effect=choose_wait
    ):
        agent.autonomous_tick()

    offered = next(
        candidate
        for candidate in captured["candidates"]
        if candidate["action"] == "listen_music"
    )
    assert offered["params"] | expected == offered["params"]
    assert offered["params"]["unheard"] is True
    assert 0.0 < offered["strength"] <= 0.5
    assert agent.music_memory.get_work(work["id"]) is None


def test_neutral_repeat_adds_no_emotion_knowledge_goal_or_need_reward(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ListenNeutral")
    work = _compose(agent)
    agent.act("listen_music", intention=_selection(listening_candidate(agent)))
    agent.cycle_count += 1
    candidate = listening_candidate(agent)
    before_work = agent.music_memory.get_work(work["id"])
    emotions = deepcopy(agent.emotional_state.to_dict())
    knowledge = deepcopy(agent.knowledge_base)
    models = deepcopy(agent.mental_models.to_storage_dict())
    goals = deepcopy(agent.goals)
    needs = {
        name: need.current_level for name, need in agent.motivation_system.needs.items()
    }

    result = agent.act("listen_music", intention=_selection(candidate))

    assert "прослушала свою мелодию" in result
    remembered = agent.music_memory.get_work(work["id"])
    assert remembered["listen_count"] == 2
    assert remembered["familiarity"] > before_work["familiarity"]
    assert remembered["personal_significance"] == before_work["personal_significance"]
    assert remembered["associations"] == before_work["associations"]
    assert agent._unheard_music_revision is None
    assert agent._last_action_outcome.had_effect
    assert agent.emotional_state.to_dict() == emotions
    assert agent.knowledge_base == knowledge
    assert agent.mental_models.to_storage_dict() == models
    assert agent.goals == goals
    assert {
        name: need.current_level for name, need in agent.motivation_system.needs.items()
    } == needs
    assert agent.motivation_system.predict_valence("listen_music", {}) == 0.0
    assert (
        agent.motivation_system.compute_actual_valence("listen_music", result, True, {})
        == 0.0
    )


def test_selected_listen_uses_ordinary_intention_and_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ListenLifecycle")
    work = _compose(agent)
    selected = _selection(listening_candidate(agent))

    with patch.object(
        agent.decision_arbitrator, "choose_action", return_value=selected
    ):
        report = agent.autonomous_tick()

    assert report["autonomous_action"]["action"] == "listen_music"
    assert report["executed_intention"]["params"]["work_id"] == work["id"]
    assert report["actual_valence"] == 0.0
    entry = agent._intention_history[-1]
    assert entry["action"] == "listen_music"
    assert entry["status"] == "performed"
    assert entry["outcome"]["confirmed_result"] is True
    assert agent.music_memory.get_work(work["id"])["listen_count"] == 1


def test_stale_candidate_is_not_applied_to_another_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ListenStale")
    work = _compose(agent)
    candidate = listening_candidate(agent)
    stale = _selection(candidate)
    stale["params"]["revision"] = work["revision"] + 1
    before = agent.music_memory.to_checkpoint()

    assert not agent._is_candidate_available(stale)
    result = agent.act("listen_music", intention=stale)

    assert "прослушивание не состоялось" in result
    assert agent.music_memory.to_checkpoint() == before
    assert not agent._last_action_outcome.had_effect


def test_external_wav_change_creates_no_experience_and_is_not_repaired(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ListenTampered")
    work = _compose(agent)
    candidate = listening_candidate(agent)
    target = workspace_for(agent).root / f"{work['id']}.wav"
    target.write_bytes(target.read_bytes() + b"intruder")
    tampered = target.read_bytes()
    before = agent.music_memory.to_checkpoint()

    result = agent.act("listen_music", intention=_selection(candidate))

    assert "изменена извне" in result
    assert target.read_bytes() == tampered
    assert agent.music_memory.to_checkpoint() == before
    assert not agent._last_action_outcome.had_effect


def test_restart_does_not_make_heard_revision_new_and_repeat_remains_possible(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ListenRestart")
    work = _compose(agent)
    agent.act("listen_music", intention=_selection(listening_candidate(agent)))
    state = build_state_from_agent(agent)

    restored = DigitalBeing(name="ListenRestart")
    apply_state_to_agent(restored, state)
    candidate = listening_candidate(restored)

    assert candidate["params"]["unheard"] is False
    assert restored.music_memory.has_listened(work["id"], 1, work["sha256"])
    initial_significance = restored.music_memory.get_work(work["id"])[
        "personal_significance"
    ]
    assert initial_significance > 0.0
    immediate_strength = candidate["strength"]
    restored.cycle_count += 12
    later = listening_candidate(restored)
    assert later["strength"] > immediate_strength
    restored.act("listen_music", intention=_selection(later))
    remembered = restored.music_memory.get_work(work["id"])
    assert remembered["listen_count"] == 2
    assert remembered["first_listened_cycle"] == 0
    assert remembered["personal_significance"] == initial_significance


def test_listening_adds_no_direct_creative_strength_bonus(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="ListenNoCreativeBonus")
    _compose(agent)
    context = {"energy": agent.energy, "cycle": agent.cycle_count}

    def creative_strengths():
        return [
            (candidate["action"], candidate["strength"])
            for candidate in agent.motivation_system.get_action_candidates(context)
            if agent._normalize_action(candidate["action"])
            in {"compose_music", "draw", "create_draft"}
        ]

    before = creative_strengths()
    agent.act("listen_music", intention=_selection(listening_candidate(agent)))
    after = creative_strengths()

    assert after == before
