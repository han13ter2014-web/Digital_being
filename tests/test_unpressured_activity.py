"""Отсутствие дефицита не создаёт обязанности исследовать."""

from src.core.agent import DigitalBeing


def test_satisfied_needs_allow_pause_without_invented_curiosity():
    agent = DigitalBeing(name="UnpressuredPause")
    system = agent.motivation_system
    for need in system.needs.values():
        need.current_level = need.base_level
    for drive in system.drives.values():
        drive.current_level = 0
    before = {name: need.current_level for name, need in system.needs.items()}
    candidates = system.get_action_candidates({})
    assert len(candidates) == 1
    assert candidates[0]["action"] == "wait"
    assert candidates[0]["need"] is None
    assert {name: need.current_level for name, need in system.needs.items()} == before


def test_pause_selection_does_not_execute_research(monkeypatch):
    from unittest.mock import Mock

    agent = DigitalBeing(name="PauseNotFailure")
    monkeypatch.setattr(agent.decision_arbitrator, "choose_action", lambda candidates, context: {
        "action": "wait", "source": "motivation", "verdict": "proceed",
        "params": {"reason": "no_pressing_needs"},
    })
    think = Mock(side_effect=AssertionError("pause must not force learning"))
    act = Mock(side_effect=AssertionError("pause must not execute work"))
    monkeypatch.setattr(agent, "think", think)
    monkeypatch.setattr(agent, "act", act)
    before = len(agent.mental_models.concepts)
    report = agent.autonomous_tick()
    think.assert_not_called()
    act.assert_not_called()
    assert "autonomous_action" not in report
    assert len(agent.mental_models.concepts) == before


def test_real_curiosity_still_proposes_its_own_activity():
    agent = DigitalBeing(name="CuriosityNotSuppressed")
    system = agent.motivation_system
    for need in system.needs.values():
        need.current_level = need.base_level
    for drive in system.drives.values():
        drive.current_level = 0
    system.needs["curiosity"].current_level = 0
    candidates = system.get_action_candidates({})
    assert any(candidate.get("need") == "curiosity" and candidate["action"] != "wait" for candidate in candidates)
