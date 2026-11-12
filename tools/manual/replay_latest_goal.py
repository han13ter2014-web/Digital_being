"""Прогон копии последнего чекпоинта в одноразовом изолированном data-каталоге."""

import argparse
from collections import Counter
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"


def latest_checkpoint():
    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    folder = DATA / "checkpoints" / profile["life_id"]
    paths = sorted(
        folder.glob("*_cycle_*.json"),
        key=lambda path: int(path.stem.rsplit("_", 1)[1]),
    )
    if not paths:
        raise RuntimeError("Чекпоинты активной жизни не найдены")
    return profile, paths[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=80)
    args = parser.parse_args()
    if args.cycles < 1:
        raise ValueError("--cycles должен быть положительным")
    profile, source = latest_checkpoint()
    temp_root = ROOT / "tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="goal_replay_", dir=temp_root) as isolated:
        os.environ["DIGITAL_BEING_DATA_DIR"] = isolated
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        os.environ["VOICE_CONSOLE_QUIET"] = "1"
        for name in ("DIGITAL_BEING_TELEGRAM_TOKEN", "DIGITAL_BEING_TELEGRAM_CHAT_ID",
                     "DIGITAL_BEING_DISCORD_WEBHOOK_URL"):
            os.environ.pop(name, None)

        from src.core.agent import DigitalBeing
        from src.core.checkpoint_serializer import CheckpointSerializer, apply_state_to_agent

        copied = Path(isolated) / "checkpoint_copy.json"
        copied.write_bytes(source.read_bytes())
        state = CheckpointSerializer().load(str(copied))
        agent = DigitalBeing("GoalReplay", profile_managed=True)
        apply_state_to_agent(agent, state)
        searcher = getattr(agent, "web_searcher", None)
        if searcher is not None:
            searcher.toggle(False)

        initial_goal = dict(agent.active_goal or {})
        initial_id = initial_goal.get("id")
        initial_progress = dict(agent._goal_progress.get(initial_id, {}))
        initial_progress["matched_concepts"] = set(
            initial_progress.get("matched_concepts") or []
        )
        selected = []
        actions = Counter()
        errors = []
        log_path = Path(isolated) / "replay.log"
        with log_path.open("w", encoding="utf-8") as log, redirect_stdout(log):
            for _ in range(args.cycles):
                agent.cycle_count += 1
                try:
                    report = agent.autonomous_tick()
                except Exception as exc:
                    errors.append({"cycle": agent.cycle_count, "error": str(exc)})
                    continue
                executed = report.get("executed_intention") or {}
                action = executed.get("action")
                if action:
                    actions[action] += 1
                if executed.get("source") == "active_goal":
                    selected.append({
                        "cycle": agent.cycle_count,
                        "action": action,
                        "target": (executed.get("params") or {}).get("concept"),
                        "outcome": (report.get("autonomous_action") or {}).get("result"),
                    })

        current_progress = dict(agent._goal_progress.get(initial_id, {}))
        result = {
            "source_checkpoint": source.name,
            "source_cycle": state.get("cycle_count"),
            "cycles_replayed": args.cycles,
            "initial_goal": initial_goal.get("title"),
            "initial_progress": initial_progress,
            "final_progress": current_progress,
            "active_goal_after": (agent.active_goal or {}).get("title"),
            "active_goal_selections": selected,
            "selected_action_counts": dict(actions),
            "duplicates_skipped": [
                {"id": goal.get("id"), "title": goal.get("title"),
                 "duplicate_of": goal.get("duplicate_of")}
                for goal in agent.goals if goal.get("status") == "duplicate"
            ],
            "pending_goals_after": sum(g.get("status") == "pending" for g in agent.goals),
            "errors": errors,
            "isolated_data_removed_on_exit": True,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
