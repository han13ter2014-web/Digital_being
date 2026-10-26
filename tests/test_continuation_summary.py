"""Повтор без новых условий не выдаётся за новое устойчивое намерение."""

from tools.manual.continuation_summary import summarize


def test_summary_counts_pending_repeats_by_topic_action_and_context():
    def trace(context, status="pending"):
        return {"target": "память", "entry": {"action": "explore",
                "evidence_goal": {"status": status, "information_context": context}}}

    result = summarize({"seed": 1, "cycles": 10,
                        "continuation_traces": [trace("a"), trace("a"), trace("b"), trace("b", "satisfied")],
                        "continuation_offers": {"память": 7}, "continuation_choices": {"память": 4},
                        "productive_actions": 4, "productive_effects": 3, "restart": {"memory_identical": True}})
    assert result["choices"] == 4
    assert result["pending_repeats_same_context"] == 1
    assert result["goal_statuses"] == {"pending": 3, "satisfied": 1}
