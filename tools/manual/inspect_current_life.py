"""Краткая read-only сводка развития активной сущности по чекпоинтам."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def number(value, default=0):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def compact(value):
    if isinstance(value, dict):
        return {"keys": list(value)[:25], "count": len(value)}
    if isinstance(value, list):
        return {"count": len(value)}
    if isinstance(value, str):
        return value[:240]
    return value


def summarize(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    result = {
        "cycle": data.get("cycle_count"),
        "energy": data.get("energy"),
        "completed_goals": data.get("completed_goals"),
        "success_streak": data.get("success_streak"),
        "active_goal": compact(data.get("active_goal")),
    }
    goals = data.get("goals")
    if isinstance(goals, list):
        statuses = {}
        for goal in goals:
            if isinstance(goal, dict):
                status = str(goal.get("status") or "unknown")
                statuses[status] = statuses.get(status, 0) + 1
        result["goals"] = {
            "statuses": statuses,
            "completed_titles": [g.get("title") for g in goals
                                 if isinstance(g, dict) and g.get("status") == "completed"],
        }
    emotions = data.get("emotional_state")
    if isinstance(emotions, dict):
        result["emotions"] = {
            "levels": emotions.get("levels"),
            "episodes": len(emotions.get("episodes") or []),
            "last": (emotions.get("episodes") or [])[-3:],
        }
    intero = data.get("interoception")
    if isinstance(intero, dict):
        result["body"] = {key: intero.get(key) for key in (
            "glucose", "atp", "mitochondrial_health", "fatigue"
        )}
    for key, value in data.items():
        lowered = key.lower()
        if any(token in lowered for token in (
            "value", "will", "creative", "art_", "music", "personality",
            "integrated", "intention_history", "mortality",
        )):
            result[key] = value if key == "birth_values" else compact(value)
    return result


def main():
    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    folder = DATA / "checkpoints" / profile["life_id"]
    checkpoints = sorted(
        folder.glob("*_cycle_*.json"),
        key=lambda path: int(path.stem.rsplit("_", 1)[1]),
    )
    selected = [checkpoints[0], checkpoints[len(checkpoints) // 2], checkpoints[-1]]
    print(json.dumps({
        "profile": profile,
        "checkpoint_count": len(checkpoints),
        "snapshots": {path.name: summarize(path) for path in selected},
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
