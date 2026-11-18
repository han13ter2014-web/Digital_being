"""P3-C-2: реальные творческие редакции замыкают общий контур исхода."""

import pytest

from src.core.agent import DigitalBeing


@pytest.mark.parametrize(
    "action,attr,kind",
    [
        ("draw", "_art_work", "рисунок"),
        ("compose_music", "_music_work", "мелодия"),
    ],
)
def test_real_creative_revisions_confirm_outcome_emotion_and_valence(
    action, attr, kind, monkeypatch
):
    agent = DigitalBeing(name=f"CreativeOutcome_{action}")
    valences = []
    original = agent.motivation_system.on_action_result

    def observe_valence(action_type, success, valence):
        valences.append((action_type, success, valence))
        return original(action_type, success, valence)

    monkeypatch.setattr(agent.motivation_system, "on_action_result", observe_valence)
    joy_before = agent.emotional_state.levels["joy"]

    for revision in (1, 2):
        agent.act(action)
        work = getattr(agent, attr)
        outcome = agent._last_action_outcome

        assert work["revision"] == revision
        assert outcome.confirmed_result is True
        assert outcome.had_effect is True
        assert outcome.delta.is_empty is True
        assert work["id"] in outcome.result_description
        assert kind in outcome.result_description
        assert f"редакция {revision}" in outcome.result_description
        assert agent.loop_closer.no_effect_streak(action) == 0
        assert valences[-1][:2] == (action, True)
        assert valences[-1][2] > 0.0

    completed = [
        episode
        for episode in agent.emotional_state.episodes
        if episode["event"] == "intention_completed"
    ]
    assert completed
    assert agent.emotional_state.last_causes["joy"][1] == action
    assert agent.emotional_state.levels["joy"] > joy_before


@pytest.mark.parametrize(
    "action,module,availability",
    [
        ("draw", "src.cognition.local_art", "art_available"),
        ("compose_music", "src.cognition.local_music", "music_available"),
    ],
)
def test_unavailable_creative_work_is_not_confirmed(
    action, module, availability, monkeypatch
):
    agent = DigitalBeing(name=f"CreativeUnavailable_{action}")
    monkeypatch.setattr(f"{module}.{availability}", lambda *args, **kwargs: False)

    agent.act(action)

    outcome = agent._last_action_outcome
    assert outcome.confirmed_result is False
    assert outcome.had_effect is False
    assert outcome.result_description == ""


@pytest.mark.parametrize(
    "action,module,step",
    [
        ("draw", "src.cognition.local_art", "art_step"),
        ("compose_music", "src.cognition.local_music", "music_step"),
    ],
)
def test_creative_write_error_is_not_confirmed(action, module, step, monkeypatch):
    agent = DigitalBeing(name=f"CreativeError_{action}")

    def fail(*args, **kwargs):
        raise OSError("изолированная ошибка записи")

    monkeypatch.setattr(f"{module}.{step}", fail)
    agent.act(action)

    outcome = agent._last_action_outcome
    assert outcome.confirmed_result is False
    assert outcome.had_effect is False
    assert outcome.result_description == ""


@pytest.mark.parametrize("action", ["draw", "compose_music"])
@pytest.mark.parametrize(
    "result",
    [
        {"text": "Ответ: оставила работу"},
        {"text": "Ответ: без изменений", "revision_created": False},
        {
            "text": "Ответ: повреждённый ответ",
            "revision_created": True,
            "work_id": "work",
        },
    ],
)
def test_leave_no_revision_or_incomplete_evidence_is_not_confirmed(
    action, result, monkeypatch
):
    agent = DigitalBeing(name=f"CreativeBoundary_{action}")
    handler_name = "_act_draw" if action == "draw" else "_act_compose_music"
    monkeypatch.setattr(agent, handler_name, lambda: dict(result))

    agent.act(action)

    outcome = agent._last_action_outcome
    assert outcome.confirmed_result is False
    assert outcome.had_effect is False
    assert outcome.result_description == ""
