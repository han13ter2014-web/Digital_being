"""The runtime that closes the action -> observation -> memory loop."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .actions import ActionRegistry
from .approval import ApprovalPolicy
from .memory import MemoryStore
from .models import ActionResult, ActionRequest, TaskResult
from .planner import HeuristicPlanner, Planner, PlannerError
from .sandbox import Sandbox


class DelamainRuntime:
    """Execute plans in a sandbox and persist every observation.

    The runtime is intentionally synchronous. It is a small deterministic
    kernel; an LLM can be plugged in as a planner, but it is not needed for
    the loop to function.

    Approval is a preflight gate for the *whole* plan: if any step is marked
    dangerous (or if mode is ``all``), no step runs until the user approves
    the stored plan. The approved plan is consumed exactly once.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        db_path: Optional[str | Path] = None,
        *,
        sandbox: Optional[Sandbox] = None,
        memory: Optional[MemoryStore] = None,
        registry: Optional[ActionRegistry] = None,
        planner: Optional[Planner] = None,
        approval_mode: str = "off",
        approval_policy: Optional[ApprovalPolicy] = None,
    ) -> None:
        if memory is None and db_path is None:
            raise ValueError("db_path is required when memory is not provided")
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.sandbox = sandbox or Sandbox(self.workspace_root)
        self.memory = memory or MemoryStore(db_path)  # type: ignore[arg-type]
        self._owns_memory = memory is None
        self.registry = registry or ActionRegistry.default(self.sandbox, self.memory)
        self.planner = planner or HeuristicPlanner()
        self.approval_policy = approval_policy or ApprovalPolicy(approval_mode)
        self.approval_policy.bind_registry(self.registry)
        # A model-backed planner needs the live action schema, which only
        # exists after the registry has been built. Binding is optional so
        # simple custom planners do not need to implement it.
        bind_registry = getattr(self.planner, "bind_registry", None)
        if callable(bind_registry):
            bind_registry(self.registry)

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

    def _execute_step(
        self,
        request: ActionRequest | Mapping[str, Any] | str,
        args: Optional[Mapping[str, Any]] = None,
        *,
        task_id: str = "manual",
        task: str = "",
    ) -> ActionResult:
        """Execute one normalized action and append an episode to memory."""

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

    def execute(
        self,
        request: ActionRequest | Mapping[str, Any] | str,
        args: Optional[Mapping[str, Any]] = None,
        *,
        task_id: str = "manual",
        task: str = "",
    ) -> ActionResult:
        """Execute one action without the task-level approval preflight.

        This is the low-level primitive used by callers that already own the
        approval decision. Agent/planner execution goes through
        :meth:`run_task`, where the whole plan is checked before any step.
        """

        return self._execute_step(request, args, task_id=task_id, task=task)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    @staticmethod
    def _plan_dicts(requests: Iterable[ActionRequest]) -> List[Dict[str, Any]]:
        return [request.to_dict() for request in requests]

    def _plan(
        self,
        task: str,
        failure_context: Optional[Mapping[str, Any]],
    ) -> Iterable[ActionRequest]:
        """Ask the planner for a plan, using repair context when available."""

        if failure_context is not None:
            replan = getattr(self.planner, "replan", None)
            if callable(replan):
                return replan(task, dict(failure_context))
        return self.planner.plan(task)

    def _prepare_plan(
        self,
        task: str,
        plan: Optional[Iterable[ActionRequest | Mapping[str, Any] | str]],
        failure_context: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[Optional[List[ActionRequest]], Optional[str], List[Dict[str, Any]]]:
        """Resolve and normalize a plan before any task is recorded or run."""

        if plan is None:
            try:
                plan = self._plan(task, failure_context)
            except PlannerError as exc:
                return None, str(exc), []
            except Exception as exc:  # planner bugs must not kill the loop
                return (
                    None,
                    f"planner failed: {type(exc).__name__}: {exc}",
                    [],
                )

        if isinstance(plan, (ActionRequest, str, Mapping)):
            raw_plan: List[Any] = [plan]
        else:
            raw_plan = list(plan)

        if not raw_plan:
            return None, "plan is empty", []

        requests: List[ActionRequest] = []
        for raw_step in raw_plan:
            try:
                request = self._normalize_request(raw_step)
            except (TypeError, ValueError) as exc:
                return (
                    None,
                    f"invalid plan step: {type(exc).__name__}: {exc}",
                    self._plan_dicts(requests),
                )
            requests.append(request)
        return requests, None, self._plan_dicts(requests)

    def _request_approval(
        self,
        *,
        task: str,
        task_id: str,
        requests: List[ActionRequest],
        dangerous_actions: List[str],
    ) -> TaskResult:
        planned_actions = self._plan_dicts(requests)
        approval = self.memory.create_approval(
            task_id=task_id,
            task=task,
            plan=planned_actions,
            dangerous_actions=dangerous_actions,
        )
        self.memory.record_episode(
            task_id=task_id,
            task=task,
            action="approval.requested",
            args={},
            ok=True,
            output={
                "approval_id": approval["id"],
                "dangerous_actions": list(dangerous_actions),
                "plan": planned_actions,
            },
            metadata={"approval_id": approval["id"]},
        )
        detail = ", ".join(dangerous_actions) if dangerous_actions else "all actions"
        return TaskResult(
            task_id=task_id,
            task=task,
            ok=False,
            error=f"approval required: {detail}",
            planned_actions=planned_actions,
            pending_approval=approval,
        )

    def run_task(
        self,
        task: str,
        plan: Optional[Iterable[ActionRequest | Mapping[str, Any] | str]] = None,
        *,
        task_id: Optional[str] = None,
        approval_id: Optional[str] = None,
        failure_context: Optional[Mapping[str, Any]] = None,
    ) -> TaskResult:
        """Execute a plan, stopping at the first failed step.

        Planning and normalization happen before ``task.start``. If the
        approval policy requires a decision, the runtime stores the complete
        plan and returns a ``TaskResult`` with ``pending_approval`` set; no
        action and no ``task.start`` episode are written. Calling this method
        with ``approval_id`` executes that stored, already-approved plan.

        ``failure_context`` is optional and is used only when the planner has
        to build a plan. It is passed to a planner's ``replan()`` method when
        available, otherwise the normal ``plan()`` method is used.
        """

        if approval_id:
            return self.run_approved(approval_id)

        task = str(task)
        task_id = str(task_id or uuid.uuid4().hex)
        requests, error, planned_actions = self._prepare_plan(
            task,
            plan,
            failure_context,
        )
        if error is not None or requests is None:
            return TaskResult(
                task_id=task_id,
                task=task,
                ok=False,
                error=error or "invalid plan",
                planned_actions=planned_actions,
            )

        requires_approval, dangerous_actions = self.approval_policy.evaluate(requests)
        if requires_approval:
            return self._request_approval(
                task=task,
                task_id=task_id,
                requests=requests,
                dangerous_actions=dangerous_actions,
            )

        return self._execute_plan(
            task=task,
            task_id=task_id,
            requests=requests,
        )

    def run_approved(self, approval_id: str) -> TaskResult:
        """Execute an approved plan exactly once.

        The approval is consumed before the first step. That makes a repeated
        approve/run command harmless even if the caller retries after a crash.
        """

        approval = self.memory.get_approval(approval_id)
        if approval is None:
            return TaskResult(
                task_id="",
                task="",
                ok=False,
                error=f"approval not found: {approval_id}",
            )

        task_id = str(approval.get("task_id") or "")
        task = str(approval.get("task") or "")
        if approval.get("status") != "approved":
            return TaskResult(
                task_id=task_id,
                task=task,
                ok=False,
                error=(
                    f"approval {approval_id} is {approval.get('status')}; "
                    "expected approved"
                ),
                planned_actions=list(approval.get("plan") or []),
            )

        requests: List[ActionRequest] = []
        try:
            for raw_step in approval.get("plan") or []:
                requests.append(self._normalize_request(raw_step))
        except (TypeError, ValueError) as exc:
            return TaskResult(
                task_id=task_id,
                task=task,
                ok=False,
                error=f"stored approval plan is invalid: {exc}",
                planned_actions=list(approval.get("plan") or []),
            )
        if not requests:
            return TaskResult(
                task_id=task_id,
                task=task,
                ok=False,
                error="stored approval plan is empty",
            )

        if not self.memory.consume_approval(approval_id):
            current = self.memory.get_approval(approval_id)
            state = current.get("status") if current else "missing"
            return TaskResult(
                task_id=task_id,
                task=task,
                ok=False,
                error=f"approval {approval_id} is not reusable (status={state})",
                planned_actions=list(approval.get("plan") or []),
            )

        return self._execute_plan(
            task=task,
            task_id=task_id,
            requests=requests,
            approval_id=approval_id,
        )

    def _execute_plan(
        self,
        *,
        task: str,
        task_id: str,
        requests: List[ActionRequest],
        approval_id: Optional[str] = None,
    ) -> TaskResult:
        planned_actions = self._plan_dicts(requests)
        start_metadata: Dict[str, Any] = {}
        if approval_id:
            start_metadata["approval_id"] = approval_id
        self.memory.record_episode(
            task_id=task_id,
            task=task,
            action="task.start",
            args={},
            ok=True,
            output={"task": task},
            metadata=start_metadata,
        )

        steps: List[ActionResult] = []
        attempted: List[Dict[str, Any]] = []
        for request in requests:
            attempted.append(request.to_dict())
            result = self._execute_step(request, task_id=task_id, task=task)
            steps.append(result)
            if not result.ok:
                self.memory.record_episode(
                    task_id=task_id,
                    task=task,
                    action="task.finish",
                    args={},
                    ok=False,
                    error=result.error,
                    output={
                        "steps": len(steps),
                        "planned_actions": list(attempted),
                    },
                    metadata=start_metadata,
                )
                return TaskResult(
                    task_id=task_id,
                    task=task,
                    ok=False,
                    steps=steps,
                    final_output=result.output,
                    error=result.error,
                    planned_actions=attempted,
                    approval_id=approval_id,
                )

        final_output = steps[-1].output if steps else None
        self.memory.record_episode(
            task_id=task_id,
            task=task,
            action="task.finish",
            args={},
            ok=True,
            output={
                "steps": len(steps),
                "planned_actions": list(attempted),
            },
            metadata=start_metadata,
        )
        return TaskResult(
            task_id=task_id,
            task=task,
            ok=True,
            steps=steps,
            final_output=final_output,
            planned_actions=attempted,
            approval_id=approval_id,
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
