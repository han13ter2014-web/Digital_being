"""Optional integration of the Delamain-local runtime with Digital Being.

The subsystem is deliberately lazy and disabled by default. Importing it has no
side effects: no database is opened and no directory is created until the
subsystem is enabled and actually runs a goal.

Enable it in one of three ways:

* set ``DELAMAIN_ENABLED=1`` (or ``DELAMAIN_LOCAL_ENABLED=1``) in the
  environment before starting the agent;
* set ``DELAMAIN_LOCAL_ENABLED = True`` in ``config/simulation_config.py``;
* run ``/delamain on`` in the tray chat.

The runtime itself is still model-free. A goal is either a simple command that
the deterministic planner understands, or an explicit list of action requests
stored in the goal metadata.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src.core.subsystem_base import Subsystem

from .models import ActionRequest, TaskResult, utc_now_iso
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
    version = "0.3.0"

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

    def _ensure_runtime(self) -> DelamainRuntime:
        if self.runtime is None:
            self.workspace.mkdir(parents=True, exist_ok=True)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            sandbox = Sandbox(self.workspace, max_file_bytes=self.max_file_bytes)
            self.runtime = DelamainRuntime(
                self.workspace,
                self.db_path,
                sandbox=sandbox,
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
    ) -> Dict[str, Any]:
        """Create a durable execution goal.

        At least one of ``command`` or ``plan`` is required; a goal without an
        executable representation would only sit in the table forever.
        """

        title = str(title).strip()
        if not title:
            raise ValueError("goal title must not be empty")
        command = None if command is None else str(command).strip()
        if not command and not plan:
            raise ValueError("goal needs a command or an explicit plan")

        metadata: Dict[str, Any] = {}
        if command:
            metadata["command"] = command
        if plan:
            metadata["plan"] = self._normalize_plan(plan)

        runtime = self._ensure_runtime()
        goal_id = runtime.memory.save_goal(
            title,
            status="pending",
            success_predicate=success_predicate,
            priority=priority,
            metadata=metadata,
        )
        return {
            "id": goal_id,
            "title": title,
            "status": "pending",
            "priority": max(0.0, min(1.0, float(priority))),
            "metadata": metadata,
        }

    def list_goals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.runtime is None:
            if not self.enabled:
                return []
            self._ensure_runtime()
        assert self.runtime is not None
        return self.runtime.memory.list_goals(status=status)

    def list_skills(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        if self.runtime is None:
            if not self.enabled:
                return []
            self._ensure_runtime()
        assert self.runtime is not None
        return self.runtime.memory.list_skills(limit=limit)

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
            if self._goal_command(goal) or self._goal_plan(goal)
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
        try:
            previous_attempts = int(metadata.get("attempts") or 0)
        except (TypeError, ValueError):
            previous_attempts = 0
        attempt_number = max(0, previous_attempts) + 1

        plan = explicit_plan
        reused_skill = False
        if plan is None:
            plan = self._skill_plan_for(runtime, title, command)
            reused_skill = plan is not None

        # Keep the stage-8 task id for the first attempt; retries get a
        # suffix so their episodes remain distinguishable.
        task_id = f"goal-{goal_id}"
        if attempt_number > 1:
            task_id += f"-attempt-{attempt_number}"
        result = runtime.run_task(task, plan=plan, task_id=task_id)

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

        if self.tick_interval > 1 and int(cycle) % self.tick_interval != 0:
            return None

        try:
            summary = self.run_pending_goal(trigger="tick")
        except Exception as exc:
            # A broken optional layer must not break the agent loop.
            self._record_error(exc)
            return None

        if summary is None:
            return None
        return {"events": [{"name": "delamain_goal", "data": summary}]}

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
                "last_result": self._last_result,
            }
        )
        return base


__all__ = ["DelamainSubsystem"]
