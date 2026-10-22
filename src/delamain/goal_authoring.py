"""Safe authoring of executable payloads for cognitive goals.

Stage 12 links a cognitive goal to Delamain only when the goal already carries
an explicit ``execution`` payload.  This module is the missing authoring layer:

* ``/goals exec`` can attach an explicit command (a human decision);
* ``/goals propose`` can ask the configured planner (heuristic or local LLM)
  for a plan, but only stores a **proposal**;
* ``/goals accept`` attaches an approved proposal, ``/goals reject`` discards
  it;
* a proposal records its steps, affected files, dangerous actions, the current
  approval mode and the final decision in the cognitive goal itself.

The module never executes an action.  Execution still goes through the
Delamain runtime, including the existing approval gate for dangerous plans.
Planner-generated proposals are disabled by default
(``DELAMAIN_GOAL_PROPOSAL_ENABLED``); the manual command path is explicit and
does not require the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .models import ActionRequest, utc_now_iso
from .planner import HeuristicPlanner


PROPOSAL_STATUSES = ("pending", "accepted", "rejected", "error")
AUTHORABLE_GOAL_STATUSES = ("active", "pending")


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_plan(plan: Any) -> List[Dict[str, Any]]:
    """Return a JSON-safe list of ``{action, args}`` steps."""

    if plan is None:
        return []
    if isinstance(plan, (ActionRequest, Mapping, str)):
        raw_steps: List[Any] = [plan]
    elif isinstance(plan, (list, tuple)):
        raw_steps = list(plan)
    else:
        raise ValueError(f"unsupported plan type: {type(plan).__name__}")

    steps: List[Dict[str, Any]] = []
    for index, step in enumerate(raw_steps, 1):
        if isinstance(step, ActionRequest):
            action = step.action
            args = step.args
        elif isinstance(step, str):
            action = step
            args = {}
        elif isinstance(step, Mapping):
            action = step.get("action")
            args = step.get("args", {})
        else:
            raise ValueError(f"plan step {index} is not an action request")

        if not isinstance(action, str) or not action.strip():
            raise ValueError(f"plan step {index} has no action name")
        if args is None:
            args = {}
        if not isinstance(args, Mapping):
            raise ValueError(f"plan step {index} args must be an object")
        steps.append({"action": action.strip(), "args": dict(args)})
    return steps


def _validate_plan(plan: Sequence[Mapping[str, Any]], registry: Any) -> List[Dict[str, Any]]:
    """Reject unknown actions before a proposal can be accepted."""

    steps = _normalize_plan(plan)
    if not steps:
        raise ValueError("plan is empty")
    if registry is None:
        return steps
    get = getattr(registry, "get", None)
    if not callable(get):
        return steps
    unknown = [
        str(step["action"])
        for step in steps
        if get(str(step["action"])) is None
    ]
    if unknown:
        names = ", ".join(dict.fromkeys(unknown))
        raise ValueError(f"unknown action(s): {names}")
    return steps


def _plan_files(plan: Sequence[Mapping[str, Any]]) -> List[str]:
    files: List[str] = []
    for step in plan:
        args = step.get("args")
        if not isinstance(args, Mapping):
            continue
        path = args.get("path")
        if path is None:
            continue
        value = str(path).strip()
        if value and value not in files:
            files.append(value)
    return files


def _plan_summary(plan: Sequence[Mapping[str, Any]]) -> str:
    parts: List[str] = []
    for step in plan:
        action = str(step.get("action") or "?")
        args = step.get("args")
        details: List[str] = []
        if isinstance(args, Mapping):
            path = args.get("path")
            if path is not None:
                details.append(str(path))
            pattern = args.get("pattern")
            if pattern is not None and path is None:
                details.append(str(pattern))
            if action in ("remember_fact", "recall_facts"):
                key = args.get("key") or args.get("query")
                if key is not None:
                    details.append(str(key))
            if action == "save_goal" and args.get("title") is not None:
                details.append(str(args["title"]))
        if details:
            parts.append(f"{action}:{' '.join(details)}")
        else:
            parts.append(action)
    if len(parts) > 8:
        return " → ".join(parts[:8]) + " → …"
    return " → ".join(parts)


def _string_list(value: Any) -> List[str]:
    """Normalize a metadata value that should be a list of strings."""

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _coerce_proposal(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    return dict(value)


@dataclass
class GoalExecutionProposal:
    """A reviewable executable payload for one cognitive goal."""

    command: Optional[str] = None
    plan: List[Dict[str, Any]] = field(default_factory=list)
    success_predicate: str = ""
    summary: str = ""
    files: List[str] = field(default_factory=list)
    dangerous_actions: List[str] = field(default_factory=list)
    requires_approval: bool = False
    approval_mode: str = "off"
    source: str = "manual"
    planner_mode: str = ""
    status: str = "pending"
    error: Optional[str] = None
    planner_error: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    decided_at: Optional[str] = None
    reason: str = ""

    @property
    def has_payload(self) -> bool:
        return bool(self.command or self.plan)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "plan": [dict(step) for step in self.plan],
            "success_predicate": self.success_predicate,
            "summary": self.summary,
            "files": list(self.files),
            "dangerous_actions": list(self.dangerous_actions),
            "requires_approval": bool(self.requires_approval),
            "approval_mode": self.approval_mode,
            "source": self.source,
            "planner_mode": self.planner_mode,
            "status": self.status,
            "error": self.error,
            "planner_error": self.planner_error,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Any) -> Optional["GoalExecutionProposal"]:
        data = _coerce_proposal(value)
        if data is None:
            return None
        try:
            plan = _normalize_plan(data.get("plan"))
        except (TypeError, ValueError) as exc:
            plan = []
            data = dict(data)
            data["error"] = data.get("error") or str(exc)
        status = str(data.get("status") or "pending")
        if status not in PROPOSAL_STATUSES:
            status = "error"
        return cls(
            command=(
                str(data["command"]).strip()
                if data.get("command") is not None
                else None
            ),
            plan=plan,
            success_predicate=str(data.get("success_predicate") or ""),
            summary=str(data.get("summary") or ""),
            files=_string_list(data.get("files")),
            dangerous_actions=_string_list(data.get("dangerous_actions")),
            requires_approval=bool(data.get("requires_approval", False)),
            approval_mode=str(data.get("approval_mode") or "off"),
            source=str(data.get("source") or "manual"),
            planner_mode=str(data.get("planner_mode") or ""),
            status=status,
            error=data.get("error"),
            planner_error=data.get("planner_error"),
            created_at=str(data.get("created_at") or utc_now_iso()),
            decided_at=(
                str(data["decided_at"])
                if data.get("decided_at") is not None
                else None
            ),
            reason=str(data.get("reason") or ""),
        )


class GoalAuthoring:
    """Create, store and decide on executable payloads for cognitive goals."""

    def __init__(self, subsystem: Any) -> None:
        self.subsystem = subsystem
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.subsystem, "enabled", False))

    @property
    def proposal_enabled(self) -> bool:
        return bool(getattr(self.subsystem, "goal_proposal_enabled", False))

    def status(self) -> Dict[str, Any]:
        counts = {status: 0 for status in PROPOSAL_STATUSES}
        goal_subsystem = self._goal_subsystem()
        if goal_subsystem is not None:
            for goal in list(getattr(goal_subsystem, "goals", []) or []):
                proposal = _coerce_proposal(goal.get("execution_proposal"))
                if proposal is None:
                    continue
                status = str(proposal.get("status") or "pending")
                if status not in counts:
                    status = "error"
                counts[status] += 1
        return {
            "enabled": self.enabled,
            "proposal_enabled": self.proposal_enabled,
            "last_error": self._last_error,
            "counts": counts,
        }

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    def build_manual(
        self,
        goal_id: int,
        command: str,
        *,
        success_predicate: str = "",
        agent: Any = None,
    ) -> Dict[str, Any]:
        """Attach an explicit command to a cognitive goal.

        This is the ``/goals exec`` path.  The user already made the decision,
        so the proposal is stored as accepted immediately.  The heuristic
        planner is used only for a deterministic preview; it is never required
        for the actual runtime planner.
        """

        goal, error = self._resolve_target(goal_id, agent=agent)
        if error is not None:
            return self._error(goal_id, error, goal=goal)

        command = str(command or "").strip()
        if not command:
            return self._error(goal_id, "command must not be empty", goal=goal)
        if self._has_payload(goal):
            return self._error(
                goal_id,
                "goal already has an executable payload; refusing to overwrite it",
                goal=goal,
            )
        if not getattr(self.subsystem, "enabled", True):
            return self._error(
                goal_id,
                "Delamain-local is disabled; run /delamain on or set "
                "DELAMAIN_ENABLED=1 before authoring",
                goal=goal,
            )

        existing = GoalExecutionProposal.from_dict(goal.get("execution_proposal"))
        if existing is not None and existing.status == "pending":
            return self._error(
                goal_id,
                "a pending proposal already exists; accept or reject it first",
                goal=goal,
                proposal=existing,
            )

        try:
            runtime = self.subsystem._ensure_runtime()
        except Exception as exc:
            return self._error(
                goal_id,
                f"Delamain runtime is unavailable: {type(exc).__name__}: {exc}",
                goal=goal,
            )

        plan: List[Dict[str, Any]] = []
        planner_error: Optional[str] = None
        try:
            preview = HeuristicPlanner().plan(command)
        except Exception as exc:
            # The heuristic planner does not understand this command.  Keep the
            # explicit command: the configured runtime planner may still handle
            # it, and a failure will be visible during execution.
            planner_error = f"{type(exc).__name__}: {exc}"
        else:
            try:
                plan = _validate_plan(preview, runtime.registry)
            except Exception as exc:
                # A preview that produced actions with unknown names is not a
                # safe payload.  Refuse it before attach.
                return self._error(
                    goal_id,
                    f"preview plan is invalid: {type(exc).__name__}: {exc}",
                    goal=goal,
                )

        dangerous, requires_approval = self._evaluate_plan(runtime, plan)
        proposal = GoalExecutionProposal(
            command=command,
            plan=plan,
            success_predicate=str(success_predicate or "").strip(),
            summary=(
                _plan_summary(plan)
                if plan
                else "план не построен; будет запрошен у планировщика при выполнении"
            ),
            files=_plan_files(plan),
            dangerous_actions=dangerous,
            requires_approval=requires_approval,
            approval_mode=str(getattr(runtime.approval_policy, "mode", "off")),
            source="manual",
            planner_mode="heuristic",
            status="accepted",
            planner_error=planner_error,
        )

        attached = self._attach(goal, proposal, agent=agent)
        if not attached:
            return self._error(
                goal_id,
                "could not attach the payload to the cognitive goal",
                goal=goal,
                proposal=proposal,
            )

        self._store_proposal(goal, proposal, agent=agent)
        self._store_decision(
            goal,
            accepted=True,
            source="manual",
            proposal=proposal,
            agent=agent,
        )
        return self._success(goal, proposal, message="payload attached")

    def propose(
        self,
        goal_id: int,
        *,
        task: Optional[str] = None,
        agent: Any = None,
    ) -> Dict[str, Any]:
        """Ask the configured planner for a plan and store it as a proposal."""

        if not self.proposal_enabled:
            return self._error(
                goal_id,
                "planner proposals are disabled; set DELAMAIN_GOAL_PROPOSAL_ENABLED=1 "
                "or use /goals exec for an explicit command",
            )

        goal, error = self._resolve_target(goal_id, agent=agent)
        if error is not None:
            return self._error(goal_id, error, goal=goal)
        if self._has_payload(goal):
            return self._error(
                goal_id,
                "goal already has an executable payload; refusing to replace it",
                goal=goal,
            )
        if not getattr(self.subsystem, "enabled", True):
            return self._error(
                goal_id,
                "Delamain-local is disabled; run /delamain on or set "
                "DELAMAIN_ENABLED=1 before proposing",
                goal=goal,
            )

        task_text = str(task if task is not None else goal.get("title") or "").strip()
        if not task_text:
            return self._error(
                goal_id,
                "cannot propose a plan: goal has no title and no task was given",
                goal=goal,
            )

        try:
            runtime = self.subsystem._ensure_runtime()
        except Exception as exc:
            return self._error(
                goal_id,
                f"Delamain runtime is unavailable: {type(exc).__name__}: {exc}",
                goal=goal,
            )

        planner = runtime.planner
        source, planner_mode = self._planner_info(runtime)
        try:
            requests = planner.plan(task_text)
            plan = _validate_plan(requests, runtime.registry)
        except Exception as exc:
            proposal = GoalExecutionProposal(
                summary="proposal could not be built",
                source=source,
                planner_mode=planner_mode,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                planner_error=str(exc),
            )
            self._store_proposal(goal, proposal, agent=agent)
            return self._error(
                goal_id,
                f"planner could not build a safe plan: {type(exc).__name__}: {exc}",
                goal=goal,
                proposal=proposal,
            )

        dangerous, requires_approval = self._evaluate_plan(runtime, plan)
        proposal = GoalExecutionProposal(
            plan=plan,
            summary=_plan_summary(plan),
            files=_plan_files(plan),
            dangerous_actions=dangerous,
            requires_approval=requires_approval,
            approval_mode=str(getattr(runtime.approval_policy, "mode", "off")),
            source=source,
            planner_mode=planner_mode,
            status="pending",
        )
        self._store_proposal(goal, proposal, agent=agent)
        return self._success(goal, proposal, message="proposal stored")

    def accept(self, goal_id: int, *, agent: Any = None) -> Dict[str, Any]:
        """Attach a pending proposal after the user explicitly accepts it."""

        goal, error = self._resolve_target(goal_id, agent=agent)
        if error is not None:
            return self._error(goal_id, error, goal=goal)

        proposal = GoalExecutionProposal.from_dict(goal.get("execution_proposal"))
        if proposal is None:
            return self._error(goal_id, "no proposal to accept", goal=goal)
        if proposal.status != "pending":
            return self._error(
                goal_id,
                f"proposal is {proposal.status}; only a pending proposal can be accepted",
                goal=goal,
                proposal=proposal,
            )
        if self._has_payload(goal):
            return self._error(
                goal_id,
                "goal already has an executable payload; refusing to overwrite it",
                goal=goal,
                proposal=proposal,
            )
        if not proposal.has_payload:
            return self._error(
                goal_id,
                "proposal has no command or plan",
                goal=goal,
                proposal=proposal,
            )
        if not getattr(self.subsystem, "enabled", True):
            return self._error(
                goal_id,
                "Delamain-local is disabled; run /delamain on or set "
                "DELAMAIN_ENABLED=1 before accepting",
                goal=goal,
                proposal=proposal,
            )

        try:
            runtime = self.subsystem._ensure_runtime()
        except Exception as exc:
            return self._error(
                goal_id,
                f"Delamain runtime is unavailable: {type(exc).__name__}: {exc}",
                goal=goal,
                proposal=proposal,
            )

        try:
            plan = _validate_plan(proposal.plan, runtime.registry) if proposal.plan else []
        except Exception as exc:
            proposal.status = "error"
            proposal.error = f"{type(exc).__name__}: {exc}"
            proposal.decided_at = utc_now_iso()
            self._store_proposal(goal, proposal, agent=agent)
            return self._error(
                goal_id,
                f"proposal is no longer valid: {proposal.error}",
                goal=goal,
                proposal=proposal,
            )

        dangerous, requires_approval = self._evaluate_plan(runtime, plan)
        proposal.plan = plan
        proposal.dangerous_actions = dangerous
        proposal.requires_approval = requires_approval
        proposal.approval_mode = str(getattr(runtime.approval_policy, "mode", "off"))
        proposal.status = "accepted"
        proposal.decided_at = utc_now_iso()
        proposal.error = None

        attached = self._attach(goal, proposal, agent=agent)
        if not attached:
            proposal.status = "pending"
            proposal.decided_at = None
            return self._error(
                goal_id,
                "could not attach the accepted proposal",
                goal=goal,
                proposal=proposal,
            )

        self._store_proposal(goal, proposal, agent=agent)
        self._store_decision(
            goal,
            accepted=True,
            source=proposal.source or "proposal",
            proposal=proposal,
            agent=agent,
        )
        return self._success(goal, proposal, message="proposal accepted")

    def reject(
        self,
        goal_id: int,
        *,
        reason: str = "",
        agent: Any = None,
    ) -> Dict[str, Any]:
        """Reject a pending proposal without attaching or executing it."""

        goal, error = self._resolve_target(goal_id, agent=agent)
        if error is not None:
            return self._error(goal_id, error, goal=goal)

        proposal = GoalExecutionProposal.from_dict(goal.get("execution_proposal"))
        if proposal is None:
            return self._error(goal_id, "no proposal to reject", goal=goal)
        if proposal.status == "accepted":
            return self._error(
                goal_id,
                "proposal is already accepted and cannot be rejected",
                goal=goal,
                proposal=proposal,
            )
        if proposal.status == "rejected":
            return self._error(
                goal_id,
                "proposal is already rejected",
                goal=goal,
                proposal=proposal,
            )
        if proposal.status not in ("pending", "error"):
            return self._error(
                goal_id,
                f"proposal is {proposal.status}; only pending or error proposals can be rejected",
                goal=goal,
                proposal=proposal,
            )

        proposal.status = "rejected"
        proposal.reason = str(reason or "").strip()
        proposal.decided_at = utc_now_iso()
        self._store_proposal(goal, proposal, agent=agent)
        self._store_decision(
            goal,
            accepted=False,
            source=proposal.source or "proposal",
            proposal=proposal,
            agent=agent,
        )
        return self._success(goal, proposal, message="proposal rejected")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _goal_subsystem(self, agent: Any = None) -> Any:
        agent = agent if agent is not None else getattr(self.subsystem, "_agent", None)
        goal_subsystem = getattr(agent, "goal_subsystem", None)
        if goal_subsystem is None:
            goal_subsystem = getattr(self.subsystem, "_goal_subsystem", None)
        return goal_subsystem

    def _resolve_target(
        self,
        goal_id: int,
        *,
        agent: Any = None,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        goal_subsystem = self._goal_subsystem(agent)
        if goal_subsystem is None:
            return None, "GoalSubsystem is not available"
        parsed_id = _as_int(goal_id)
        if parsed_id is None:
            return None, f"invalid goal id: {goal_id!r}"

        getter = getattr(goal_subsystem, "get_goal", None)
        goal = getter(parsed_id) if callable(getter) else None
        if goal is None:
            goal = next(
                (
                    item
                    for item in list(getattr(goal_subsystem, "goals", []) or [])
                    if _as_int(item.get("id")) == parsed_id
                ),
                None,
            )
        if goal is None:
            return None, f"cognitive goal #{parsed_id} not found"
        status = str(goal.get("status") or "")
        if status not in AUTHORABLE_GOAL_STATUSES:
            return (
                goal,
                f"cognitive goal #{parsed_id} is {status or 'unknown'}; "
                "only active or pending goals can be authored",
            )
        return goal, None

    @staticmethod
    def _has_payload(goal: Mapping[str, Any]) -> bool:
        for key in ("execution", "delamain_execution", "delamain"):
            if goal.get(key):
                return True
        if goal.get("delamain_command") or goal.get("command"):
            return True
        if goal.get("delamain_plan") or goal.get("plan"):
            return True
        return False

    @staticmethod
    def _evaluate_plan(
        runtime: Any,
        plan: Sequence[Mapping[str, Any]],
    ) -> tuple[List[str], bool]:
        if not plan:
            return [], False
        requests = [
            ActionRequest(
                str(step.get("action") or ""),
                dict(step.get("args") or {}),
            )
            for step in plan
        ]
        policy = runtime.approval_policy
        dangerous = list(policy.dangerous_actions(requests))
        requires_approval, _ = policy.evaluate(requests)
        return dangerous, bool(requires_approval)

    def _planner_info(self, runtime: Any) -> tuple[str, str]:
        planner = runtime.planner
        used = str(getattr(planner, "last_used", "") or "")
        if used == "fallback":
            source = "heuristic"
        elif used == "primary":
            source = "llm" if getattr(self.subsystem, "llm_enabled", False) else "planner"
        elif isinstance(planner, HeuristicPlanner):
            source = "heuristic"
        elif getattr(self.subsystem, "llm_enabled", False):
            source = "llm"
        else:
            source = "planner"
        mode = str(
            getattr(self.subsystem, "_planner_mode", "")
            or type(planner).__name__
        )
        return source, mode

    def _attach(
        self,
        goal: Dict[str, Any],
        proposal: GoalExecutionProposal,
        *,
        agent: Any = None,
    ) -> bool:
        goal_subsystem = self._goal_subsystem(agent)
        if goal_subsystem is None:
            return False
        attach = getattr(goal_subsystem, "attach_execution", None)
        if not callable(attach):
            return False
        return bool(
            attach(
                int(goal["id"]),
                command=proposal.command,
                plan=proposal.plan or None,
                success_predicate=proposal.success_predicate,
                replace=False,
            )
        )

    def _store_proposal(
        self,
        goal: Dict[str, Any],
        proposal: GoalExecutionProposal,
        *,
        agent: Any = None,
    ) -> None:
        payload = proposal.to_dict()
        goal_subsystem = self._goal_subsystem(agent)
        setter = getattr(goal_subsystem, "set_execution_proposal", None)
        if callable(setter):
            setter(int(goal["id"]), payload)
        else:
            goal["execution_proposal"] = payload

    def _store_decision(
        self,
        goal: Dict[str, Any],
        *,
        accepted: bool,
        source: str,
        proposal: GoalExecutionProposal,
        agent: Any = None,
    ) -> None:
        decision = {
            "accepted": bool(accepted),
            "source": str(source),
            "proposal_source": proposal.source,
            "proposal_status": proposal.status,
            "requires_approval": bool(proposal.requires_approval),
            "dangerous_actions": list(proposal.dangerous_actions),
            "decided_at": utc_now_iso(),
        }
        goal_subsystem = self._goal_subsystem(agent)
        setter = getattr(goal_subsystem, "set_execution_decision", None)
        if callable(setter):
            setter(int(goal["id"]), decision)
        else:
            goal["execution_decision"] = decision

    def _success(
        self,
        goal: Dict[str, Any],
        proposal: GoalExecutionProposal,
        *,
        message: str,
    ) -> Dict[str, Any]:
        self._last_error = None
        return {
            "ok": True,
            "goal_id": _as_int(goal.get("id")),
            "goal": dict(goal),
            "proposal": proposal.to_dict(),
            "execution": dict(goal.get("execution") or {}),
            "message": message,
            "error": None,
        }

    def _error(
        self,
        goal_id: Any,
        message: str,
        *,
        goal: Optional[Mapping[str, Any]] = None,
        proposal: Optional[GoalExecutionProposal] = None,
    ) -> Dict[str, Any]:
        self._last_error = str(message)
        return {
            "ok": False,
            "goal_id": _as_int(goal_id),
            "goal": dict(goal) if isinstance(goal, Mapping) else None,
            "proposal": proposal.to_dict() if proposal is not None else None,
            "execution": (
                dict(goal.get("execution") or {})
                if isinstance(goal, Mapping)
                else {}
            ),
            "message": str(message),
            "error": str(message),
        }


__all__ = [
    "AUTHORABLE_GOAL_STATUSES",
    "GoalAuthoring",
    "GoalExecutionProposal",
    "PROPOSAL_STATUSES",
]
