"""Small command-line demo for the Delamain-local core.

Examples (from the project root)::

    python -m src.delamain --root workspace --task "список файлов"
    python -m src.delamain --root workspace --task "запиши в notes/a.txt: привет"
    python -m src.delamain --root workspace --task "проверь notes/a.txt на привет"
    python -m src.delamain --root workspace --task demo --plan-file plan.json

The CLI is intentionally model-free. It is useful for smoke tests, manual
inspection of the memory database and for demonstrating the loop offline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .runtime import DelamainRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.delamain",
        description="Run one task through the local Delamain action/memory loop.",
    )
    parser.add_argument(
        "--root",
        default="workspace",
        help="workspace directory for file actions (default: workspace)",
    )
    parser.add_argument(
        "--db",
        default=str(Path("data") / "delamain" / "delamain.sqlite3"),
        help="SQLite memory path (default: data/delamain/delamain.sqlite3)",
    )
    parser.add_argument("--task", required=True, help="task text to plan and run")
    plan_group = parser.add_mutually_exclusive_group()
    plan_group.add_argument(
        "--plan",
        default=None,
        help="optional JSON list of {action, args} steps; bypasses the planner",
    )
    plan_group.add_argument(
        "--plan-file",
        default=None,
        help="read the optional JSON plan from a UTF-8 file",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    plan = None
    raw_plan = args.plan
    if args.plan_file:
        try:
            raw_plan = Path(args.plan_file).read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(f"cannot read --plan-file: {exc}", file=sys.stderr)
            return 2
    if raw_plan:
        try:
            plan = json.loads(raw_plan)
        except json.JSONDecodeError as exc:
            print(f"invalid plan JSON: {exc}", file=sys.stderr)
            return 2

    with DelamainRuntime(args.root, args.db) as runtime:
        result = runtime.run_task(args.task, plan=plan)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
