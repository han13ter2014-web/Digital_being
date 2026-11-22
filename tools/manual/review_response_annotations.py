"""Открыть ручную разметку ответов только для явной sandbox-копии."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.response_annotation import AnnotationError  # noqa: E402
from src.core.response_annotation_review import (  # noqa: E402
    ReviewError,
    open_review_session,
)
from src.ui.annotation_review_window import run_annotation_review  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox-root", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--response-journal", required=True)
    parser.add_argument("--annotation-journal", required=True)
    parser.add_argument("--life-id", required=True)
    parser.add_argument("--annotator-id", default="owner")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        session = open_review_session(
            sandbox_root=args.sandbox_root,
            snapshot_path=args.snapshot,
            response_journal_path=args.response_journal,
            annotation_journal_path=args.annotation_journal,
            life_id=args.life_id,
            annotator_id=args.annotator_id,
        )
    except (ReviewError, AnnotationError, ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"Разметка не открыта: {error}\n")
    print(
        json.dumps(
            {
                "mode": "sandbox_only",
                "candidates": len(session.candidates),
                "live_runtime_connected": False,
                "training_started": False,
            },
            ensure_ascii=False,
        )
    )
    run_annotation_review(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
