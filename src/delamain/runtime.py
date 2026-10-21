"""The runtime that closes the action -> observation -> memory loop."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .actions import ActionRegistry
from .memory import MemoryStore
from .models import ActionResult, ActionRequest, TaskResult
from .planner import HeuristicPlanner, PlannerError
from .sandbox import Sandbox


class DelamainRuntime:
    """Execute plans in a sandbox and persist every observation.

    The runtime is intentionally synchronous. It is a small deterministic
    kernel; an LLM can later be plugged in as a planner, but it is not needed
    for the loop to function.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        db_path: Optional[str | Path] = None,
        *,
        sandbox: Optional[Sandbox] = None,
        memory: Optional[MemoryStore] = None,
        registry: Optional[ActionRegistry] = None,
        planner: Optional[HeuristicPlanner] = None,
    ) -> None:
        if memory is None and db_path is None:
            raise ValueError("db_path is required when memory is not provided")
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.sandbox = sandbox or Sandbox(self.workspace_root)
        self.memory = memory or MemoryStore(db_path)  # type: ignore[arg-type]
        self._owns_memory = memory is None
        self.registry = registry or ActionRegistry.default(self.sandbox, self.memory)
        self.planner = planner or HeuristicPlanner()

    # ------------------------------------------------------------------
    # Single steps
    # ------------------------------------------------------------------

    def _normalize_request(
        self,
        request: ActionRequest | Mapping[str, Any] | str,
        args: Optional[Mapping[str, Any]] = None,
    ) -> ActionRequest:
        if isinstance(request, ActionRequest):
            return request
        if isinstance(request, str):
            return ActionRequest(request, dict(args or {}))
        if isinstance(request, Mapping):
            action = request.get("action")
            if not action:
                raise ValueError("action request is missing 'action'")
            request_args = request.get("args", {})
            if request_args is None:
                request_args = {}
            if not isinstance(request_args, Mapping):
                raise ValueError("action request 'args' must be an object")
            return ActionRequest(str(action), dict(request_args))
        raise TypeError(f"unsupported action request: {type(request).__name__}")

    def execute(
        self,
        request: ActionRequest | Mapping[str, Any] | str,
        args: Optional[Mapping[str, Any]] = None,
        *,
        task_id: str = "manual",
        task: str = "",
    ) -> ActionResult:
        """Execute one action and append an episode to memory."""

        req = self._normalize_request(request, args)
        result = self.registry.execute(req.action, req.args)
        metadata = dict(result.metadata)
        metadata["duration_ms"] = result.duration_ms
        self.memory.record_episode(
            task_id=str(task_id),
            task=str(task),
            action=req.action,
            args=req.args,
            ok=result.ok,
            output=result.output,
            error=result.error,
            metadata=metadata,
        )
        return result

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def run_task(
        self,
        task: str,
        plan: Optional[Iterable[ActionRequest | Mapping[str, Any] | str]] = None,
        *,
        task_id: Optional[str] = None,
    ) -> TaskResult:
        """Execute a plan, stopping at the first failed step.

        Every attempted step is written to episodic memory. A task-level
        ``task.start`` / ``task.finish`` pair makes the history easy to read.
        """

        task = str(task)
        task_id = str(task_id or uuid.uuid4().hex)
        self.memory.record_episode(
            task_id=task_id,
            task=task,
            action="task.start",
            args={},
            ok=True,
            output={"task": task},
        )

        if plan is None:
            try:
                plan = self.planner.plan(task)
            except PlannerError as exc:
                self.memory.record_episode(
                    task_id=task_id,
                    task=task,
                    action="task.finish",
                    args={},
                    ok=False,
                    error=str(exc),
                    output={"steps": 0},
                )
                return TaskResult(
                    task_id=task_id,
                    task=task,
                    ok=False,
                    error=str(exc),
                )
            except Exception as exc:  # defensive: planner bugs must not kill the loop
                error = f"planner failed: {type(exc).__name__}: {exc}"
                self.memory.record_episode(
                    task_id=task_id,
                    task=task,
                    action="task.finish",
                    args={},
                    ok=False,
                    error=error,
                    output={"steps": 0},
                )
                return TaskResult(task_id=task_id, task=task, ok=False, error=error)

        if isinstance(plan, (ActionRequest, str, Mapping)):
            raw_plan: List[Any] = [plan]
        else:
            raw_plan = list(plan)

        if not raw_plan:
            error = "plan is empty"
            self.memory.record_episode(
                task_id=task_id,
                task=task,
                action="task.finish",
                args={},
                ok=False,
                error=error,
                output={"steps": 0},
            )
            return TaskResult(task_id=task_id, task=task, ok=False, error=error)

        steps: List[ActionResult] = []
        for raw_step in raw_plan:
            try:
                request = self._normalize_request(raw_step)
            except (TypeError, ValueError) as exc:
                error = f"invalid plan step: {type(exc).__name__}: {exc}"
                self.memory.record_episode(
                    task_id=task_id,
                    task=task,
                    action="task.finish",
                    args={},
                    ok=False,
                    error=error,
                    output={"steps": len(steps)},
                )
                return TaskResult(
                    task_id=task_id,
                    task=task,
                    ok=False,
                    steps=steps,
                    error=error,
                )

            result = self.execute(request, task_id=task_id, task=task)
            steps.append(result)
            if not result.ok:
                self.memory.record_episode(
                    task_id=task_id,
                    task=task,
                    action="task.finish",
                    args={},
                    ok=False,
                    error=result.error,
                    output={"steps": len(steps)},
                )
                return TaskResult(
                    task_id=task_id,
                    task=task,
                    ok=False,
                    steps=steps,
                    final_output=result.output,
                    error=result.error,
                )

        final_output = steps[-1].output if steps else None
        self.memory.record_episode(
            task_id=task_id,
            task=task,
            action="task.finish",
            args={},
            ok=True,
            output={"steps": len(steps)},
        )
        return TaskResult(
            task_id=task_id,
            task=task,
            ok=True,
            steps=steps,
            final_output=final_output,
        )

    # ------------------------------------------------------------------
    # Introspection and lifecycle
    # ------------------------------------------------------------------

    def describe_actions(self) -> List[Dict[str, Any]]:
        return [spec.to_dict() for spec in self.registry.specs()]

    def history(self, task_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        return self.memory.recent_episodes(task_id=task_id, limit=limit)

    def close(self) -> None:
        if self._owns_memory:
            self.memory.close()

    def __enter__(self) -> "DelamainRuntime":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
