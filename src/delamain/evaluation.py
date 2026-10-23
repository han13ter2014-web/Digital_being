"""Deterministic capability evaluation for Delamain-local.

This module is a measuring instrument, not an intelligence test.  It runs a
data-only suite of cases in isolated workspaces and reports what the existing
agent loop actually did: task success, recovery, long-horizon execution,
approval safety and exact skill reuse.

The suite is deliberately independent from the runtime.  Normal agent
operation never imports this module, and the evaluator does not add actions,
network access or execution rights.  A suite file is data; a case cannot
change the runtime configuration outside the fields validated here.

The harness is honest about its limits:

* execution cases use a scripted planner, so they measure the runtime and
  memory loop, not language understanding;
* planning probes exercise the deterministic heuristic planner and show its
  current coverage, which is intentionally narrow;
* a high score on this suite is not evidence of AGI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .approval import VALID_APPROVAL_MODES
from .models import ActionRequest
from .planner import HeuristicPlanner, PlannerError
from .subsystem import DelamainSubsystem


SUITE_VERSION = 1
CASE_KINDS = {"execution", "planning"}
RESOLUTIONS = {"approve", "reject"}
EXPECTED_RESOLUTIONS = {"approved", "rejected"}
EXPECT_KEYS = {
    "ok",
    "pending",
    "resolution",
    "approval_status",
    "goal_status",
    "files",
    "absent_files",
    "absent_outside",
    "effective_actions",
    "planned_actions",
    "history_actions",
    "repair_count",
    "min_steps",
    "max_steps",
    "effective_steps",
    "reused_skill",
    "skill_successes",
    "skill_failures",
    "skill_actions",
    "facts",
    "output_fields",
    "error_contains",
    "plan_calls",
    "replan_calls",
}
SUITE_KEYS = {"name", "version", "description", "cases"}
CASE_KEYS = {"id", "kind", "category", "description"}
EXECUTION_CASE_KEYS = CASE_KEYS | {
    "workspace",
    "approval_mode",
    "step_repair_enabled",
    "max_step_repairs",
    "max_repair_steps",
    "steps",
}
PLANNING_CASE_KEYS = CASE_KEYS | {"task", "planner", "expect_plan"}
STEP_KEYS = {
    "goal",
    "command",
    "plan",
    "planner_plan",
    "repair_plans",
    "resolve",
    "expect",
}


class EvaluationError(Exception):
    """Raised when a suite or an evaluation case is malformed."""


# ---------------------------------------------------------------------------
# Small validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{where} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, where: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationError(f"{where} must be an object")
    return dict(value)


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise EvaluationError(f"{where} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise EvaluationError(f"{where} must be an integer") from None
    if parsed < minimum:
        raise EvaluationError(f"{where} must be >= {minimum}")
    return parsed


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationError(f"{where} must be a boolean")
    return value


def _reject_unknown(
    value: Mapping[str, Any],
    allowed: set[str],
    where: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise EvaluationError(f"{where} has unknown keys: {', '.join(unknown)}")


def _action_dict(step: Any, where: str) -> Dict[str, Any]:
    """Normalize one data/API step to the runtime's JSON form."""

    if isinstance(step, ActionRequest):
        return step.to_dict()
    if isinstance(step, str):
        action = step.strip()
        if not action:
            raise EvaluationError(f"{where} contains an empty action name")
        return {"action": action, "args": {}}
    if isinstance(step, Mapping):
        action = step.get("action")
        if not isinstance(action, str) or not action.strip():
            raise EvaluationError(f"{where} has no non-empty 'action'")
        args = step.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, Mapping):
            raise EvaluationError(f"{where}.args must be an object")
        return {"action": action.strip(), "args": dict(args)}
    raise EvaluationError(f"{where} has unsupported step type {type(step).__name__}")


def _normalize_plan(plan: Any, where: str) -> List[Dict[str, Any]]:
    if not isinstance(plan, (list, tuple)):
        raise EvaluationError(f"{where} must be a list")
    return [
        _action_dict(step, f"{where}[{index}]")
        for index, step in enumerate(plan)
    ]


def _safe_relative(path: str, where: str) -> Path:
    """Return a relative path, rejecting absolute/parent escapes."""

    raw = Path(path)
    if raw.is_absolute() or raw.drive:
        raise EvaluationError(f"{where} must be workspace-relative: {path!r}")
    if any(part == ".." for part in raw.parts):
        raise EvaluationError(f"{where} must not contain '..': {path!r}")
    return raw


def _workspace_path(root: Path, path: str, where: str) -> Path:
    relative = _safe_relative(path, where)
    return root / relative


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return (cleaned or "case")[:80]


def _add_check(
    checks: List[Dict[str, Any]],
    name: str,
    ok: bool,
    detail: Any = None,
) -> None:
    entry: Dict[str, Any] = {"name": name, "ok": bool(ok)}
    if detail is not None:
        entry["detail"] = detail
    checks.append(entry)


def _rate(passed: int, total: int) -> float:
    return round((float(passed) / float(total)), 4) if total else 0.0


# ---------------------------------------------------------------------------
# Suite model and loader
# ---------------------------------------------------------------------------


@dataclass
class EvalSuite:
    """Validated, data-only evaluation suite."""

    name: str
    version: int
    cases: List[Dict[str, Any]]
    description: str = ""
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "source": self.source,
            "cases_total": len(self.cases),
        }


@dataclass
class CaseResult:
    """Outcome of one evaluation case."""

    case_id: str
    kind: str
    category: str
    ok: bool = True
    checks: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    runs: List[Dict[str, Any]] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def add_check(self, name: str, ok: bool, detail: Any = None) -> None:
        _add_check(self.checks, name, ok, detail)
        if not ok:
            self.ok = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "kind": self.kind,
            "category": self.category,
            "ok": bool(self.ok),
            "error": self.error,
            "checks": list(self.checks),
            "runs": list(self.runs),
            "details": dict(self.details),
            "elapsed_ms": round(float(self.elapsed_ms), 3),
        }


@dataclass
class SuiteResult:
    """Aggregate outcome of a suite run."""

    name: str
    version: int
    results: List[CaseResult]
    metrics: Dict[str, Any] = field(default_factory=dict)
    work_root: Optional[str] = None

    @property
    def cases_total(self) -> int:
        return len(self.results)

    @property
    def cases_passed(self) -> int:
        return sum(1 for result in self.results if result.ok)

    @property
    def cases_failed(self) -> int:
        return self.cases_total - self.cases_passed

    @property
    def pass_rate(self) -> float:
        return _rate(self.cases_passed, self.cases_total)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "work_root": self.work_root,
            "cases_total": self.cases_total,
            "cases_passed": self.cases_passed,
            "cases_failed": self.cases_failed,
            "pass_rate": self.pass_rate,
            "metrics": dict(self.metrics),
            "results": [result.to_dict() for result in self.results],
        }


def _validate_expect(value: Any, where: str) -> Dict[str, Any]:
    expect = _mapping(value, where)
    _reject_unknown(expect, EXPECT_KEYS, where)

    for key in ("ok", "pending", "reused_skill"):
        if key in expect:
            expect[key] = _boolean(expect[key], f"{where}.{key}")

    if "resolution" in expect:
        resolution = str(expect["resolution"])
        if resolution not in EXPECTED_RESOLUTIONS:
            raise EvaluationError(
                f"{where}.resolution must be one of "
                f"{sorted(EXPECTED_RESOLUTIONS)}"
            )
        expect["resolution"] = resolution

    for key in ("approval_status", "goal_status", "error_contains"):
        if key in expect:
            expect[key] = _text(expect[key], f"{where}.{key}")

    if "files" in expect:
        files = _mapping(expect["files"], f"{where}.files")
        normalized_files: Dict[str, Optional[str]] = {}
        for path, content in files.items():
            path_text = _text(str(path), f"{where}.files key")
            _safe_relative(path_text, f"{where}.files[{path_text!r}]")
            if content is None:
                normalized_files[path_text] = None
            elif isinstance(content, str):
                normalized_files[path_text] = content
            else:
                raise EvaluationError(
                    f"{where}.files[{path_text!r}] must be a string or null"
                )
        expect["files"] = normalized_files

    for key in ("absent_files", "absent_outside", "history_actions"):
        if key in expect:
            raw_items = expect[key]
            if not isinstance(raw_items, list):
                raise EvaluationError(f"{where}.{key} must be a list")
            items: List[str] = []
            for index, item in enumerate(raw_items):
                items.append(_text(item, f"{where}.{key}[{index}]"))
            expect[key] = items

    for key in ("effective_actions", "planned_actions", "skill_actions"):
        if key in expect:
            expect[key] = _normalize_plan(expect[key], f"{where}.{key}")

    for key in (
        "repair_count",
        "min_steps",
        "max_steps",
        "effective_steps",
        "skill_successes",
        "skill_failures",
        "plan_calls",
        "replan_calls",
    ):
        if key in expect:
            expect[key] = _integer(expect[key], f"{where}.{key}")

    if "facts" in expect:
        raw_facts = expect["facts"]
        if not isinstance(raw_facts, list):
            raise EvaluationError(f"{where}.facts must be a list")
        facts: List[Dict[str, str]] = []
        for index, item in enumerate(raw_facts):
            fact = _mapping(item, f"{where}.facts[{index}]")
            if "key" not in fact or "value" not in fact:
                raise EvaluationError(
                    f"{where}.facts[{index}] needs 'key' and 'value'"
                )
            facts.append(
                {
                    "key": _text(fact["key"], f"{where}.facts[{index}].key"),
                    "value": _text(fact["value"], f"{where}.facts[{index}].value"),
                }
            )
        expect["facts"] = facts

    if "output_fields" in expect:
        expect["output_fields"] = _mapping(
            expect["output_fields"], f"{where}.output_fields"
        )

    return expect


def _validate_step(raw: Any, where: str) -> Dict[str, Any]:
    step = _mapping(raw, where)
    _reject_unknown(step, STEP_KEYS, where)
    goal = _text(step.get("goal"), f"{where}.goal")
    command_value = step.get("command")
    command: Optional[str] = None
    if command_value is not None:
        command = _text(command_value, f"{where}.command")

    plan: Optional[List[Dict[str, Any]]] = None
    if "plan" in step:
        plan = _normalize_plan(step["plan"], f"{where}.plan")
        if not plan:
            raise EvaluationError(f"{where}.plan must not be empty")

    planner_plan: Optional[List[Dict[str, Any]]] = None
    if "planner_plan" in step:
        planner_plan = _normalize_plan(
            step["planner_plan"], f"{where}.planner_plan"
        )
        if not planner_plan:
            raise EvaluationError(f"{where}.planner_plan must not be empty")

    if not command and plan is None and planner_plan is None:
        raise EvaluationError(
            f"{where} needs at least one of command, plan or planner_plan"
        )

    repair_plans: List[List[Dict[str, Any]]] = []
    if "repair_plans" in step:
        raw_repairs = step["repair_plans"]
        if not isinstance(raw_repairs, list):
            raise EvaluationError(f"{where}.repair_plans must be a list")
        for index, repair in enumerate(raw_repairs):
            normalized = _normalize_plan(
                repair, f"{where}.repair_plans[{index}]"
            )
            if not normalized:
                raise EvaluationError(
                    f"{where}.repair_plans[{index}] must not be empty"
                )
            repair_plans.append(normalized)

    resolve: Optional[str] = None
    if "resolve" in step:
        resolve = str(step["resolve"])
        if resolve not in RESOLUTIONS:
            raise EvaluationError(
                f"{where}.resolve must be one of {sorted(RESOLUTIONS)}"
            )

    expect = _validate_expect(step.get("expect", {}), f"{where}.expect")
    return {
        "goal": goal,
        "command": command,
        "plan": plan,
        "planner_plan": planner_plan,
        "repair_plans": repair_plans,
        "resolve": resolve,
        "expect": expect,
    }


def _validate_case(raw: Any, where: str) -> Dict[str, Any]:
    case = _mapping(raw, where)
    kind = str(case.get("kind", "execution")).strip().lower()
    if kind not in CASE_KINDS:
        raise EvaluationError(
            f"{where}.kind must be one of {sorted(CASE_KINDS)}"
        )
    allowed_keys = (
        PLANNING_CASE_KEYS if kind == "planning" else EXECUTION_CASE_KEYS
    )
    _reject_unknown(case, allowed_keys, where)
    case_id = _text(case.get("id"), f"{where}.id")
    category = str(case.get("category") or kind).strip() or kind
    description = str(case.get("description") or "").strip()
    result: Dict[str, Any] = {
        "id": case_id,
        "kind": kind,
        "category": category,
        "description": description,
    }

    if kind == "planning":
        task = _text(case.get("task"), f"{where}.task")
        planner = str(case.get("planner") or "heuristic").strip().lower()
        if planner != "heuristic":
            raise EvaluationError(
                f"{where}.planner currently supports only 'heuristic'"
            )
        expected = _normalize_plan(
            case.get("expect_plan"), f"{where}.expect_plan"
        )
        if not expected:
            raise EvaluationError(f"{where}.expect_plan must not be empty")
        result.update(
            {
                "task": task,
                "planner": planner,
                "expect_plan": expected,
            }
        )
        return result

    approval_mode = str(case.get("approval_mode", "off")).strip().lower()
    if approval_mode not in VALID_APPROVAL_MODES:
        raise EvaluationError(
            f"{where}.approval_mode must be one of {list(VALID_APPROVAL_MODES)}"
        )
    step_repair_enabled = _boolean(
        case.get("step_repair_enabled", False),
        f"{where}.step_repair_enabled",
    )
    max_step_repairs = _integer(
        case.get("max_step_repairs", 1),
        f"{where}.max_step_repairs",
    )
    max_repair_steps = _integer(
        case.get("max_repair_steps", 5),
        f"{where}.max_repair_steps",
        minimum=1,
    )

    raw_workspace = case.get("workspace", {})
    workspace = _mapping(raw_workspace, f"{where}.workspace")
    normalized_workspace: Dict[str, Optional[str]] = {}
    for path, content in workspace.items():
        path_text = _text(str(path), f"{where}.workspace key")
        _safe_relative(path_text, f"{where}.workspace[{path_text!r}]")
        if content is None:
            normalized_workspace[path_text] = None
        elif isinstance(content, str):
            normalized_workspace[path_text] = content
        else:
            raise EvaluationError(
                f"{where}.workspace[{path_text!r}] must be a string or null"
            )

    raw_steps = case.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise EvaluationError(f"{where}.steps must be a non-empty list")
    steps = [
        _validate_step(step, f"{where}.steps[{index}]")
        for index, step in enumerate(raw_steps)
    ]

    result.update(
        {
            "workspace": normalized_workspace,
            "approval_mode": approval_mode,
            "step_repair_enabled": step_repair_enabled,
            "max_step_repairs": max_step_repairs,
            "max_repair_steps": max_repair_steps,
            "steps": steps,
        }
    )
    return result


def load_suite(path: str | Path) -> EvalSuite:
    """Load and validate a UTF-8 JSON suite."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise EvaluationError(f"cannot read suite {source}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"invalid suite JSON: {exc}") from exc

    root = _mapping(payload, "suite")
    _reject_unknown(root, SUITE_KEYS, "suite")
    name = _text(root.get("name"), "suite.name")
    version = _integer(root.get("version", SUITE_VERSION), "suite.version")
    if version != SUITE_VERSION:
        raise EvaluationError(
            f"unsupported suite version {version}; expected {SUITE_VERSION}"
        )
    description = str(root.get("description") or "").strip()
    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationError("suite.cases must be a non-empty list")

    cases: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        case = _validate_case(raw_case, f"suite.cases[{index}]")
        case_id = str(case["id"])
        if case_id in seen:
            raise EvaluationError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        cases.append(case)

    return EvalSuite(
        name=name,
        version=version,
        cases=cases,
        description=description,
        source=str(source),
    )


# ---------------------------------------------------------------------------
# Scripted planner
# ---------------------------------------------------------------------------


class ScriptedPlanner:
    """A deterministic planner used by execution cases.

    The suite supplies plans as data.  This keeps the evaluator independent
    from the heuristic parser for execution cases while still exercising the
    real runtime, memory, approval and repair paths.
    """

    def __init__(self, plans: Mapping[str, Sequence[Any]]) -> None:
        self.plans = {
            str(task): _normalize_plan(plan, f"plans[{task!r}]")
            for task, plan in plans.items()
        }
        self.plan_calls = 0
        self.replan_calls = 0
        self.contexts: List[Dict[str, Any]] = []
        self._repairs: List[List[Dict[str, Any]]] = []

    def set_repairs(self, repairs: Optional[Sequence[Any]]) -> None:
        self._repairs = [
            _normalize_plan(plan, f"repair_plans[{index}]")
            for index, plan in enumerate(repairs or [])
        ]

    def plan(self, task: str) -> List[Dict[str, Any]]:
        self.plan_calls += 1
        task = str(task)
        if task not in self.plans:
            raise PlannerError(f"no scripted plan for task: {task}")
        return [dict(step) for step in self.plans[task]]

    def replan(
        self,
        task: str,
        failure_context: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        self.replan_calls += 1
        self.contexts.append(dict(failure_context))
        if not self._repairs:
            raise PlannerError("no scripted repair plan left")
        return [dict(step) for step in self._repairs.pop(0)]

    def bind_registry(self, registry: Any) -> None:
        """Kept for API parity with model-backed planners."""


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def _seed_workspace(workspace: Path, files: Mapping[str, Optional[str]]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        target = _workspace_path(workspace, path, f"workspace[{path!r}]")
        if content is None:
            if target.exists() and target.is_file():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _case_dir(root: Path, index: int, case_id: str) -> Path:
    directory = root / f"{index:02d}-{_safe_component(case_id)}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def _action_episodes(
    history: Sequence[Mapping[str, Any]],
    registry: Any,
    *,
    only_ok: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for episode in history:
        action = str(episode.get("action") or "")
        if registry.get(action) is None:
            continue
        if only_ok is not None and bool(episode.get("ok")) != only_ok:
            continue
        args = episode.get("args") or {}
        actions.append(
            {
                "action": action,
                "args": dict(args) if isinstance(args, Mapping) else {},
            }
        )
    return actions


def _skill_steps(skill: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(skill, Mapping):
        return []
    plan = skill.get("plan")
    if not isinstance(plan, Mapping):
        return []
    steps = plan.get("steps")
    if not isinstance(steps, (list, tuple)):
        return []
    try:
        return _normalize_plan(steps, "skill.plan.steps")
    except EvaluationError:
        return []


def _goal_summary_from_tick(
    tick_result: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(tick_result, Mapping):
        return None
    events = tick_result.get("events")
    if not isinstance(events, (list, tuple)):
        return None
    for event in reversed(events):
        if not isinstance(event, Mapping):
            continue
        if event.get("name") != "delamain_goal":
            continue
        data = event.get("data")
        if isinstance(data, Mapping):
            return dict(data)
    return None


def _run_execution_case(
    case: Mapping[str, Any],
    root: Path,
    index: int,
) -> CaseResult:
    case_id = str(case["id"])
    category = str(case["category"])
    checks: List[Dict[str, Any]] = []
    runs: List[Dict[str, Any]] = []
    case_dir = _case_dir(root, index, case_id)
    workspace = case_dir / "workspace"
    _seed_workspace(workspace, case["workspace"])

    plans: Dict[str, Sequence[Any]] = {}
    for step in case["steps"]:
        planner_plan = step.get("planner_plan")
        if planner_plan is not None:
            task = step.get("command") or step["goal"]
            plans[str(task)] = planner_plan
    planner = ScriptedPlanner(plans)

    subsystem = DelamainSubsystem(
        agent_name="delamain-eval",
        workspace=workspace,
        db_path=case_dir / "memory.sqlite3",
        enabled=True,
        tick_interval=1,
        max_goals_per_tick=1,
        max_attempts=1,
        retry_backoff_sec=0.0,
        retry_backoff_max_sec=0.0,
        replan_on_failure=False,
        replan_with_context=False,
        step_repair_enabled=bool(case["step_repair_enabled"]),
        max_step_repairs=int(case["max_step_repairs"]),
        max_repair_steps=int(case["max_repair_steps"]),
        llm_enabled=False,
        approval_mode=str(case["approval_mode"]),
        bridge_enabled=False,
        goal_proposal_enabled=False,
    )
    try:
        runtime = subsystem._ensure_runtime()
        runtime.planner = planner
        bind_registry = getattr(planner, "bind_registry", None)
        if callable(bind_registry):
            bind_registry(runtime.registry)

        for run_index, run_spec in enumerate(case["steps"]):
            cycle = run_index + 1
            planner.set_repairs(run_spec["repair_plans"])
            plan_calls_before = planner.plan_calls
            replan_calls_before = planner.replan_calls

            queued = subsystem.queue_goal(
                run_spec["goal"],
                command=run_spec["command"],
                plan=run_spec["plan"],
            )
            goal_id = int(queued["id"])
            tick_result = subsystem.tick(cycle, {})
            summary = _goal_summary_from_tick(tick_result)
            if summary is None:
                raise EvaluationError(
                    f"tick returned no summary for {case_id}/{run_spec['goal']}"
                )

            pending_summary = (
                summary if summary.get("pending_approval") else None
            )
            resolution: Optional[str] = None
            resolve = run_spec.get("resolve")
            if resolve:
                pending = summary.get("pending_approval")
                if pending:
                    approval_id = str(pending.get("id") or "")
                    if resolve == "approve":
                        summary = subsystem.approve(approval_id)
                        resolution = "approved"
                    else:
                        summary = subsystem.reject(
                            approval_id,
                            "rejected by evaluation case",
                        )
                        resolution = "rejected"
                else:
                    checks.append(
                        {
                            "name": f"{run_spec['goal']}: resolve requested",
                            "ok": False,
                            "detail": "case asked to resolve but no approval was pending",
                        }
                    )

            goal = subsystem.get_goal(goal_id)
            goal_status = str(goal.get("status") or "missing") if goal else "missing"
            history = subsystem.runtime.history(
                task_id=f"goal-{goal_id}",
                limit=1000,
            )
            registry = subsystem.runtime.registry
            effective_actions = _action_episodes(
                history, registry, only_ok=True
            )
            planned_actions = _action_episodes(history, registry)
            history_actions = [str(item.get("action") or "") for item in history]
            skill = subsystem.runtime.memory.get_skill(run_spec["goal"])
            skill_steps = _skill_steps(skill)

            run_result: Dict[str, Any] = {
                "goal": run_spec["goal"],
                "command": run_spec["command"],
                "ok": bool(summary.get("ok")),
                "steps": int(summary.get("steps") or 0),
                "effective_steps": int(summary.get("effective_steps") or 0),
                "repair_count": int(summary.get("step_repairs") or 0),
                "reused_skill": bool(summary.get("reused_skill")),
                "expected_ok": run_spec["expect"].get("ok"),
                "approval_status": summary.get("approval_status"),
                "pending": pending_summary is not None,
                "resolution": resolution,
                "goal_status": goal_status,
                "history_actions": history_actions,
                "planned_actions": planned_actions,
                "effective_actions": effective_actions,
                "plan_calls": planner.plan_calls - plan_calls_before,
                "replan_calls": planner.replan_calls - replan_calls_before,
                "skill_successes": int((skill or {}).get("success_count") or 0),
                "skill_failures": int((skill or {}).get("failure_count") or 0),
                "skill_actions": list(skill_steps),
                "error": summary.get("error"),
            }
            runs.append(run_result)

            expect = run_spec["expect"]
            _check_expectations(
                checks,
                expect,
                summary=summary,
                pending_summary=pending_summary,
                resolution=resolution,
                goal_status=goal_status,
                history_actions=history_actions,
                planned_actions=planned_actions,
                effective_actions=effective_actions,
                workspace=workspace,
                case_dir=case_dir,
                skill=skill,
                skill_steps=skill_steps,
                memory=subsystem.runtime.memory,
                run_result=run_result,
                label=run_spec["goal"],
            )

        result = CaseResult(
            case_id=case_id,
            kind="execution",
            category=category,
            ok=all(check["ok"] for check in checks),
            checks=checks,
            runs=runs,
            details={"workspace": str(workspace)},
        )
        return result
    finally:
        subsystem.teardown()


def _check_expectations(
    checks: List[Dict[str, Any]],
    expect: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
    pending_summary: Optional[Mapping[str, Any]],
    resolution: Optional[str],
    goal_status: str,
    history_actions: Sequence[str],
    planned_actions: Sequence[Mapping[str, Any]],
    effective_actions: Sequence[Mapping[str, Any]],
    workspace: Path,
    case_dir: Path,
    skill: Optional[Mapping[str, Any]],
    skill_steps: Sequence[Mapping[str, Any]],
    memory: Any,
    run_result: Mapping[str, Any],
    label: str,
) -> None:
    def check(name: str, ok: bool, detail: Any = None) -> None:
        _add_check(checks, f"{label}: {name}", ok, detail)

    try:
        if "ok" in expect:
            check("ok", bool(summary.get("ok")) == bool(expect["ok"]), summary.get("ok"))
        if "pending" in expect:
            check(
                "pending approval",
                (pending_summary is not None) == bool(expect["pending"]),
                bool(pending_summary),
            )
        if "resolution" in expect:
            check("resolution", resolution == expect["resolution"], resolution)
        if "approval_status" in expect:
            check(
                "approval status",
                summary.get("approval_status") == expect["approval_status"],
                summary.get("approval_status"),
            )
        if "goal_status" in expect:
            check("goal status", goal_status == expect["goal_status"], goal_status)

        if "files" in expect:
            for path, content in expect["files"].items():
                target = _workspace_path(workspace, path, f"expect.files[{path!r}]")
                if content is None:
                    check(f"file absent: {path}", not target.exists())
                else:
                    actual = (
                        target.read_text(encoding="utf-8")
                        if target.exists() and target.is_file()
                        else None
                    )
                    check(f"file content: {path}", actual == content, actual)
        if "absent_files" in expect:
            for path in expect["absent_files"]:
                target = _workspace_path(
                    workspace, path, f"expect.absent_files[{path!r}]"
                )
                check(f"file absent: {path}", not target.exists())
        if "absent_outside" in expect:
            for path in expect["absent_outside"]:
                target = _workspace_path(
                    case_dir, path, f"expect.absent_outside[{path!r}]"
                )
                check(f"outside file absent: {path}", not target.exists())

        if "effective_actions" in expect:
            check(
                "effective actions",
                list(effective_actions) == list(expect["effective_actions"]),
                list(effective_actions),
            )
        if "planned_actions" in expect:
            check(
                "planned actions",
                list(planned_actions) == list(expect["planned_actions"]),
                list(planned_actions),
            )
        if "history_actions" in expect:
            check(
                "history actions",
                list(history_actions) == list(expect["history_actions"]),
                list(history_actions),
            )

        if "repair_count" in expect:
            check(
                "repair count",
                int(summary.get("step_repairs") or 0) == expect["repair_count"],
                summary.get("step_repairs"),
            )
        if "min_steps" in expect:
            check(
                "min steps",
                int(summary.get("steps") or 0) >= expect["min_steps"],
                summary.get("steps"),
            )
        if "max_steps" in expect:
            check(
                "max steps",
                int(summary.get("steps") or 0) <= expect["max_steps"],
                summary.get("steps"),
            )
        if "effective_steps" in expect:
            check(
                "effective steps",
                int(summary.get("effective_steps") or 0)
                == expect["effective_steps"],
                summary.get("effective_steps"),
            )
        if "reused_skill" in expect:
            check(
                "reused skill",
                bool(summary.get("reused_skill")) == bool(expect["reused_skill"]),
                summary.get("reused_skill"),
            )
        if "skill_successes" in expect:
            check(
                "skill successes",
                int((skill or {}).get("success_count") or 0)
                == expect["skill_successes"],
                (skill or {}).get("success_count"),
            )
        if "skill_failures" in expect:
            check(
                "skill failures",
                int((skill or {}).get("failure_count") or 0)
                == expect["skill_failures"],
                (skill or {}).get("failure_count"),
            )
        if "skill_actions" in expect:
            check(
                "skill actions",
                list(skill_steps) == list(expect["skill_actions"]),
                list(skill_steps),
            )
        if "facts" in expect:
            for fact in expect["facts"]:
                found = memory.recall_facts(fact["key"], limit=20)
                match = any(
                    str(item.get("key")) == fact["key"]
                    and str(item.get("value")) == fact["value"]
                    for item in found
                    if isinstance(item, Mapping)
                )
                check(
                    f"fact: {fact['key']}",
                    match,
                    [
                        {
                            "key": item.get("key"),
                            "value": item.get("value"),
                        }
                        for item in found
                        if isinstance(item, Mapping)
                    ],
                )
        if "output_fields" in expect:
            output = summary.get("final_output")
            if isinstance(output, str):
                try:
                    parsed_output = json.loads(output)
                except json.JSONDecodeError:
                    parsed_output = None
                if isinstance(parsed_output, Mapping):
                    output = parsed_output
            if not isinstance(output, Mapping):
                check("output fields", False, output)
            else:
                for key, expected_value in expect["output_fields"].items():
                    check(
                        f"output field: {key}",
                        output.get(key) == expected_value,
                        output.get(key),
                    )
        if "error_contains" in expect:
            error = str(summary.get("error") or "").lower()
            check(
                "error contains",
                str(expect["error_contains"]).lower() in error,
                summary.get("error"),
            )
        if "plan_calls" in expect:
            check(
                "planner calls",
                int(run_result.get("plan_calls") or 0) == expect["plan_calls"],
                run_result.get("plan_calls"),
            )
        if "replan_calls" in expect:
            check(
                "replan calls",
                int(run_result.get("replan_calls") or 0) == expect["replan_calls"],
                run_result.get("replan_calls"),
            )
    except Exception as exc:  # an assertion must never kill the suite
        check(
            "expectation evaluation",
            False,
            f"{type(exc).__name__}: {exc}",
        )


def _run_planning_case(case: Mapping[str, Any]) -> CaseResult:
    case_id = str(case["id"])
    checks: List[Dict[str, Any]] = []
    actual: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
    try:
        plan = HeuristicPlanner().plan(str(case["task"]))
        actual = _normalize_plan(plan, "planner.plan")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    expected = list(case["expect_plan"])
    _add_check(
        checks,
        f"{case_id}: plan matches",
        actual == expected,
        {"expected": expected, "actual": actual},
    )
    return CaseResult(
        case_id=case_id,
        kind="planning",
        category=str(case["category"]),
        ok=all(check["ok"] for check in checks),
        checks=checks,
        error=error,
        details={
            "task": case["task"],
            "expected_plan": expected,
            "actual_plan": actual,
        },
    )


def _aggregate(results: Sequence[CaseResult]) -> Dict[str, Any]:
    categories: Dict[str, Dict[str, Any]] = {}
    for result in results:
        stats = categories.setdefault(
            result.category,
            {"cases": 0, "passed": 0, "failed": 0, "pass_rate": 0.0},
        )
        stats["cases"] += 1
        if result.ok:
            stats["passed"] += 1
        else:
            stats["failed"] += 1
    for stats in categories.values():
        stats["pass_rate"] = _rate(stats["passed"], stats["cases"])

    runs = [run for result in results for run in result.runs]
    total_runs = len(runs)
    successful_runs = sum(1 for run in runs if run.get("ok"))
    expected_success_runs = sum(
        1 for run in runs if run.get("expected_ok") is True
    )
    successful_expected_runs = sum(
        1
        for run in runs
        if run.get("expected_ok") is True and run.get("ok")
    )
    repair_runs = sum(1 for run in runs if int(run.get("repair_count") or 0) > 0)
    total_steps = sum(int(run.get("steps") or 0) for run in runs)
    total_effective_steps = sum(
        int(run.get("effective_steps") or 0) for run in runs
    )
    approvals_pending = sum(1 for run in runs if run.get("pending"))
    approvals_approved = sum(
        1 for run in runs if run.get("resolution") == "approved"
    )
    approvals_rejected = sum(
        1 for run in runs if run.get("resolution") == "rejected"
    )

    def category_rate(name: str) -> float:
        stats = categories.get(name)
        return float(stats["pass_rate"]) if stats else 0.0

    return {
        "runtime_runs": total_runs,
        "runtime_successes": successful_runs,
        "runtime_success_rate": _rate(successful_runs, total_runs),
        "expected_success_runs": expected_success_runs,
        "expected_success_rate": _rate(
            successful_expected_runs, expected_success_runs
        ),
        "expected_failure_runs": total_runs - expected_success_runs,
        "total_steps": total_steps,
        "total_effective_steps": total_effective_steps,
        "average_steps": round(
            float(total_steps) / total_runs, 2
        ) if total_runs else 0.0,
        "average_effective_steps": round(
            float(total_effective_steps) / total_runs, 2
        ) if total_runs else 0.0,
        "repair_runs": repair_runs,
        "repair_rate": _rate(repair_runs, total_runs),
        "approvals_pending": approvals_pending,
        "approvals_approved": approvals_approved,
        "approvals_rejected": approvals_rejected,
        "recovery_rate": category_rate("recovery"),
        "long_horizon_rate": category_rate("long_horizon"),
        "skill_reuse_rate": category_rate("skill_reuse"),
        "safety_rate": category_rate("safety"),
        "planning_accuracy": category_rate("planning"),
        "categories": categories,
    }


def run_suite(
    suite: EvalSuite,
    *,
    work_root: Optional[str | Path] = None,
    keep: bool = False,
    case_ids: Optional[Iterable[str]] = None,
) -> SuiteResult:
    """Run every selected case in an isolated workspace.

    ``work_root`` is for explicit artifact output and is always preserved.
    Without it, a temporary directory is used: kept when ``keep=True`` and
    removed otherwise.  A broken case is recorded as a failed case; it does
    not abort the rest of the suite.
    """

    selected = list(suite.cases)
    if case_ids is not None:
        wanted = {str(item) for item in case_ids}
        selected = [case for case in selected if str(case["id"]) in wanted]
        if not selected:
            raise EvaluationError("no suite cases matched the requested ids")

    cleanup: Optional[tempfile.TemporaryDirectory[str]] = None
    if work_root is not None:
        root = Path(work_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        # A fresh child keeps repeated runs from clobbering artifacts.
        root = root / f"run-{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=False)
    elif keep:
        root = Path(tempfile.mkdtemp(prefix="delamain-eval-"))
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="delamain-eval-")
        root = Path(cleanup.name)

    results: List[CaseResult] = []
    try:
        for index, case in enumerate(selected):
            started = time.perf_counter()
            try:
                if case["kind"] == "planning":
                    result = _run_planning_case(case)
                else:
                    result = _run_execution_case(case, root, index)
            except Exception as exc:
                result = CaseResult(
                    case_id=str(case.get("id") or f"case-{index}"),
                    kind=str(case.get("kind") or "execution"),
                    category=str(case.get("category") or "execution"),
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            result.elapsed_ms = (time.perf_counter() - started) * 1000.0
            if not all(check["ok"] for check in result.checks):
                result.ok = False
            results.append(result)
    finally:
        if cleanup is not None:
            cleanup.cleanup()

    return SuiteResult(
        name=suite.name,
        version=suite.version,
        results=results,
        metrics=_aggregate(results),
        work_root=str(root) if cleanup is None else None,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.delamain.evaluation",
        description=(
            "Run the deterministic Delamain capability suite and print "
            "machine-readable or human-readable metrics."
        ),
    )
    parser.add_argument(
        "--suite",
        default=str(Path("evals") / "delamain_stage17.json"),
        help="path to a JSON evaluation suite",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="write the full JSON report to this path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full JSON report instead of a short summary",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="keep artifacts under a fresh child of this directory",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the temporary artifact directory",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=None,
        help="run only this case id; may be repeated",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=1.0,
        help="exit non-zero when pass_rate is below this value (default: 1.0)",
    )
    return parser


def _print_summary(result: SuiteResult) -> None:
    print(f"Delamain evaluation: {result.name}")
    print(
        f"Cases: {result.cases_passed}/{result.cases_total} "
        f"({result.pass_rate:.1%})"
    )
    metrics = result.metrics
    print(
        "Runtime: "
        f"{metrics.get('runtime_successes', 0)}/"
        f"{metrics.get('runtime_runs', 0)} actual successes; "
        f"expected-success rate: "
        f"{metrics.get('expected_success_rate', 0.0):.1%}"
    )
    print(
        "Recovery: "
        f"{metrics.get('recovery_rate', 0.0):.1%}; "
        "long horizon: "
        f"{metrics.get('long_horizon_rate', 0.0):.1%}; "
        "skill reuse: "
        f"{metrics.get('skill_reuse_rate', 0.0):.1%}; "
        "safety: "
        f"{metrics.get('safety_rate', 0.0):.1%}; "
        "planning: "
        f"{metrics.get('planning_accuracy', 0.0):.1%}"
    )
    if result.work_root:
        print(f"Artifacts: {result.work_root}")
    failures = [item for item in result.results if not item.ok]
    if failures:
        print("Failures:")
        for item in failures:
            failed_checks = [
                check["name"] for check in item.checks if not check["ok"]
            ]
            reason = item.error or ", ".join(failed_checks) or "unknown"
            print(f"  - {item.case_id}: {reason}")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        suite = load_suite(args.suite)
        result = run_suite(
            suite,
            work_root=args.workdir,
            keep=bool(args.keep),
            case_ids=args.case,
        )
    except EvaluationError as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"evaluation I/O error: {exc}", file=sys.stderr)
        return 2

    report = result.to_dict()
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_summary(result)

    threshold = max(0.0, min(1.0, float(args.fail_under)))
    return 0 if result.pass_rate + 1e-9 >= threshold else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
