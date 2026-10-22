"""Compact failure context shared by the runtime and goal metadata.

Stage 15 stored a bounded description of a failed attempt in the goal.  Stage
16 needs the same structure *inside* one attempt, where a planner may replace
the remaining plan after a failed step.  Keeping the builder here avoids
duplicating the truncation rules and keeps the runtime and subsystem in sync.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional, Sequence

from .models import ActionResult, TaskResult


def _short(value: Any, limit: int) -> Any:
    """Return a JSON-safe scalar or a truncated string representation."""

    if value is None:
        return None
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def compact_value(value: Any, *, limit: int = 500, depth: int = 0) -> Any:
    """Bound nested values before they are stored in metadata or a prompt.

    Failure context can contain a whole file, a long error or a list of facts.
    The planner only needs a readable summary, so strings are truncated and
    containers are capped.  JSON-safe scalar values are preserved.
    """

    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if depth >= 3:
        return _short(value, limit * 2)
    if isinstance(value, Mapping):
        return {
            str(key): compact_value(item, limit=limit, depth=depth + 1)
            for key, item in list(value.items())[:20]
        }
    if isinstance(value, (list, tuple)):
        return [
            compact_value(item, limit=limit, depth=depth + 1)
            for item in list(value)[:20]
        ]
    return value


def _step_dicts(value: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    return [dict(step) for step in value if isinstance(step, Mapping)]


def build_failure_context(
    result: TaskResult,
    *,
    attempt: Optional[int] = None,
    remaining_steps: Optional[Sequence[Mapping[str, Any]]] = None,
    repair_count: Optional[int] = None,
    failed_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a compact description of a failed task/step.

    ``failed_index`` is a zero-based index into ``result.planned_actions``.
    Stage 16 passes it explicitly because one runtime call can contain several
    failed steps separated by successful repair segments; without the override
    the builder would have to guess which failure ended the task.  When it is
    omitted (the Stage 15 durable-context path), the last failed result in
    ``result.steps`` is used.

    ``remaining_steps`` is the part of the plan that was not attempted when a
    step failed.  It is included for in-attempt repair so the planner can
    decide whether to keep or replace that work.
    """

    planned = _step_dicts(result.planned_actions)
    step_results = list(result.steps)
    steps_before = max(0, int(result.steps_before or 0))
    stage = "planning"
    selected_index = failed_index
    failed_result: Optional[ActionResult] = None

    if selected_index is not None:
        selected_index = max(0, int(selected_index))
        offset = selected_index - steps_before
        if 0 <= offset < len(step_results):
            failed_result = step_results[offset]
        if planned:
            stage = "action"
    elif planned and step_results:
        stage = "action"
        for offset, step_result in enumerate(step_results):
            if not step_result.ok:
                selected_index = steps_before + offset
                failed_result = step_result
        if selected_index is None:  # defensive: task failed after all steps
            selected_index = steps_before + len(step_results) - 1
            failed_result = step_results[-1]
    elif planned:
        stage = "normalization"

    failed_action = None
    if (
        selected_index is not None
        and 0 <= selected_index < len(planned)
        and isinstance(planned[selected_index], Mapping)
    ):
        failed_action = planned[selected_index]

    # ``effective_actions`` is authoritative even when it is empty: after a
    # repair the very first attempted step may have failed, and treating the
    # planned prefix as "completed" would lie to the planner.  The runtime
    # always fills this field, including on failure.
    completed = _step_dicts(result.effective_actions)

    context: Dict[str, Any] = {
        "stage": stage,
        "attempt": None if attempt is None else max(1, int(attempt)),
        "failed_step": (
            selected_index + 1 if selected_index is not None else None
        ),
        "action": (
            str(failed_action.get("action"))
            if failed_action and failed_action.get("action")
            else None
        ),
        "args": (
            compact_value(failed_action.get("args") or {})
            if failed_action
            else {}
        ),
        "error": _short(result.error, 1000),
        "output": (
            compact_value(failed_result.output, limit=1000)
            if failed_result is not None
            else None
        ),
        "completed_steps": compact_value(completed),
    }
    if remaining_steps is not None:
        context["remaining_steps"] = compact_value(
            _step_dicts(remaining_steps)
        )
    if repair_count is not None:
        context["repair_count"] = max(0, int(repair_count))
    return {
        key: value
        for key, value in context.items()
        if value is not None
    }


__all__ = ["build_failure_context", "compact_value"]
