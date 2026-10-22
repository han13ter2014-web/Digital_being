"""The runtime that closes the action -> observation -> memory loop."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .actions import ActionRegistry
from .approval import ApprovalPolicy
from .context import build_failure_context
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

    Stage 16 adds optional, bounded step repair. When a step fails and the
    budget allows, the planner may return a *replacement* for the remaining
    plan. The runtime never repeats an already attempted ``action + args``,
    caps both the number of repair segments and the size of one segment, and
    still applies the approval gate to the repair plan. A repair that needs
    approval is stored as a durable continuation; after approval the runtime
    resumes with the already completed steps preserved. Step repair is off by
    default.
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
        step_repair_enabled: bool = False,
        max_step_repairs: int = 1,
        max_repair_steps: int = 5,
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
        self.step_repair_enabled = bool(step_repair_enabled)
        self.max_step_repairs = max(0, int(max_step_repairs))
        self.max_repair_steps = max(1, int(max_repair_steps))
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

    def _normalize_plan(
        self,
        plan: Optional[Iterable[ActionRequest | Mapping[str, Any] | str]],
    ) -> Tuple[Optional[List[ActionRequest]], Optional[str], List[Dict[str, Any]]]:
        """Normalize a plan without recording or executing anything."""

        if plan is None:
            return None, "plan is empty", []
        if isinstance(plan, (ActionRequest, str, Mapping)):
            raw_plan: List[Any] = [plan]
        else:
            try:
                raw_plan = list(plan)
            except TypeError as exc:
                return (
                    None,
                    f"invalid plan: {type(exc).__name__}: {exc}",
                    [],
                )

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
        return self._normalize_plan(plan)

    def _prepare_repair_plan(
        self,
        task: str,
        failure_context: Mapping[str, Any],
    ) -> Tuple[
        Optional[List[ActionRequest]],
        Optional[str],
        List[Dict[str, Any]],
    ]:
        """Ask the planner for a bounded replacement of the remaining plan."""

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

        requests, error, planned = self._normalize_plan(plan)
        if error is not None or requests is None:
            return None, error or "invalid repair plan", planned
        if len(requests) > self.max_repair_steps:
            return (
                None,
                (
                    "repair plan has too many steps "
                    f"({len(requests)} > {self.max_repair_steps})"
                ),
                planned,
            )
        return requests, None, planned

    @staticmethod
    def _action_key(step: Mapping[str, Any]) -> str:
        """Canonical identity used to reject repeated actions and arguments."""

        return json.dumps(
            {
                "action": str(step.get("action") or ""),
                "args": step.get("args") or {},
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

    def _repair_validation_error(
        self,
        requests: Sequence[ActionRequest],
        planned_actions: Sequence[Mapping[str, Any]],
    ) -> Optional[str]:
        """Reject a repair plan that repeats work or uses an unknown action."""

        seen = {
            self._action_key(step)
            for step in planned_actions
            if isinstance(step, Mapping)
        }
        local: set[str] = set()
        for request in requests:
            if self.registry.get(request.action) is None:
                return f"repair plan uses unknown action: {request.action}"
            key = self._action_key(request.to_dict())
            if key in seen:
                return (
                    "repair plan repeats an already attempted step: "
                    f"{request.action}"
                )
            if key in local:
                return f"repair plan contains a duplicate step: {request.action}"
            local.add(key)
        return None

    def _create_approval(
        self,
        *,
        task: str,
        task_id: str,
        requests: List[ActionRequest],
        dangerous_actions: List[str],
        metadata: Optional[Mapping[str, Any]] = None,
        output_extra: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store one approval and record its request episode."""

        planned_actions = self._plan_dicts(requests)
        approval = self.memory.create_approval(
            task_id=task_id,
            task=task,
            plan=planned_actions,
            dangerous_actions=dangerous_actions,
            metadata=dict(metadata or {}),
        )
        output: Dict[str, Any] = {
            "approval_id": approval["id"],
            "dangerous_actions": list(dangerous_actions),
            "plan": planned_actions,
        }
        if output_extra:
            output.update(dict(output_extra))
        self.memory.record_episode(
            task_id=task_id,
            task=task,
            action="approval.requested",
            args={},
            ok=True,
            output=output,
            metadata={"approval_id": approval["id"]},
        )
        return approval

    def _request_approval(
        self,
        *,
        task: str,
        task_id: str,
        requests: List[ActionRequest],
        dangerous_actions: List[str],
    ) -> TaskResult:
        approval = self._create_approval(
            task=task,
            task_id=task_id,
            requests=requests,
            dangerous_actions=dangerous_actions,
        )
        detail = ", ".join(dangerous_actions) if dangerous_actions else "all actions"
        return TaskResult(
            task_id=task_id,
            task=task,
            ok=False,
            error=f"approval required: {detail}",
            planned_actions=self._plan_dicts(requests),
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
        """Execute a plan, stopping at the first unrepaired failed step.

        Planning and normalization happen before ``task.start``. If the
        approval policy requires a decision, the runtime stores the complete
        plan and returns a ``TaskResult`` with ``pending_approval`` set; no
        action and no ``task.start`` episode are written. Calling this method
        with ``approval_id`` executes that stored, already-approved plan.

        ``failure_context`` is optional and is used only when the planner has
        to build a plan. It is passed to a planner's ``replan()`` method when
        available, otherwise the normal ``plan()`` method is used.

        When ``step_repair_enabled`` is true, a failed step may trigger a
        bounded replacement plan from the planner. The replacement applies to
        the remaining work; already completed work is never replayed. See
        :meth:`_execute_plan` for the exact safety rules.
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

    @staticmethod
    def _json_steps(value: Any) -> List[Dict[str, Any]]:
        """Return a safe copy of a JSON list of action dictionaries."""

        if not isinstance(value, (list, tuple)):
            return []
        return [dict(item) for item in value if isinstance(item, Mapping)]

    def run_approved(self, approval_id: str) -> TaskResult:
        """Execute an approved plan exactly once.

        The approval is consumed before the first step. That makes a repeated
        approve/run command harmless even if the caller retries after a crash.

        A Stage 16 repair approval carries the already attempted and effective
        actions in its metadata.  In that case this method resumes the task:
        the stored plan is the replacement remainder, while the prior steps are
        preserved for summaries, failure context and skill recording.
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

        metadata = approval.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        is_repair = metadata.get("kind") == "step_repair"
        prior_actions = self._json_steps(metadata.get("prior_actions"))
        raw_effective = metadata.get("prior_effective_actions")
        if isinstance(raw_effective, (list, tuple)):
            prior_effective_actions = self._json_steps(raw_effective)
        else:
            # Repair approvals always store both lists, including an empty
            # effective list when the very first step failed.  The fallback is
            # only for a hand-edited/legacy row that lacks the key entirely.
            prior_effective_actions = list(prior_actions)
        if not is_repair:
            prior_actions = []
            prior_effective_actions = []
            prior_steps = 0
            repair_count = 0
        else:
            prior_steps = len(prior_actions)
            try:
                repair_count = max(1, int(metadata.get("repair_count") or 1))
            except (TypeError, ValueError):
                repair_count = 1

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
            prior_actions=prior_actions,
            prior_effective_actions=prior_effective_actions,
            steps_before=prior_steps,
            repair_count=repair_count,
        )

    def _execute_plan(
        self,
        *,
        task: str,
        task_id: str,
        requests: List[ActionRequest],
        approval_id: Optional[str] = None,
        prior_actions: Optional[Sequence[Mapping[str, Any]]] = None,
        prior_effective_actions: Optional[Sequence[Mapping[str, Any]]] = None,
        steps_before: int = 0,
        repair_count: int = 0,
    ) -> TaskResult:
        """Execute a plan with optional bounded, replacement-style repair.

        A repair plan replaces the *remaining* queue.  It is not appended in
        front of the old tail, because that would make a repaired step fail
        again on the old follow-up.  The planner receives the old tail in
        ``remaining_steps`` and decides what to keep.

        Every accepted repair consumes one unit of ``max_step_repairs``.  The
        runtime also rejects a repair segment that is larger than
        ``max_repair_steps``, uses an unknown action, contains a duplicate, or
        repeats any previously attempted ``action + args``.  A repeated step
        with changed arguments is allowed: that is a genuine repair, not a
        blind retry.
        """

        planned_actions = self._json_steps(prior_actions)
        effective_actions = self._json_steps(prior_effective_actions)
        steps_before = max(0, int(steps_before or 0))
        if planned_actions:
            steps_before = max(steps_before, len(planned_actions))
        repair_count = max(0, int(repair_count))
        resumed = steps_before > 0 or bool(planned_actions)

        start_metadata: Dict[str, Any] = {}
        if approval_id:
            start_metadata["approval_id"] = approval_id
        if resumed:
            start_metadata.update(
                {
                    "resume": True,
                    "steps_before": steps_before,
                    "repair_count": repair_count,
                }
            )
        start_output: Dict[str, Any] = {"task": task}
        if resumed:
            start_output.update(
                {
                    "steps_before": steps_before,
                    "repair_count": repair_count,
                }
            )
        self.memory.record_episode(
            task_id=task_id,
            task=task,
            action="task.resume" if resumed else "task.start",
            args={},
            ok=True,
            output=start_output,
            metadata=start_metadata,
        )

        steps: List[ActionResult] = []
        queue: List[ActionRequest] = list(requests)
        repair_error: Optional[str] = None
        while queue:
            request = queue.pop(0)
            action_dict = request.to_dict()
            planned_actions.append(action_dict)
            result = self._execute_step(request, task_id=task_id, task=task)
            steps.append(result)
            if result.ok:
                effective_actions.append(action_dict)
                continue

            repair_error = None
            if (
                self.step_repair_enabled
                and repair_count < self.max_step_repairs
            ):
                # The current failure is the last attempted step.  Passing the
                # exact index matters when earlier repair segments failed too.
                failed_index = len(planned_actions) - 1
                snapshot = TaskResult(
                    task_id=task_id,
                    task=task,
                    ok=False,
                    steps=steps,
                    final_output=result.output,
                    error=result.error,
                    planned_actions=planned_actions,
                    effective_actions=effective_actions,
                    steps_before=steps_before,
                    repair_count=repair_count,
                )
                context = build_failure_context(
                    snapshot,
                    remaining_steps=self._plan_dicts(queue),
                    repair_count=repair_count,
                    failed_index=failed_index,
                )
                repair_requests, prep_error, repair_planned = (
                    self._prepare_repair_plan(task, context)
                )
                if repair_requests is not None and prep_error is None:
                    validation_error = self._repair_validation_error(
                        repair_requests,
                        planned_actions,
                    )
                else:
                    validation_error = prep_error or (
                        "planner returned no repair plan"
                    )

                if validation_error is None and repair_requests is not None:
                    requires_approval, dangerous_actions = (
                        self.approval_policy.evaluate(repair_requests)
                    )
                    next_repair_count = repair_count + 1
                    repair_output = {
                        "failed_step": context.get("failed_step"),
                        "failed_action": context.get("action"),
                        "plan": repair_planned,
                        "repair_count": next_repair_count,
                    }
                    if requires_approval:
                        repair_output["approval_pending"] = True
                        self.memory.record_episode(
                            task_id=task_id,
                            task=task,
                            action="task.repair",
                            args={},
                            ok=True,
                            output=repair_output,
                            metadata={"repair_count": next_repair_count},
                        )
                        approval = self._create_approval(
                            task=task,
                            task_id=task_id,
                            requests=repair_requests,
                            dangerous_actions=dangerous_actions,
                            metadata={
                                "kind": "step_repair",
                                "prior_actions": list(planned_actions),
                                "prior_effective_actions": list(
                                    effective_actions
                                ),
                                "prior_steps": len(planned_actions),
                                "repair_count": next_repair_count,
                                "failed_step": context.get("failed_step"),
                                "failure_context": context,
                            },
                            output_extra={
                                "repair": True,
                                "failed_step": context.get("failed_step"),
                                "prior_steps": len(planned_actions),
                            },
                        )
                        detail = (
                            ", ".join(dangerous_actions)
                            if dangerous_actions
                            else "all actions"
                        )
                        # The original approval (if any) is already consumed;
                        # the returned summary must point at the new pending
                        # repair approval instead.
                        return TaskResult(
                            task_id=task_id,
                            task=task,
                            ok=False,
                            steps=steps,
                            error=f"approval required: {detail}",
                            planned_actions=planned_actions,
                            effective_actions=effective_actions,
                            steps_before=steps_before,
                            repair_count=next_repair_count,
                            pending_approval=approval,
                            approval_id=None,
                        )

                    repair_count = next_repair_count
                    self.memory.record_episode(
                        task_id=task_id,
                        task=task,
                        action="task.repair",
                        args={},
                        ok=True,
                        output=repair_output,
                        metadata={"repair_count": repair_count},
                    )
                    # Replacement, not insertion: the old tail is discarded.
                    queue = list(repair_requests)
                    continue

                repair_error = validation_error or "repair plan rejected"
                self.memory.record_episode(
                    task_id=task_id,
                    task=task,
                    action="task.repair.rejected",
                    args={},
                    ok=False,
                    error=repair_error,
                    output={
                        "failed_step": context.get("failed_step"),
                        "failed_action": context.get("action"),
                        "reason": repair_error,
                        "plan": repair_planned,
                    },
                    metadata={"repair_count": repair_count},
                )

            include_effective = (
                self.step_repair_enabled or resumed or repair_count > 0
            )
            finish_output: Dict[str, Any] = {
                "steps": steps_before + len(steps),
                "planned_actions": list(planned_actions),
            }
            if include_effective:
                finish_output["effective_actions"] = list(effective_actions)
                finish_output["repair_count"] = repair_count
            if repair_error:
                finish_output["repair_error"] = repair_error
            finish_metadata = dict(start_metadata)
            if include_effective:
                finish_metadata["repair_count"] = repair_count
            self.memory.record_episode(
                task_id=task_id,
                task=task,
                action="task.finish",
                args={},
                ok=False,
                error=result.error,
                output=finish_output,
                metadata=finish_metadata,
            )
            return TaskResult(
                task_id=task_id,
                task=task,
                ok=False,
                steps=steps,
                final_output=result.output,
                error=result.error,
                planned_actions=planned_actions,
                effective_actions=effective_actions,
                steps_before=steps_before,
                repair_count=repair_count,
                approval_id=approval_id,
            )

        final_output = steps[-1].output if steps else None
        include_effective = (
            self.step_repair_enabled or resumed or repair_count > 0
        )
        finish_output = {
            "steps": steps_before + len(steps),
            "planned_actions": list(planned_actions),
        }
        if include_effective:
            finish_output["effective_actions"] = list(effective_actions)
            finish_output["repair_count"] = repair_count
        finish_metadata = dict(start_metadata)
        if include_effective:
            finish_metadata["repair_count"] = repair_count
        self.memory.record_episode(
            task_id=task_id,
            task=task,
            action="task.finish",
            args={},
            ok=True,
            output=finish_output,
            metadata=finish_metadata,
        )
        return TaskResult(
            task_id=task_id,
            task=task,
            ok=True,
            steps=steps,
            final_output=final_output,
            planned_actions=planned_actions,
            effective_actions=effective_actions,
            steps_before=steps_before,
            repair_count=repair_count,
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
