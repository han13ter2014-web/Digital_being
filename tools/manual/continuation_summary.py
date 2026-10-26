"""Сводка JSON-замеров возвратов, включая повторы без новых условий.

python tools/manual/continuation_summary.py REPORT [REPORT ...]
"""

import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(data):
    contexts = Counter()
    statuses = Counter()
    for trace in data["continuation_traces"]:
        entry = trace.get("entry") or {}
        goal = entry.get("evidence_goal") or {}
        statuses[goal.get("status", "missing")] += 1
        if goal.get("status") == "pending":
            contexts[(trace["target"], entry.get("action"), goal.get("information_context"))] += 1
    return {"seed": data["seed"], "cycles": data["cycles"],
            "offers": sum(data["continuation_offers"].values()),
            "choices": sum(data["continuation_choices"].values()),
            "goal_statuses": dict(statuses),
            "pending_repeats_same_context": sum(max(0, count - 1) for count in contexts.values()),
            "productive_actions": data["productive_actions"],
            "productive_effects": data["productive_effects"],
            "restart": data["restart"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    for report in args.reports:
        result = summarize(json.loads(report.read_text(encoding="utf-8")))
        print(json.dumps({"report": report.name, **result}, ensure_ascii=True))
