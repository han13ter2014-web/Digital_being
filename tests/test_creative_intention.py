"""P3-C-0: наблюдаемое творческое намерение без изменения политики выбора."""

from copy import deepcopy

import pytest

from src.cognition.intention_history import begin_intention, validate_history
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent


@pytest.mark.parametrize(
    "action,attr,form",
    [
        ("create_draft", "_creative_draft", "text"),
        ("draw", "_art_work", "art"),
        ("compose_music", "_music_work", "music"),
    ],
)
def test_creative_intention_distinguishes_new_and_continuation(action, attr, form):
    agent = DigitalBeing(name=f"CreativeIntention{form}")
    new_entry = begin_intention(agent, {"action": action, "source": "test"})

    intention = new_entry["decision_episode"]["creative_intention"]
    assert intention == {
        "schema_version": 1,
        "form": form,
        "operation": "new",
        "work_id": None,
        "revision": 0,
        "status": None,
        "reason": "",
    }

    work = {"id": "work-1", "revision": 3, "status": "active"}
    setattr(agent, attr, deepcopy(work))
    continued = begin_intention(agent, {"action": action, "source": "test"})
    intention = continued["decision_episode"]["creative_intention"]

    assert intention["form"] == form
    assert intention["operation"] == "continue"
    assert intention["work_id"] == "work-1"
    assert intention["revision"] == 3
    assert intention["status"] == "active"
    assert continued["decision_episode"]["baseline"]["revision"] == 3


def test_text_intention_preserves_explicit_new_and_leave_requests():
    agent = DigitalBeing(name="CreativeIntentionTextRequests")
    current = {"id": "a" * 32, "revision": 2, "status": "active"}
    other = {"id": "b" * 32, "revision": 4, "status": "active"}
    agent._creative_draft = deepcopy(current)
    agent._creative_catalog = {other["id"]: deepcopy(other)}

    new_entry = begin_intention(
        agent,
        {"action": "create_draft", "params": {"draft_mode": "new"}},
    )
    new_intention = new_entry["decision_episode"]["creative_intention"]
    assert new_intention["operation"] == "new"
    assert new_intention["work_id"] is None
    assert new_intention["revision"] == 0

    leave_entry = begin_intention(
        agent,
        {
            "action": "create_draft",
            "params": {
                "draft_mode": "leave",
                "draft_id": other["id"],
                "reason": "работа завершена",
            },
        },
    )
    leave_intention = leave_entry["decision_episode"]["creative_intention"]
    assert leave_intention["operation"] == "leave"
    assert leave_intention["work_id"] == other["id"]
    assert leave_intention["revision"] == 4
    assert leave_intention["reason"] == "работа завершена"


def test_creative_intention_survives_checkpoint_and_legacy_remains_readable():
    agent = DigitalBeing(name="CreativeIntentionRestart")
    agent._art_work = {"id": "art-1", "revision": 2, "status": "active"}
    entry = begin_intention(agent, {"action": "draw", "source": "test"})
    expected = deepcopy(entry["decision_episode"]["creative_intention"])

    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    restored = agent._intention_history[-1]
    assert restored["status"] == "interrupted"
    assert restored["decision_episode"]["creative_intention"] == expected

    legacy = deepcopy(state)
    del legacy["intention_history"][-1]["decision_episode"]["creative_intention"]
    apply_state_to_agent(agent, legacy)
    assert "creative_intention" not in agent._intention_history[-1]["decision_episode"]


def test_motivation_creative_act_alias_survives_checkpoint_validation():
    agent = DigitalBeing(name="CreativeIntentionAlias")
    entry = begin_intention(agent, {"action": "creative_act", "source": "motivation"})
    assert entry["decision_episode"]["creative_intention"]["form"] == "text"

    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    restored = agent._intention_history[-1]["decision_episode"]["creative_intention"]
    assert restored["form"] == "text"
    assert restored["operation"] == "new"


@pytest.mark.parametrize(
    "mutation,path",
    [
        (lambda item: item.update(form="music"), "form"),
        (lambda item: item.update(operation="rotate"), "operation"),
        (lambda item: item.update(revision=-1), "revision"),
        (lambda item: item.update(work_id=7), "work_id"),
        (lambda item: item.update(status="finished"), "status"),
        (lambda item: item.update(schema_version=2), "schema_version"),
    ],
)
def test_creative_intention_validation_rejects_inconsistent_snapshots(mutation, path):
    agent = DigitalBeing(name="CreativeIntentionValidation")
    entry = begin_intention(agent, {"action": "draw", "source": "test"})
    mutation(entry["decision_episode"]["creative_intention"])

    with pytest.raises(ValueError, match=path):
        validate_history([entry])


def test_non_creative_episode_has_no_creative_intention():
    agent = DigitalBeing(name="CreativeIntentionBoundary")
    entry = begin_intention(agent, {"action": "play", "source": "test"})
    assert "creative_intention" not in entry["decision_episode"]
    validate_history([entry])
