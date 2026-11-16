"""Decision Episode: замысел и наблюдаемый результат не подменяют друг друга."""

from copy import deepcopy

import pytest

from config.simulation_config import LR_CONFIG
from src.cognition.decision_episode import finish_decision_episode
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_history import (
    begin_intention,
    finish_intention,
    restore_history,
    validate_history,
)
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.loop_closure import ActionOutcome
from src.core.world_delta import WorldDelta


def outcome(action, *, confirmed=False, reason="", knowledge=0):
    return ActionOutcome(
        action=action,
        delta=WorldDelta(knowledge_entries=knowledge),
        reason=reason,
        confirmed_result=confirmed,
    )


def finish(agent, entry, result=None, before=None, after=None):
    finish_intention(entry, result)
    finish_evidence_goal(agent, entry)
    finish_decision_episode(
        agent,
        entry,
        outcome=result,
        activity_before=before,
        activity_after=after,
    )


def test_expectation_is_created_before_execution_and_not_rewritten():
    agent = DigitalBeing(name="EpisodeContract")
    entry = begin_intention(
        agent,
        {
            "action": "explore",
            "source": "active_goal",
            "params": {"topic": "память", "goal_id": 7, "reason": "карта"},
        },
    )
    episode = entry["decision_episode"]
    expected = deepcopy(episode)

    assert episode["intention_id"] == entry["id"]
    assert episode["goal_id"] == 7
    assert episode["criterion"] == "new_topic_evidence"
    assert episode["satisfaction"] == "pending"
    assert episode["resolution"] == "none"

    finish(agent, entry, outcome("explore", knowledge=1))

    assert entry["outcome"]["had_effect"] is True
    assert episode["satisfaction"] == "pending"
    assert episode["resolution"] == "continue"
    for field in (
        "version",
        "intention_id",
        "action",
        "target",
        "source",
        "goal_id",
        "reason",
        "expected_evidence",
        "criterion",
        "baseline",
    ):
        assert episode[field] == expected[field]


def test_explore_requires_new_source_on_the_same_topic():
    agent = DigitalBeing(name="EpisodeEvidence")
    entry = begin_intention(agent, {"action": "explore", "params": {"topic": "память"}})
    agent.mental_models.encounter_concept(
        "другая тема",
        "наблюдение",
        "Наблюдение относится к другой теме",
        evidence_strength=0.7,
        evidence_kind="observation",
        source="other:1",
    )
    finish(agent, entry, outcome("explore", knowledge=1))
    assert entry["decision_episode"]["satisfaction"] == "pending"

    agent.mental_models.encounter_concept(
        "память",
        "наблюдение",
        "Состояние памяти сохранилось после перезапуска",
        evidence_strength=0.7,
        evidence_kind="observation",
        source="memory:1",
    )
    finish_evidence_goal(agent, entry)
    finish_decision_episode(agent, entry, outcome=outcome("explore"))
    assert entry["decision_episode"]["satisfaction"] == "satisfied"
    assert entry["decision_episode"]["resolution"] == "let_go"


@pytest.mark.parametrize("terminal", ["denied", "error", "unobserved", "interrupted"])
def test_unsuccessful_execution_is_never_satisfied(terminal):
    agent = DigitalBeing(name=f"Episode{terminal}")
    entry = begin_intention(agent, {"action": "play", "source": "test"})
    result = None
    if terminal == "denied":
        result = outcome("play", confirmed=True, reason="denied: test")
        finish_intention(entry, result)
    elif terminal == "error":
        finish_intention(entry, error=RuntimeError("boom"))
    elif terminal == "interrupted":
        entry = restore_history([entry])[0]
    else:
        finish_intention(entry)
    finish_decision_episode(agent, entry, outcome=result)

    assert entry["status"] == terminal
    assert entry["decision_episode"]["satisfaction"] == "pending"
    assert entry["decision_episode"]["resolution"] == "none"


def test_rest_at_energy_ceiling_is_not_a_false_failure():
    agent = DigitalBeing(name="EpisodeRestCeiling")
    agent.energy = float(LR_CONFIG.ENERGY_MAX)
    entry = begin_intention(agent, {"action": "rest", "source": "body"})
    finish(agent, entry, outcome("rest"))

    assert entry["decision_episode"]["satisfaction"] == "not_applicable"
    assert entry["decision_episode"]["resolution"] == "none"


def test_confirmed_body_recovery_satisfies_rest():
    agent = DigitalBeing(name="EpisodeRestRecovery")
    agent.energy = 20
    entry = begin_intention(agent, {"action": "deep_rest", "source": "body"})
    finish(agent, entry, outcome("deep_rest", confirmed=True))

    assert entry["decision_episode"]["satisfaction"] == "satisfied"


@pytest.mark.parametrize(
    "action,before,after,confirmed",
    [
        ("play", {"round": 1}, {"round": 1, "board": ["X"]}, True),
        (
            "create_draft",
            {"id": "d", "revision": 1, "status": "active"},
            {"id": "d", "revision": 2, "status": "active"},
            False,
        ),
        (
            "draw",
            {"id": "a", "revision": 1, "status": "active"},
            {"id": "a", "revision": 2, "status": "active"},
            False,
        ),
        (
            "compose_music",
            {"id": "m", "revision": 1, "status": "active"},
            {"id": "m", "revision": 2, "status": "active"},
            False,
        ),
    ],
)
def test_activity_satisfaction_uses_its_own_observed_step(
    action, before, after, confirmed
):
    agent = DigitalBeing(name=f"Episode{action}")
    entry = begin_intention(agent, {"action": action, "source": "test"})
    finish(agent, entry, outcome(action, confirmed=confirmed), before, after)

    assert entry["decision_episode"]["satisfaction"] == "satisfied"


@pytest.mark.parametrize("action", ["create_draft", "draw", "compose_music"])
def test_leave_or_unchanged_work_is_not_a_new_revision(action):
    agent = DigitalBeing(name=f"EpisodeLeave{action}")
    before = {"id": "work", "revision": 3, "status": "active"}
    after = {"id": "work", "revision": 3, "status": "left"}
    entry = begin_intention(agent, {"action": action, "source": "test"})
    finish(agent, entry, outcome(action, confirmed=True), before, after)

    assert entry["decision_episode"]["satisfaction"] == "pending"


def test_action_without_adapter_remains_not_applicable_despite_world_delta():
    agent = DigitalBeing(name="EpisodeNoAdapter")
    entry = begin_intention(agent, {"action": "communicate", "source": "test"})
    finish(agent, entry, outcome("communicate", confirmed=True, knowledge=1))

    assert entry["status"] == "performed"
    assert entry["decision_episode"]["satisfaction"] == "not_applicable"
    assert entry["decision_episode"]["resolution"] == "none"


def test_episode_does_not_complete_arbitrary_goal():
    agent = DigitalBeing(name="EpisodeGoalBoundary")
    goal_id = agent.set_goal("Широкая цель", activate=True)
    entry = begin_intention(
        agent,
        {
            "action": "explore",
            "params": {"topic": "память", "goal_id": goal_id},
        },
    )
    agent.mental_models.encounter_concept(
        "память",
        "наблюдение",
        "Новый источник подтверждает только узкое свидетельство",
        evidence_strength=0.7,
        evidence_kind="observation",
        source="memory:2",
    )
    finish(agent, entry, outcome("explore"))

    assert entry["decision_episode"]["satisfaction"] == "satisfied"
    assert agent.active_goal["id"] == goal_id
    assert agent.active_goal["status"] == "active"


def test_old_checkpoint_without_episode_and_interrupted_contract_are_safe():
    agent = DigitalBeing(name="EpisodeRestore")
    begin_intention(agent, {"action": "explore", "params": {"topic": "память"}})
    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    restored = agent._intention_history[-1]
    assert restored["status"] == "interrupted"
    assert restored["decision_episode"]["satisfaction"] == "pending"
    assert restored["decision_episode"]["resolution"] == "none"
    assert state["intention_history"][-1]["status"] == "started"

    legacy = build_state_from_agent(agent)
    del legacy["intention_history"][-1]["decision_episode"]
    apply_state_to_agent(agent, legacy)
    assert "decision_episode" not in agent._intention_history[-1]


def test_effector_success_without_revision_observation_is_not_satisfied():
    agent = DigitalBeing(name="EpisodeEffector")
    entry = begin_intention(agent, {"action": "create_draft", "source": "effector"})
    agent._on_effector_result(
        {
            "status": "succeeded",
            "request_id": "req-episode",
            "ok": True,
            "error": None,
            "detail": {"metadata": {"intention_id": entry["id"]}},
        }
    )

    assert entry["status"] == "performed"
    assert entry["decision_episode"]["satisfaction"] == "not_applicable"


def test_queued_question_is_a_structural_satisfied_result():
    from unittest.mock import patch

    agent = DigitalBeing(name="EpisodeQuestion")
    agent.cycle_count = 60
    selected = {
        "action": "ask_user",
        "source": "test",
        "verdict": "proceed",
        "params": {"topic": "память"},
    }
    with patch.object(
        agent.decision_arbitrator, "choose_action", return_value=selected
    ):
        agent.autonomous_tick()

    entry = agent._intention_history[-1]
    assert entry["outcome"]["confirmed_result"] is True
    assert entry["decision_episode"]["satisfaction"] == "satisfied"
    assert entry["decision_episode"]["resolution"] == "wait"


@pytest.mark.parametrize(
    "corruption,path",
    [
        (lambda episode: episode.update(satisfaction="unknown"), "satisfaction"),
        (lambda episode: episode.update(baseline=[]), "baseline"),
        (lambda episode: episode.update(intention_id="other"), "intention_id"),
        (
            lambda episode: episode.update(satisfaction="satisfied"),
            "satisfaction",
        ),
    ],
)
def test_episode_validation_rejects_inconsistent_contract(corruption, path):
    agent = DigitalBeing(name="EpisodeValidation")
    entry = begin_intention(agent, {"action": "play", "source": "test"})
    corruption(entry["decision_episode"])

    with pytest.raises(ValueError, match=path):
        validate_history([entry])


@pytest.mark.parametrize(
    "action,attr", [("draw", "_art_work"), ("compose_music", "_music_work")]
)
def test_real_creative_tick_satisfies_only_after_revision(
    tmp_path, monkeypatch, action, attr
):
    from unittest.mock import patch

    from src.core.activity_workspace import ActivityWorkspace

    monkeypatch.setattr(
        "src.core.activity_workspace.workspace_for",
        lambda agent: ActivityWorkspace(root=tmp_path),
    )
    agent = DigitalBeing(name=f"EpisodeReal{action}")
    selected = {"action": action, "source": "test", "verdict": "proceed"}
    with patch.object(
        agent.decision_arbitrator, "choose_action", return_value=selected
    ):
        agent.autonomous_tick()

    entry = agent._intention_history[-1]
    assert getattr(agent, attr)["revision"] == 1
    assert entry["decision_episode"]["baseline"]["revision"] == 0
    assert entry["decision_episode"]["satisfaction"] == "satisfied"


@pytest.mark.parametrize(
    "action,handler",
    [("draw", "_act_draw"), ("compose_music", "_act_compose_music")],
)
def test_plausible_failure_text_is_not_creative_evidence(action, handler):
    from unittest.mock import patch

    agent = DigitalBeing(name=f"EpisodeText{action}")
    selected = {"action": action, "source": "test", "verdict": "proceed"}
    with patch.object(
        agent.decision_arbitrator, "choose_action", return_value=selected
    ), patch.object(
        agent, handler, return_value={"text": "Ответ: хотела, но не получилось"}
    ):
        agent.autonomous_tick()

    entry = agent._intention_history[-1]
    assert entry["status"] == "performed"
    assert entry["decision_episode"]["satisfaction"] == "pending"
