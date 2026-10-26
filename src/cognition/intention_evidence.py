"""Узкий результат исследования: новое свидетельство, не регистрация темы."""

from src.cognition.mental_models import EVIDENCE_MIN
from src.memory.knowledge_quality import normalize_concept_name


def evidence_sources(agent, target):
    key = normalize_concept_name(target) or target
    node = agent.mental_models.concepts.get(key)
    sources = set()
    if node is None:
        return []
    for experience in node.experiences:
        if experience.get("evidence_kind") not in {"observation", "testimony"}:
            continue
        strength = experience.get("evidence_strength", 0.0)
        source = experience.get("source")
        text = experience.get("outcome")
        if (isinstance(strength, (int, float)) and EVIDENCE_MIN <= strength <= 1
                and isinstance(source, str) and source.strip()
                and isinstance(text, str) and len(text.strip()) > 10):
            sources.add(source)
    return sorted(sources)


def begin_evidence_goal(agent, entry):
    if agent._normalize_action(entry["action"]) == "explore" and entry.get("target"):
        from src.cognition.method_feedback import information_context

        entry["evidence_goal"] = {"kind": "new_topic_evidence",
                                  "information_context": information_context(agent),
                                  "baseline_sources": evidence_sources(agent, entry["target"]),
                                  "status": "pending", "new_sources": []}


def finish_evidence_goal(agent, entry):
    goal = entry.get("evidence_goal")
    if goal is None or entry["status"] not in {"performed", "unobserved"}:
        return
    current = set(evidence_sources(agent, entry["target"]))
    new = sorted(current - set(goal["baseline_sources"]))
    goal["new_sources"] = new
    goal["status"] = "satisfied" if new else "pending"
