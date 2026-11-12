"""Read-only диагностика активной цели и очереди последнего чекпоинта."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def main():
    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    folder = DATA / "checkpoints" / profile["life_id"]
    checkpoints = sorted(
        folder.glob("*_cycle_*.json"),
        key=lambda path: int(path.stem.rsplit("_", 1)[1]),
    )
    path = checkpoints[-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    active_title = data.get("active_goal")
    goals = data.get("goals") or []
    active = next((g for g in goals if g.get("title") == active_title), None)
    active_id = active.get("id") if active else None
    progress = data.get("_goal_progress") or {}
    result = {
        "checkpoint": path.name,
        "cycle": data.get("cycle_count"),
        "active_goal": active,
        "active_progress": progress.get(str(active_id), progress.get(active_id)),
        "recent_pending": [g for g in goals if g.get("status") == "pending"][-20:],
        "top_level_keys": sorted(data),
    }
    for key, value in data.items():
        if any(token in key.lower() for token in ("motivation", "intention", "waiting")):
            if isinstance(value, list):
                result[key] = {"count": len(value), "last": value[-8:]}
            elif isinstance(value, dict):
                result[key] = value
            else:
                result[key] = value
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
