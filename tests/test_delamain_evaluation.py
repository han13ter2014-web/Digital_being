"""Tests for the Stage 17 capability evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.delamain.evaluation import (
    EvaluationError,
    load_suite,
    main,
    run_suite,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_SUITE = PROJECT_ROOT / "evals" / "delamain_stage17.json"


def _write_suite(
    tmp_path: Path,
    cases: list[dict],
    *,
    name: str = "tiny-suite",
) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "name": name,
                "version": 1,
                "description": "inline test suite",
                "cases": cases,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _execution_case(
    *,
    case_id: str = "write-basic",
    category: str = "basic",
    workspace: dict | None = None,
    plan: list[dict] | None = None,
    expect: dict | None = None,
    **extra,
) -> dict:
    case = {
        "id": case_id,
        "kind": "execution",
        "category": category,
        "workspace": workspace or {},
        "steps": [
            {
                "goal": case_id,
                "plan": plan
                or [
                    {
                        "action": "write_file",
                        "args": {"path": "out.txt", "content": "ok"},
                    }
                ],
                "expect": expect
                or {
                    "ok": True,
                    "goal_status": "done",
                    "files": {"out.txt": "ok"},
                },
            }
        ],
    }
    case.update(extra)
    return case


def _planning_case(
    *,
    case_id: str = "planning-write",
    task: str = "write notes/a.txt: hello",
    expect_plan: list[dict] | None = None,
) -> dict:
    return {
        "id": case_id,
        "kind": "planning",
        "category": "planning",
        "task": task,
        "expect_plan": expect_plan
        or [
            {
                "action": "write_file",
                "args": {"path": "notes/a.txt", "content": "hello"},
            }
        ],
    }


def _run_one(case: dict, tmp_path: Path, **suite_kwargs):
    suite_path = _write_suite(tmp_path, [case])
    suite = load_suite(suite_path)
    return suite, run_suite(suite, work_root=tmp_path / "artifacts", **suite_kwargs)


# ---------------------------------------------------------------------------
# Loader and validation
# ---------------------------------------------------------------------------


def test_shipped_suite_is_valid_and_passes() -> None:
    suite = load_suite(SHIPPED_SUITE)
    assert suite.name == "delamain-stage17"
    assert len(suite.cases) == 18

    result = run_suite(suite)
    assert result.cases_total == 18
    assert result.cases_passed == 18
    assert result.cases_failed == 0
    assert result.pass_rate == 1.0
    assert result.work_root is None


def test_loader_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(EvaluationError, match="invalid suite JSON"):
        load_suite(path)


def test_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    case = _planning_case()
    path = _write_suite(tmp_path, [case, dict(case)])
    with pytest.raises(EvaluationError, match="duplicate case id"):
        load_suite(path)


def test_loader_rejects_unknown_expectation_key(tmp_path: Path) -> None:
    case = _execution_case(expect={"ok": True, "typoo": True})
    path = _write_suite(tmp_path, [case])
    with pytest.raises(EvaluationError, match="unknown keys"):
        load_suite(path)


def test_loader_rejects_unknown_case_key(tmp_path: Path) -> None:
    case = _execution_case()
    case["workspaces"] = {}
    path = _write_suite(tmp_path, [case])
    with pytest.raises(EvaluationError, match="unknown keys"):
        load_suite(path)


def test_loader_rejects_unknown_step_key(tmp_path: Path) -> None:
    case = _execution_case()
    case["steps"][0]["planner"] = "heuristic"
    path = _write_suite(tmp_path, [case])
    with pytest.raises(EvaluationError, match="unknown keys"):
        load_suite(path)


def test_loader_rejects_unknown_suite_key(tmp_path: Path) -> None:
    path = _write_suite(tmp_path, [_execution_case()])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["case"] = payload.pop("cases")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EvaluationError, match="unknown keys"):
        load_suite(path)


def test_loader_rejects_parent_escape_in_workspace(tmp_path: Path) -> None:
    case = _execution_case(workspace={"../escape.txt": "no"})
    path = _write_suite(tmp_path, [case])
    with pytest.raises(EvaluationError, match="must not contain"):
        load_suite(path)


def test_loader_rejects_unknown_approval_mode(tmp_path: Path) -> None:
    case = _execution_case(approval_mode="sometimes")
    path = _write_suite(tmp_path, [case])
    with pytest.raises(EvaluationError, match="approval_mode"):
        load_suite(path)


# ---------------------------------------------------------------------------
# Execution, assertions and isolation
# ---------------------------------------------------------------------------


def test_basic_execution_case_passes(tmp_path: Path) -> None:
    suite, result = _run_one(_execution_case(), tmp_path)
    assert suite.name == "tiny-suite"
    assert result.cases_passed == 1
    case = result.results[0]
    assert case.ok
    assert case.runs[0]["ok"] is True
    assert case.runs[0]["goal_status"] == "done"
    assert case.runs[0]["effective_steps"] == 1
    workspace = Path(result.work_root) / "00-write-basic" / "workspace"
    assert (workspace / "out.txt").read_text(encoding="utf-8") == "ok"


def test_mismatched_expectation_fails_case(tmp_path: Path) -> None:
    case = _execution_case(
        expect={
            "ok": True,
            "files": {"out.txt": "different"},
        }
    )
    _, result = _run_one(case, tmp_path)
    assert result.cases_failed == 1
    assert not result.results[0].ok
    failed = [check for check in result.results[0].checks if not check["ok"]]
    assert any("file content" in check["name"] for check in failed)


def test_expected_runtime_failure_is_a_passing_case(tmp_path: Path) -> None:
    case = _execution_case(
        plan=[
            {
                "action": "read_file",
                "args": {"path": "missing.txt"},
            }
        ],
        expect={
            "ok": False,
            "goal_status": "failed",
            "files": {"missing.txt": None},
        },
    )
    _, result = _run_one(case, tmp_path)
    assert result.pass_rate == 1.0
    run = result.results[0].runs[0]
    assert run["ok"] is False
    assert run["goal_status"] == "failed"


def test_cases_get_isolated_workspaces(tmp_path: Path) -> None:
    first = _execution_case(case_id="first")
    second = _execution_case(case_id="second")
    suite_path = _write_suite(tmp_path, [first, second])
    result = run_suite(
        load_suite(suite_path),
        work_root=tmp_path / "artifacts",
    )
    assert result.cases_passed == 2
    first_dir = Path(result.work_root) / "00-first" / "workspace"
    second_dir = Path(result.work_root) / "01-second" / "workspace"
    assert first_dir != second_dir
    assert (first_dir / "out.txt").read_text(encoding="utf-8") == "ok"
    assert (second_dir / "out.txt").read_text(encoding="utf-8") == "ok"


def test_case_filter_selects_requested_cases(tmp_path: Path) -> None:
    suite_path = _write_suite(
        tmp_path,
        [_execution_case(case_id="first"), _execution_case(case_id="second")],
    )
    result = run_suite(
        load_suite(suite_path),
        work_root=tmp_path / "artifacts",
        case_ids=["second"],
    )
    assert result.cases_total == 1
    assert result.results[0].case_id == "second"


def test_case_filter_rejects_no_match(tmp_path: Path) -> None:
    suite_path = _write_suite(tmp_path, [_execution_case()])
    with pytest.raises(EvaluationError, match="no suite cases matched"):
        run_suite(load_suite(suite_path), case_ids=["missing"])


# ---------------------------------------------------------------------------
# Repair, approvals, safety and skill reuse from the shipped suite
# ---------------------------------------------------------------------------


def test_repair_replaces_only_the_failed_tail(tmp_path: Path) -> None:
    suite = load_suite(SHIPPED_SUITE)
    result = run_suite(
        suite,
        work_root=tmp_path,
        case_ids=["recovery-replace"],
    )
    assert result.cases_passed == 1
    run = result.results[0].runs[0]
    assert run["repair_count"] == 1
    assert run["replan_calls"] == 1
    assert [item["action"] for item in run["effective_actions"]] == [
        "write_file",
        "write_file",
    ]
    assert [item["action"] for item in run["planned_actions"]] == [
        "write_file",
        "read_file",
        "write_file",
    ]
    workspace = Path(result.work_root) / "00-recovery-replace" / "workspace"
    assert (workspace / "recovery" / "tail.txt").exists() is False
    assert (workspace / "recovery" / "fixed.txt").read_text(
        encoding="utf-8"
    ) == "fixed"


def test_dangerous_repair_waits_for_approval(tmp_path: Path) -> None:
    suite = load_suite(SHIPPED_SUITE)
    result = run_suite(
        suite,
        work_root=tmp_path,
        case_ids=["recovery-approval"],
    )
    assert result.cases_passed == 1
    run = result.results[0].runs[0]
    assert run["pending"] is True
    assert run["resolution"] == "approved"
    assert run["approval_status"] == "consumed"
    assert run["goal_status"] == "done"
    workspace = Path(result.work_root) / "00-recovery-approval" / "workspace"
    assert (workspace / "approval" / "fixed.txt").read_text(
        encoding="utf-8"
    ) == "fixed"


def test_rejected_repair_does_not_execute_and_keeps_completed_work(
    tmp_path: Path,
) -> None:
    suite = load_suite(SHIPPED_SUITE)
    result = run_suite(
        suite,
        work_root=tmp_path,
        case_ids=["repair-reject"],
    )
    assert result.cases_passed == 1
    run = result.results[0].runs[0]
    assert run["ok"] is False
    assert run["resolution"] == "rejected"
    assert run["approval_status"] == "rejected"
    assert run["goal_status"] == "failed"
    assert [item["action"] for item in run["effective_actions"]] == [
        "verify_file"
    ]
    workspace = Path(result.work_root) / "00-repair-reject" / "workspace"
    assert (workspace / "approval" / "rejected.txt").exists() is False


def test_safety_reject_leaves_no_file(tmp_path: Path) -> None:
    suite = load_suite(SHIPPED_SUITE)
    result = run_suite(
        suite,
        work_root=tmp_path,
        case_ids=["safety-reject"],
    )
    assert result.cases_passed == 1
    workspace = Path(result.work_root) / "00-safety-reject" / "workspace"
    assert (workspace / "safety" / "rejected.txt").exists() is False


def test_sandbox_escape_is_blocked(tmp_path: Path) -> None:
    suite = load_suite(SHIPPED_SUITE)
    result = run_suite(
        suite,
        work_root=tmp_path,
        case_ids=["safety-sandbox-escape"],
    )
    assert result.cases_passed == 1
    run = result.results[0].runs[0]
    assert run["ok"] is False
    case_root = Path(result.work_root) / "00-safety-sandbox-escape"
    assert (case_root / "escape.txt").exists() is False


def test_exact_skill_reuse_skips_the_planner(tmp_path: Path) -> None:
    suite = load_suite(SHIPPED_SUITE)
    result = run_suite(
        suite,
        work_root=tmp_path,
        case_ids=["skill-reuse-exact"],
    )
    assert result.cases_passed == 1
    first, second = result.results[0].runs
    assert first["reused_skill"] is False
    assert first["plan_calls"] == 1
    assert first["skill_successes"] == 1
    assert second["reused_skill"] is True
    assert second["plan_calls"] == 0
    assert second["skill_successes"] == 2
    assert second["skill_failures"] == 0


# ---------------------------------------------------------------------------
# Planning probes and metrics
# ---------------------------------------------------------------------------


def test_planning_probe_passes_for_supported_command() -> None:
    suite = load_suite(SHIPPED_SUITE)
    result = run_suite(suite, case_ids=["planning-write-en"])
    assert result.cases_passed == 1
    case = result.results[0]
    assert case.kind == "planning"
    assert case.details["actual_plan"] == case.details["expected_plan"]


def test_planning_probe_catches_unsupported_phrasing(tmp_path: Path) -> None:
    case = _planning_case(
        task="please write notes/a.txt: hello",
    )
    _, result = _run_one(case, tmp_path)
    assert result.cases_failed == 1
    assert result.results[0].details["actual_plan"] is None
    assert result.results[0].error is not None


def test_metrics_separate_actual_and_expected_success() -> None:
    suite = load_suite(SHIPPED_SUITE)
    result = run_suite(suite)
    metrics = result.metrics
    assert metrics["runtime_runs"] == 12
    assert metrics["runtime_successes"] == 9
    assert metrics["expected_success_runs"] == 9
    assert metrics["expected_failure_runs"] == 3
    assert metrics["expected_success_rate"] == 1.0
    assert metrics["recovery_rate"] == 1.0
    assert metrics["long_horizon_rate"] == 1.0
    assert metrics["skill_reuse_rate"] == 1.0
    assert metrics["safety_rate"] == 1.0
    assert metrics["planning_accuracy"] == 1.0
    assert metrics["repair_runs"] == 3
    assert metrics["approvals_pending"] == 4
    assert metrics["approvals_approved"] == 2
    assert metrics["approvals_rejected"] == 2


def test_category_breakdown_is_reported() -> None:
    result = run_suite(load_suite(SHIPPED_SUITE))
    categories = result.metrics["categories"]
    assert categories["basic"]["cases"] == 3
    assert categories["recovery"]["passed"] == 3
    assert categories["safety"]["pass_rate"] == 1.0
    assert categories["planning"]["cases"] == 7


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_json_report(tmp_path: Path, capsys) -> None:
    suite_path = _write_suite(
        tmp_path,
        [_execution_case()],
        name="cli-suite",
    )
    report_path = tmp_path / "report.json"
    code = main(
        [
            "--suite",
            str(suite_path),
            "--json",
            "--report",
            str(report_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["cases_passed"] == 1
    assert output["pass_rate"] == 1.0
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["name"] == "cli-suite"
    assert saved["results"][0]["case_id"] == "write-basic"


def test_cli_fails_below_threshold(tmp_path: Path, capsys) -> None:
    case = _execution_case(
        expect={
            "ok": True,
            "files": {"out.txt": "wrong"},
        }
    )
    suite_path = _write_suite(tmp_path, [case])
    code = main(["--suite", str(suite_path), "--json"])
    capsys.readouterr()
    assert code == 1


def test_cli_can_allow_partial_success(tmp_path: Path, capsys) -> None:
    case = _execution_case(
        expect={
            "ok": True,
            "files": {"out.txt": "wrong"},
        }
    )
    suite_path = _write_suite(tmp_path, [case])
    code = main(
        [
            "--suite",
            str(suite_path),
            "--json",
            "--fail-under",
            "0.0",
        ]
    )
    capsys.readouterr()
    assert code == 0


def test_cli_reports_missing_suite(tmp_path: Path, capsys) -> None:
    code = main(["--suite", str(tmp_path / "missing.json")])
    assert code == 2
    assert "evaluation error" in capsys.readouterr().err.lower()
