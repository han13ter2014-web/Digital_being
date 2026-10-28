"""Угасание — рекомендация на основании опыта, не скрытый таймер."""

from src.core.agent import DigitalBeing
from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_fading import fading_assessment


def attempt(agent):
    entry = begin_intention(agent, {"action": "explore", "params": {"topic": "память"}})
    finish_intention(entry)
    finish_evidence_goal(agent, entry)
    agent.cycle_count += 1
    return entry


def test_one_or_two_failed_attempts_do_not_auto_fade():
    agent = DigitalBeing(name="FadeNotYet")
    first = attempt(agent)
    assert not fading_assessment(agent, first)["eligible"]
    second = attempt(agent)
    assert not fading_assessment(agent, second)["eligible"]
    assert len(agent._intention_history) == 2
    assert not agent._intention_history[-1].get("resolution")


def test_repeated_pending_attempts_recommend_explicit_forgotten():
    agent = DigitalBeing(name="FadeRecommendation")
    entries = [attempt(agent) for _ in range(3)]
    result = fading_assessment(agent, entries[-1])
    assert result["eligible"]
    assert result["suggested_resolution"] == "forgotten"
    assert result["attempts"] == 3
    assert not entries[-1].get("resolution")


def test_new_evidence_blocks_fading_recommendation():
    agent = DigitalBeing(name="FadeEvidence")
    entries = [attempt(agent) for _ in range(3)]
    agent.mental_models.encounter_concept("память", "source", "Память сохраняет опыт",
                                         evidence_strength=0.8, evidence_kind="testimony", source="new:1")
    finish_evidence_goal(agent, entries[-1])
    assert fading_assessment(agent, entries[-1])["reason"] == "satisfied"


def test_resolved_intention_is_not_fade_candidate():
    agent = DigitalBeing(name="FadeResolved")
    entry = attempt(agent)
    entry["resolution"] = {"kind": "cancelled", "reason": "оставил", "cycle": agent.cycle_count}
    assert fading_assessment(agent, entry)["reason"] == "resolved"
