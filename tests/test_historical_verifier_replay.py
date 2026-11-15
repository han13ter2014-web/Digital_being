"""T2b: honest and corrupted replays of all historical K14 verifiers."""

import ast
import hashlib
import subprocess
import uuid
from pathlib import Path

import pytest

from tools.manual.replay_historical_verifiers import (
    MANIFEST,
    ROOT,
    discover_evidence,
    replay,
)


def _git(*args):
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def test_manifest_pins_and_corruption_targets_match_history():
    assert len(MANIFEST) == 16
    assert len({row["verifier"] for row in MANIFEST}) == 16
    assert len({(row["parent"], row["step"]) for row in MANIFEST}) == 15

    for row in MANIFEST:
        actual_parent = _git("rev-parse", f"{row['step']}^")
        assert actual_parent.startswith(row["parent"])
        module_source = _git("show", f"{row['step']}:{row['module']}")
        functions = {
            node.name
            for node in ast.parse(module_source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert row["function"] in functions


def test_replay_output_cannot_escape_repository_tmp(tmp_path):
    outside = Path(tmp_path) / "outside"
    with pytest.raises(ValueError, match="inside the repository tmp"):
        replay(evidence=ROOT, output=outside)


def test_all_historical_verifiers_pass_and_catch_corruption():
    evidence = discover_evidence()
    if evidence is None:
        pytest.skip("no complete historical verifier evidence in this checkout")
    before = {
        row["verifier"]: hashlib.sha256(
            (evidence / row["verifier"]).read_bytes()
        ).hexdigest()
        for row in MANIFEST
    }
    output = ROOT / "tmp" / f"t2b_test_{uuid.uuid4().hex[:10]}"

    report = replay(output=output)

    failed = [row for row in report["rows"] if not row["ok"]]
    assert report["ok"], {"error": report.get("error"), "failed": failed}
    assert report["summary"] == {
        "selected": 16,
        "completed": 16,
        "honest_passed": 16,
        "corruption_caught": 16,
    }
    after = {
        row["verifier"]: hashlib.sha256(
            (evidence / row["verifier"]).read_bytes()
        ).hexdigest()
        for row in MANIFEST
    }
    assert after == before


def test_creation_replay_is_deterministic_across_fresh_processes():
    if discover_evidence() is None:
        pytest.skip("no complete historical verifier evidence in this checkout")

    reports = []
    for _ in range(2):
        output = ROOT / "tmp" / f"t2b_creation_{uuid.uuid4().hex[:10]}"
        reports.append(
            replay(
                output=output,
                only={"verify_creation_move.py"},
                corruption=False,
            )
        )

    assert all(report["ok"] for report in reports), [
        {"error": report.get("error"), "rows": report["rows"]} for report in reports
    ]
