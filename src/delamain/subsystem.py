"""Optional integration of the Delamain-local runtime with Digital Being.

The subsystem is deliberately lazy and disabled by default. Importing it has no
side effects: no database is opened and no directory is created until the
subsystem is enabled and actually runs a goal.

Enable it in one of three ways:

* set ``DELAMAIN_ENABLED=1`` (or ``DELAMAIN_LOCAL_ENABLED=1``) in the
  environment before starting the agent;
* set ``DELAMAIN_LOCAL_ENABLED = True`` in ``config/simulation_config.py``;
* run ``/delamain on`` in the tray chat.

The runtime works without a model. A goal is either a simple command that the
deterministic planner understands, an explicit list of action requests stored
in the goal metadata, or (optionally) a plan from a local Ollama model with a
heuristic fallback. The LLM is disabled by default by
``DELAMAIN_LLM_ENABLED``. Dangerous plans can wait for explicit approval;
the gate is disabled by default by ``DELAMAIN_APPROVAL_MODE=off``.

An optional bridge (``DELAMAIN_BRIDGE_ENABLED=1``) links the active cognitive
goal from ``GoalSubsystem`` to at most one durable Delamain goal when the
cognitive goal carries an explicit ``execution`` payload. The bridge is also
disabled by default and never guesses a command from a title.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src.core.subsystem_base import Subsystem

from .approval import VALID_APPROVAL_MODES, normalize_approval_mode
from .goal_bridge import GoalBridge, derive_bridge_status
from .llm_planner import OllamaPlanner
from .models import ActionRequest, TaskResult, utc_now_iso
from .planner import FallbackPlanner, HeuristicPlanner, Planner
from .runtime import DelamainRuntime
from .sandbox import Sandbox

try:  # The subsystem is also usable without the project config.
    from config.simulation_config import LR_CONFIG
except Exception:  # pragma: no cover - only for standalone imports
    LR_CONFIG = None  # type: ignore[assignment]


def _cfg(name: str, default: Any) -> Any:
    if LR_CONFIG is None:
        return default
    return getattr(LR_CONFIG, name, default)


def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _default_paths() -> tuple[Path, Path]:
    try:
        from src.core.paths import data_path

        return (
            Path(data_path("delamain", "workspace")),
            Path(data_path("delamain", "delamain.sqlite3")),
        )
    except Exception:  # pragma: no cover - fallback for standalone use
        return (
            Path("data") / "delamain" / "workspace",
            Path("data") / "delamain" / "delamain.sqlite3",
        )


def _short(value: Any, limit: int = 500) -> Any:
    """Keep event payloads small; the full result remains in SQLite."""

    if value is None:
        return None
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


class DelamainSubsystem(Subsystem):
    """Expose the deterministic Delamain loop as an optional subsystem."""

    name = "delamain"
    priority = 200
    version = "0.5.0"

    def __init__(
        self,
        agent_name: str = "unknown",
        *,
        workspace: Optional[str | Path] = None,
        db_path: Optional[str | Path] = None,
        enabled: Optional[bool] = None,
        tick_interval: Optional[int] = None,
        max_goals_per_tick: Optional[int] = None,
        max_attempts: Optional[int] = None,
        max_file_bytes: Optional[int] = None,
        llm_enabled: Optional[bool] = None,
        llm_base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_timeout: Optional[float] = None,
        llm_max_steps: Optional[int] = None,
        llm_temperature: Optional[float] = None,
        approval_mode: Optional[str] = None,
        bridge_enabled: Optional[bool] = None,
    ) -> None:
        super().__init__(agent_name=agent_name)

        default_workspace, default_db = _default_paths()
        workspace_value = (
            workspace
            or os.environ.get("DELAMAIN_WORKSPACE")
            or _cfg("DELAMAIN_WORKSPACE", "")
            or default_workspace
        )
        db_value = (
            db_path
            or os.environ.get("DELAMAIN_DB")
            or _cfg("DELAMAIN_DB", "")
            or default_db
        )
        self.workspace = Path(workspace_value).expanduser()
        self.db_path = Path(db_value).expanduser()

        if enabled is None:
            env_value = os.environ.get("DELAMAIN_ENABLED")
            if env_value is None:
                env_value = os.environ.get("DELAMAIN_LOCAL_ENABLED")
            if env_value is None:
                enabled = bool(_cfg("DELAMAIN_LOCAL_ENABLED", False))
            else:
                enabled = _parse_bool(env_value)
        self.enabled = bool(enabled)

        interval_value = (
            tick_interval
            if tick_interval is not None
            else os.environ.get("DELAMAIN_TICK_INTERVAL")
            or _cfg("DELAMAIN_TICK_INTERVAL", 20)
        )
        self.tick_interval = max(1, int(interval_value))

        goals_value = (
            max_goals_per_tick
            if max_goals_per_tick is not None
            else os.environ.get("DELAMAIN_MAX_GOALS_PER_TICK")
            or _cfg("DELAMAIN_MAX_GOALS_PER_TICK", 1)
        )
        self.max_goals_per_tick = max(1, int(goals_value))

        attempts_value = (
            max_attempts
            if max_attempts is not None
            else os.environ.get("DELAMAIN_MAX_ATTEMPTS")
            or _cfg("DELAMAIN_MAX_ATTEMPTS", 1)
        )
        # The default is intentionally 1: stage 8 behaviour (one failure ->
        # failed) is preserved unless the user opts into retries.
        self.max_attempts = max(1, int(attempts_value))

        if llm_enabled is None:
            llm_env = os.environ.get("DELAMAIN_LLM_ENABLED")
            if llm_env is None:
                llm_enabled = bool(_cfg("DELAMAIN_LLM_ENABLED", False))
            else:
                llm_enabled = _parse_bool(llm_env)
        self.llm_enabled = bool(llm_enabled)
        self.llm_base_url = str(
            llm_base_url
            or os.environ.get("DELAMAIN_LLM_BASE_URL")
            or _cfg("DELAMAIN_LLM_BASE_URL", "http://127.0.0.1:11434")
        ).strip()
        self.llm_model = str(
            llm_model
            or os.environ.get("DELAMAIN_LLM_MODEL")
            or _cfg("DELAMAIN_LLM_MODEL", "qwen2.5:7b-instruct")
        ).strip()
        timeout_value = (
            llm_timeout
            if llm_timeout is not None
            else os.environ.get("DELAMAIN_LLM_TIMEOUT")
            or _cfg("DELAMAIN_LLM_TIMEOUT", 20.0)
        )
        self.llm_timeout = max(1.0, float(timeout_value))
        steps_value = (
            llm_max_steps
            if llm_max_steps is not None
            else os.environ.get("DELAMAIN_LLM_MAX_STEPS")
            or _cfg("DELAMAIN_LLM_MAX_STEPS", 12)
        )
        self.llm_max_steps = max(1, int(steps_value))
        temperature_value = (
            llm_temperature
            if llm_temperature is not None
            else os.environ.get("DELAMAIN_LLM_TEMPERATURE")
            or _cfg("DELAMAIN_LLM_TEMPERATURE", 0.0)
        )
        self.llm_temperature = max(0.0, min(2.0, float(temperature_value)))

        raw_approval_mode = (
            approval_mode
            if approval_mode is not None
            else os.environ.get("DELAMAIN_APPROVAL_MODE")
            or _cfg("DELAMAIN_APPROVAL_MODE", "off")
        )
        # A typo in an explicit mode must fail closed: keep writes gated
        # instead of falling back to the permissive stage-10 behaviour.
        self.approval_mode, self._approval_mode_error = normalize_approval_mode(
            raw_approval_mode,
            fallback="dangerous",
        )

        if bridge_enabled is None:
            bridge_env = os.environ.get("DELAMAIN_BRIDGE_ENABLED")
            if bridge_env is None:
                bridge_enabled = bool(_cfg("DELAMAIN_BRIDGE_ENABLED", False))
            else:
                bridge_enabled = _parse_bool(bridge_env)
        self.bridge_enabled = bool(bridge_enabled)
        self.bridge = GoalBridge(self)

        bytes_value = (
            max_file_bytes
            if max_file_bytes is not None
            else os.environ.get("DELAMAIN_MAX_FILE_BYTES")
            or _cfg("DELAMAIN_MAX_FILE_BYTES", 1_000_000)
        )
        self.max_file_bytes = max(1, int(bytes_value))

        self.runtime: Optional[DelamainRuntime] = None
        self._agent: Any = None
        self._last_result: Optional[Dict[str, Any]] = None
        self._last_tick_cycle: Optional[int] = None
        self._planner_mode = "heuristic"
        self._planner_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self, context: Dict[str, Any]) -> None:
        super().setup(context)
        self._agent = (context or {}).get("agent")
        if self.enabled:
            try:
                self._ensure_runtime()
            except Exception as exc:
                # Do not break agent startup because an optional layer failed.
                self._record_error(exc)

    def teardown(self) -> None:
        if self.runtime is not None:
            try:
                self.runtime.close()
            except Exception as exc:
                self._record_error(exc)
            finally:
                self.runtime = None
        super().teardown()

    def set_enabled(self, enabled: bool) -> None:
        super().set_enabled(enabled)
        if self.enabled:
            self._ensure_runtime()

    def enable(self) -> Dict[str, Any]:
        """Enable the subsystem and create the runtime if needed."""

        try:
            self.set_enabled(True)
            self._ensure_runtime()
            return {"ok": True, "enabled": True, "error": None}
        except Exception as exc:
            self._record_error(exc)
            self.enabled = False
            return {"ok": False, "enabled": False, "error": str(exc)}

    def disable(self) -> Dict[str, Any]:
        """Stop autonomous goal execution without closing the runtime."""

        self.set_enabled(False)
        return {"ok": True, "enabled": False, "error": None}

    # ------------------------------------------------------------------
    # Runtime and goals
    # ------------------------------------------------------------------

    def _build_planner(self) -> Optional[Planner]:
        """Build the optional planner stack without touching the network."""

        self._planner_error = None
        if not self.llm_enabled:
            self._planner_mode = "heuristic"
            return None
        try:
            primary = OllamaPlanner(
                base_url=self.llm_base_url,
                model=self.llm_model,
                timeout=self.llm_timeout,
                max_steps=self.llm_max_steps,
                temperature=self.llm_temperature,
            )
            self._planner_mode = f"ollama:{self.llm_model}+fallback"
            return FallbackPlanner(primary, HeuristicPlanner())
        except Exception as exc:
            # A bad model name or URL must not prevent the agent from
            # starting. The deterministic planner remains available.
            self._planner_error = f"{type(exc).__name__}: {exc}"
            self._planner_mode = "heuristic (LLM setup failed)"
            return None

    def _ensure_runtime(self) -> DelamainRuntime:
        if self.runtime is None:
            self.workspace.mkdir(parents=True, exist_ok=True)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            sandbox = Sandbox(self.workspace, max_file_bytes=self.max_file_bytes)
            self.runtime = DelamainRuntime(
                self.workspace,
                self.db_path,
                sandbox=sandbox,
                planner=self._build_planner(),
                approval_mode=self.approval_mode,
            )
        return self.runtime

    def queue_goal(
        self,
        title: str,
        command: Optional[str] = None,
        *,
        plan: Optional[List[ActionRequest | Mapping[str, Any] | str]] = None,
        priority: float = 0.5,
        success_predicate: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a durable execution goal.

        At least one of ``command`` or ``plan`` is required; a goal without an
        executable representation would only sit in the table forever.
        ``metadata`` is merged into the stored goal metadata and is used by
        the optional cognitive-goal bridge.
        """

        title = str(title).strip()
        if not title:
            raise ValueError("goal title must not be empty")
        command = None if command is None else str(command).strip()
        if not command and not plan:
            raise ValueError("goal needs a command or an explicit plan")

        goal_metadata: Dict[str, Any] = dict(metadata or {})
        if command:
            goal_metadata["command"] = command
        if plan:
            goal_metadata["plan"] = self._normalize_plan(plan)

        runtime = self._ensure_runtime()
        goal_id = runtime.memory.save_goal(
            title,
            status="pending",
            success_predicate=success_predicate,
            priority=priority,
            metadata=goal_metadata,
        )
        return {
            "id": goal_id,
            "title": title,
            "status": "pending",
            "priority": max(0.0, min(1.0, float(priority))),
            "metadata": goal_metadata,
        }

    def list_goals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.runtime is None:
            if not self.enabled:
                return []
            self._ensure_runtime()
        assert self.runtime is not None
        goals = self.runtime.memory.list_goals(status=status)
        memory = self.runtime.memory
        for goal in goals:
            metadata = goal.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                continue
            if metadata.get("bridge_source") != "goal_subsystem":
                continue
            goal["bridge_status"] = derive_bridge_status(goal, memory)
            goal["cognitive_goal_id"] = metadata.get("cognitive_goal_id")
            goal["cognitive_goal_title"] = metadata.get("cognitive_goal_title")
        return goals

    def get_goal(self, goal_id: int) -> Optional[Dict[str, Any]]:
        """Return one goal with the optional bridge status attached."""

        if self.runtime is None:
            if not self.enabled:
                return None
            self._ensure_runtime()
        assert self.runtime is not None
        runtime = self.runtime
        goal = runtime.memory.get_goal(int(goal_id))
        if goal is None:
            return None
        metadata = goal.get("metadata") or {}
        if isinstance(metadata, Mapping) and metadata.get("bridge_source") == "goal_subsystem":
            goal["bridge_status"] = derive_bridge_status(goal, runtime.memory)
            goal["cognitive_goal_id"] = metadata.get("cognitive_goal_id")
            goal["cognitive_goal_title"] = metadata.get("cognitive_goal_title")
        return goal

    def list_skills(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        if self.runtime is None:
            if not self.enabled:
                return []
            self._ensure_runtime()
        assert self.runtime is not None
        return self.runtime.memory.list_skills(limit=limit)

    def list_approvals(
        self,
        status: Optional[str] = "pending",
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        if self.runtime is None:
            if not self.enabled:
                return []
            self._ensure_runtime()
        assert self.runtime is not None
        return self.runtime.memory.list_approvals(status=status, limit=limit)

    def approve(self, approval_id: str) -> Dict[str, Any]:
        """Approve and execute a stored plan exactly once."""

        approval_id = str(approval_id or "").strip()
        if not approval_id:
            return {"ok": False, "error": "approval id is empty", "trigger": "approval"}
        runtime = self._ensure_runtime()
        approval = runtime.memory.get_approval(approval_id)
        if approval is None:
            return {
                "ok": False,
                "error": f"approval not found: {approval_id}",
                "trigger": "approval",
            }
        if approval.get("status") == "pending":
            approval = runtime.memory.approve_approval(approval_id)
            if approval is None:
                current = runtime.memory.get_approval(approval_id)
                state = current.get("status") if current else "missing"
                return {
                    "ok": False,
                    "error": f"approval {approval_id} is not pending (status={state})",
                    "trigger": "approval",
                }
        elif approval.get("status") != "approved":
            return {
                "ok": False,
                "error": (
                    f"approval {approval_id} is {approval.get('status')}; "
                    "only pending or approved approvals can run"
                ),
                "trigger": "approval",
            }

        result = runtime.run_approved(approval_id)
        goal_id = approval.get("goal_id")
        goal = runtime.memory.get_goal(int(goal_id)) if goal_id is not None else None
        if goal is not None:
            metadata = goal.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            previous_attempts = self._attempts(metadata)
            summary = self._finish_goal(
                runtime,
                goal,
                result,
                trigger="approval",
                previous_attempts=previous_attempts,
                reused_skill=False,
            )
        else:
            summary = self._summarize(
                result,
                trigger="approval",
                goal_id=goal_id,
                title=approval.get("title") or None,
            )
        self._last_result = summary
        self._sync_bridge()
        return summary

    def reject(self, approval_id: str, reason: str = "") -> Dict[str, Any]:
        """Reject a pending approval and fail its linked goal, if any."""

        approval_id = str(approval_id or "").strip()
        if not approval_id:
            return {"ok": False, "error": "approval id is empty", "trigger": "approval"}
        runtime = self._ensure_runtime()
        approval = runtime.memory.get_approval(approval_id)
        if approval is None:
            return {
                "ok": False,
                "error": f"approval not found: {approval_id}",
                "trigger": "approval",
            }
        if approval.get("status") not in {"pending", "approved"}:
            return {
                "ok": False,
                "error": (
                    f"approval {approval_id} is {approval.get('status')}; "
                    "only pending or approved approvals can be rejected"
                ),
                "trigger": "approval",
            }

        updated = runtime.memory.reject_approval(approval_id, reason)
        if updated is None:
            return {
                "ok": False,
                "error": f"approval {approval_id} could not be rejected",
                "trigger": "approval",
            }

        goal_id = updated.get("goal_id")
        goal = runtime.memory.get_goal(int(goal_id)) if goal_id is not None else None
        attempts: Optional[int] = None
        if goal is not None:
            metadata = goal.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            attempts = self._attempts(metadata)
            new_metadata = dict(metadata)
            new_metadata.update(
                {
                    "approval_id": None,
                    "approval_status": "rejected",
                    "approval_reason": str(reason or ""),
                    "last_attempt_at": utc_now_iso(),
                    "last_error": f"approval rejected: {reason or 'no reason'}",
                    "last_ok": False,
                    "retry_scheduled": False,
                }
            )
            runtime.memory.update_goal(
                int(goal["id"]),
                status="failed",
                metadata=new_metadata,
            )

        summary = {
            "task_id": updated.get("task_id"),
            "task": _short(updated.get("task")),
            "ok": False,
            "steps": 0,
            "final_output": None,
            "error": f"approval rejected: {reason or 'no reason'}",
            "trigger": "approval-reject",
            "goal_id": goal_id,
            "title": updated.get("title") or None,
            "attempts": attempts,
            "retry_scheduled": False,
            "reused_skill": False,
            "approval_id": approval_id,
            "approval_status": "rejected",
            "pending_approval": None,
        }
        self._last_result = summary
        self._sync_bridge()
        return summary

    def run_now(
        self,
        task: str,
        *,
        plan: Optional[List[ActionRequest | Mapping[str, Any] | str]] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a task immediately, outside the goal table."""

        runtime = self._ensure_runtime()
        result = runtime.run_task(task, plan=plan, task_id=task_id)
        summary = self._summarize(result, trigger="manual")
        self._last_result = summary
        return summary

    def run_pending_goal(self, *, trigger: str = "manual") -> Optional[Dict[str, Any]]:
        """Run at most ``max_goals_per_tick`` executable pending goals."""

        runtime = self._ensure_runtime()
        candidates = [
            goal
            for goal in runtime.memory.list_goals(status="pending")
            if (self._goal_command(goal) or self._goal_plan(goal))
            and not self._goal_waiting_for_approval(runtime, goal)
        ]
        if not candidates:
            return None

        last: Optional[Dict[str, Any]] = None
        for goal in candidates[: self.max_goals_per_tick]:
            last = self._run_goal(runtime, goal, trigger=trigger)
        return last

    def _run_goal(
        self,
        runtime: DelamainRuntime,
        goal: Dict[str, Any],
        *,
        trigger: str,
    ) -> Dict[str, Any]:
        goal_id = int(goal["id"])
        title = str(goal.get("title") or f"goal-{goal_id}")
        command = self._goal_command(goal)
        explicit_plan = self._goal_plan(goal)
        task = command or title

        metadata = goal.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        previous_attempts = self._attempts(metadata)

        # A goal with a pending approval must not create another approval on
        # every tick. An approved approval is executed here; this also covers
        # a process restart after the user pressed approve.
        approval_id = metadata.get("approval_id")
        if approval_id:
            approval = runtime.memory.get_approval(str(approval_id))
            if approval is not None:
                state = str(approval.get("status") or "")
                if state == "pending":
                    result = TaskResult(
                        task_id=str(approval.get("task_id") or f"goal-{goal_id}"),
                        task=task,
                        ok=False,
                        error="approval required: " + ", ".join(
                            approval.get("dangerous_actions") or ["all actions"]
                        ),
                        planned_actions=list(approval.get("plan") or []),
                        pending_approval=approval,
                    )
                    summary = self._summarize(
                        result,
                        trigger=trigger,
                        goal_id=goal_id,
                        title=title,
                        attempts=previous_attempts,
                        retry_scheduled=False,
                        reused_skill=False,
                    )
                    self._last_result = summary
                    return summary
                if state == "approved":
                    result = runtime.run_approved(str(approval_id))
                    return self._finish_goal(
                        runtime,
                        goal,
                        result,
                        trigger=trigger,
                        previous_attempts=previous_attempts,
                        reused_skill=False,
                    )
                if state == "rejected":
                    new_metadata = dict(metadata)
                    new_metadata.update(
                        {
                            "approval_id": None,
                            "approval_status": "rejected",
                            "last_attempt_at": utc_now_iso(),
                            "last_error": "approval rejected",
                            "last_ok": False,
                            "retry_scheduled": False,
                        }
                    )
                    runtime.memory.update_goal(
                        goal_id,
                        status="failed",
                        metadata=new_metadata,
                    )
                    summary = {
                        "task_id": f"goal-{goal_id}",
                        "task": _short(task),
                        "ok": False,
                        "steps": 0,
                        "final_output": None,
                        "error": "approval rejected",
                        "trigger": trigger,
                        "goal_id": goal_id,
                        "title": title,
                        "attempts": previous_attempts,
                        "retry_scheduled": False,
                        "reused_skill": False,
                        "approval_id": str(approval_id),
                        "approval_status": "rejected",
                        "pending_approval": None,
                    }
                    self._last_result = summary
                    return summary

        plan = explicit_plan
        reused_skill = False
        if plan is None:
            plan = self._skill_plan_for(runtime, title, command)
            reused_skill = plan is not None

        # Keep the stage-8 task id for the first attempt; retries get a
        # suffix so their episodes remain distinguishable.
        attempt_number = previous_attempts + 1
        task_id = f"goal-{goal_id}"
        if attempt_number > 1:
            task_id += f"-attempt-{attempt_number}"
        result = runtime.run_task(task, plan=plan, task_id=task_id)

        if result.pending_approval:
            approval = result.pending_approval
            approval_id = str(approval.get("id"))
            runtime.memory.update_approval(
                approval_id,
                goal_id=goal_id,
                title=title,
                metadata={"source": "goal"},
            )
            new_metadata = dict(metadata)
            new_metadata.update(
                {
                    "approval_id": approval_id,
                    "approval_status": "pending",
                    "approval_requested_at": utc_now_iso(),
                    "last_attempt_at": utc_now_iso(),
                    "last_error": result.error,
                    "last_ok": False,
                    "retry_scheduled": False,
                }
            )
            runtime.memory.update_goal(
                goal_id,
                status="pending",
                metadata=new_metadata,
            )
            summary = self._summarize(
                result,
                trigger=trigger,
                goal_id=goal_id,
                title=title,
                attempts=previous_attempts,
                retry_scheduled=False,
                reused_skill=reused_skill,
            )
            self._last_result = summary
            return summary

        return self._finish_goal(
            runtime,
            goal,
            result,
            trigger=trigger,
            previous_attempts=previous_attempts,
            reused_skill=reused_skill,
        )

    def _finish_goal(
        self,
        runtime: DelamainRuntime,
        goal: Dict[str, Any],
        result: TaskResult,
        *,
        trigger: str,
        previous_attempts: int,
        reused_skill: bool,
    ) -> Dict[str, Any]:
        goal_id = int(goal["id"])
        title = str(goal.get("title") or f"goal-{goal_id}")
        command = self._goal_command(goal)
        attempt_number = max(0, previous_attempts) + 1

        if result.ok:
            status = "done"
            retry_scheduled = False
            # Store the actual normalized plan, not the command text. This is
            # what makes a later identical goal executable without a planner.
            runtime.memory.record_skill(
                title,
                {
                    "version": 1,
                    "command": command,
                    "steps": list(result.planned_actions),
                },
                success=True,
            )
        else:
            retry_scheduled = attempt_number < self.max_attempts
            status = "pending" if retry_scheduled else "failed"
            # Preserve the last known good plan and only count the failure.
            runtime.memory.record_skill(title, None, success=False)

        metadata = goal.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        new_metadata = dict(metadata)
        new_metadata.update(
            {
                "attempts": attempt_number,
                "last_attempt_at": utc_now_iso(),
                "last_error": result.error,
                "last_ok": bool(result.ok),
                "retry_scheduled": retry_scheduled,
            }
        )
        prior_approval_id = new_metadata.get("approval_id")
        if result.approval_id or prior_approval_id:
            new_metadata["last_approval_id"] = result.approval_id or prior_approval_id
            new_metadata["approval_id"] = None
            new_metadata["approval_status"] = (
                "consumed" if result.approval_id else "failed"
            )
        runtime.memory.update_goal(
            goal_id,
            status=status,
            metadata=new_metadata,
        )

        summary = self._summarize(
            result,
            trigger=trigger,
            goal_id=goal_id,
            title=title,
            attempts=attempt_number,
            retry_scheduled=retry_scheduled,
            reused_skill=reused_skill,
        )
        self._last_result = summary
        return summary

    @staticmethod
    def _attempts(metadata: Mapping[str, Any]) -> int:
        try:
            return max(0, int(metadata.get("attempts") or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _goal_waiting_for_approval(
        runtime: DelamainRuntime,
        goal: Mapping[str, Any],
    ) -> bool:
        metadata = goal.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            return False
        approval_id = metadata.get("approval_id")
        if not approval_id:
            return False
        approval = runtime.memory.get_approval(str(approval_id))
        return approval is not None and approval.get("status") == "pending"

    @staticmethod
    def _skill_plan_for(
        runtime: DelamainRuntime,
        title: str,
        command: Optional[str],
    ) -> Optional[List[Any]]:
        """Return a stored plan only when it matches the same command.

        Skills are keyed by title, but a title alone is not enough to justify
        replaying a plan: the command must match exactly. A plan must have at
        least one success and must not have more failures than successes.
        Legacy stage-8 skills store a command string or a raw list, so they
        are simply not reused.
        """

        skill = runtime.memory.get_skill(title)
        if skill is None:
            return None
        try:
            successes = int(skill.get("success_count") or 0)
            failures = int(skill.get("failure_count") or 0)
        except (TypeError, ValueError):
            return None
        # Require at least one success, and do not keep replaying a plan that
        # is failing more often than it works. Equal counts are allowed so a
        # goal that failed once and then succeeded on retry can still be
        # reused; one more failure will make it ineligible.
        if successes == 0 or successes < failures:
            return None

        payload = skill.get("plan")
        if not isinstance(payload, Mapping):
            return None
        if payload.get("version") != 1:
            return None
        if payload.get("command") != command:
            return None
        steps = payload.get("steps")
        if not isinstance(steps, (list, tuple)) or not steps:
            return None
        return list(steps)

    @staticmethod
    def _normalize_plan(
        plan: List[ActionRequest | Mapping[str, Any] | str],
    ) -> List[Any]:
        """Make plans JSON-safe before putting them into SQLite metadata."""

        normalized: List[Any] = []
        for step in plan:
            if isinstance(step, ActionRequest):
                normalized.append(step.to_dict())
            elif isinstance(step, Mapping):
                normalized.append(dict(step))
            else:
                normalized.append(step)
        return normalized

    @staticmethod
    def _goal_command(goal: Mapping[str, Any]) -> Optional[str]:
        metadata = goal.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            return None
        value = metadata.get("command") or metadata.get("task")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _goal_plan(goal: Mapping[str, Any]) -> Optional[List[Any]]:
        metadata = goal.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            return None
        value = metadata.get("plan")
        if isinstance(value, (list, tuple)) and value:
            return list(value)
        return None

    @staticmethod
    def _summarize(
        result: TaskResult,
        *,
        trigger: str,
        goal_id: Optional[int] = None,
        title: Optional[str] = None,
        attempts: Optional[int] = None,
        retry_scheduled: bool = False,
        reused_skill: bool = False,
    ) -> Dict[str, Any]:
        pending = result.pending_approval
        pending_summary = None
        if pending is not None:
            pending_summary = {
                "id": pending.get("id"),
                "task_id": pending.get("task_id"),
                "title": pending.get("title"),
                "task": _short(pending.get("task")),
                "status": pending.get("status"),
                "dangerous_actions": list(pending.get("dangerous_actions") or []),
                "plan": list(pending.get("plan") or []),
            }
        return {
            "task_id": result.task_id,
            "task": _short(result.task),
            "ok": bool(result.ok),
            "steps": len(result.steps),
            "final_output": _short(result.final_output),
            "error": _short(result.error),
            "trigger": str(trigger),
            "goal_id": goal_id,
            "title": title,
            "attempts": attempts,
            "retry_scheduled": bool(retry_scheduled),
            "reused_skill": bool(reused_skill),
            "approval_id": result.approval_id
            or (pending_summary.get("id") if pending_summary else None),
            "approval_status": (
                "consumed"
                if result.approval_id
                else ("pending" if pending_summary else None)
            ),
            "pending_approval": pending_summary,
        }

    # ------------------------------------------------------------------
    # Tick and introspection
    # ------------------------------------------------------------------

    def tick(
        self,
        cycle: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        super().tick(cycle, context)
        if not self.enabled:
            return None

        # The registry normally ticks once per cycle, but this guard makes
        # duplicate calls from a dashboard harmless.
        if self._last_tick_cycle == cycle:
            return None
        self._last_tick_cycle = cycle

        agent = (context or {}).get("agent") or self._agent
        bridge_events = self._sync_bridge(agent)

        if self.tick_interval > 1 and int(cycle) % self.tick_interval != 0:
            return {"events": bridge_events} if bridge_events else None

        try:
            summary = self.run_pending_goal(trigger="tick")
        except Exception as exc:
            # A broken optional layer must not break the agent loop.
            self._record_error(exc)
            return {"events": bridge_events} if bridge_events else None

        # Reconcile after execution: this is where a successful goal completes
        # its cognitive counterpart and a failed/rejected one closes it.
        bridge_events.extend(self._sync_bridge(agent))

        events = list(bridge_events)
        if summary is not None:
            events.append({"name": "delamain_goal", "data": summary})
        return {"events": events} if events else None

    def _sync_bridge(self, agent: Any = None) -> List[Dict[str, Any]]:
        """Run the optional cognitive-goal bridge; never break the tick."""

        if not self.bridge_enabled:
            return []
        try:
            return self.bridge.sync(agent or self._agent)
        except Exception as exc:  # pragma: no cover - defensive
            self._record_error(exc)
            return []

    def _planner_info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "enabled": self.llm_enabled,
            "mode": self._planner_mode,
            "base_url": self.llm_base_url,
            "model": self.llm_model,
            "timeout": self.llm_timeout,
            "max_steps": self.llm_max_steps,
            "error": self._planner_error,
            "last_used": None,
            "last_error": None,
        }
        if self.runtime is not None:
            status = getattr(self.runtime.planner, "status", None)
            if callable(status):
                try:
                    extra = status()
                except Exception as exc:  # pragma: no cover - defensive
                    info["status_error"] = f"{type(exc).__name__}: {exc}"
                else:
                    if isinstance(extra, Mapping):
                        info.update(dict(extra))
        return info

    def status(self) -> Dict[str, Any]:
        base = super().status()
        counts = {"pending": 0, "done": 0, "failed": 0}
        if self.runtime is not None:
            try:
                goals = self.runtime.memory.list_goals()
                for goal in goals:
                    goal_status = str(goal.get("status") or "")
                    if goal_status in counts:
                        counts[goal_status] += 1
            except Exception as exc:  # pragma: no cover - defensive
                base["goal_count_error"] = str(exc)

        skill_count = 0
        if self.runtime is not None:
            try:
                skill_count = len(self.runtime.memory.list_skills(limit=1000))
            except Exception as exc:  # pragma: no cover - defensive
                base["skill_count_error"] = str(exc)

        approval_counts = {
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "consumed": 0,
        }
        if self.runtime is not None:
            try:
                for state in approval_counts:
                    approval_counts[state] = self.runtime.memory.count_approvals(
                        status=state
                    )
            except Exception as exc:  # pragma: no cover - defensive
                base["approval_count_error"] = str(exc)

        base.update(
            {
                "workspace": str(self.workspace),
                "db_path": str(self.db_path),
                "runtime_ready": self.runtime is not None,
                "tick_interval": self.tick_interval,
                "max_goals_per_tick": self.max_goals_per_tick,
                "max_attempts": self.max_attempts,
                "goals": counts,
                "skills": skill_count,
                "approval": {
                    "mode": self.approval_mode,
                    "valid_modes": list(VALID_APPROVAL_MODES),
                    "error": self._approval_mode_error,
                    "counts": approval_counts,
                },
                "bridge": self.bridge.status(),
                "planner": self._planner_info(),
                "last_result": self._last_result,
            }
        )
        return base


__all__ = ["DelamainSubsystem"]
