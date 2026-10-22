"""Optional bridge between cognitive goals and executable Delamain goals.

``GoalSubsystem`` owns high-level goals such as "learn Python" or "write a
report".  Those goals are not executable by themselves.  This module links an
*active* cognitive goal to **at most one** durable Delamain goal when the
cognitive goal carries an explicit executable payload::

    goal["execution"] = {
        "command": "write notes/report.txt: ready",
        "success_predicate": "file_contains:notes/report.txt:ready",
    }

The bridge is deliberately conservative:

* it never guesses a command from a natural-language title;
* it is disabled by default (``DELAMAIN_BRIDGE_ENABLED``);
* it scans SQLite before queueing, so a lost in-memory link does not create a
  duplicate executable goal;
* a pending approval is reported as ``waiting_approval``, not as a failure;
* a rejected/failed goal fails the cognitive goal, but a rejected plan never
  touches Delamain skill counters;
* the success predicate is evaluated only after execution, using a small
  deterministic vocabulary (``ok``, ``file_exists:...``,
  ``file_contains:path:text``), not ``eval``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .models import utc_now_iso


BRIDGE_STATUSES = (
    "pending",
    "in_progress",
    "waiting_approval",
    "done",
    "failed",
)


def _metadata(goal: Mapping[str, Any]) -> Dict[str, Any]:
    value = goal.get("metadata")
    return dict(value) if isinstance(value, Mapping) else {}


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def derive_bridge_status(
    goal: Mapping[str, Any],
    memory: Any = None,
) -> str:
    """Map a Delamain goal row to the bridge status vocabulary.

    Delamain stores only ``pending``/``done``/``failed``.  The bridge adds
    ``in_progress`` (a retry has been attempted) and ``waiting_approval``
    (an approval row is still pending).
    """

    status = str(goal.get("status") or "pending")
    metadata = _metadata(goal)
    stored_status = str(metadata.get("bridge_status") or "")

    if status == "failed":
        return "failed"
    if status == "done":
        # A completed action can still fail its postcondition.  The bridge
        # persists that distinction in metadata.
        return "failed" if stored_status == "failed" else "done"

    approval_id = metadata.get("approval_id")
    if approval_id and memory is not None:
        try:
            approval = memory.get_approval(str(approval_id))
        except Exception:
            approval = None
        if approval is not None:
            approval_status = str(approval.get("status") or "")
            if approval_status == "pending":
                return "waiting_approval"
            if approval_status == "approved":
                return "in_progress"

    approval_status = str(metadata.get("approval_status") or "")
    if approval_status == "pending":
        return "waiting_approval"
    if approval_status == "approved":
        return "in_progress"

    attempts = _as_int(metadata.get("attempts"), 0) or 0
    if attempts > 0 or metadata.get("last_attempt_at"):
        return "in_progress"
    return "pending"


def bridge_summary(
    goals: Sequence[Mapping[str, Any]],
    memory: Any = None,
) -> Dict[str, Any]:
    """Count linked goals by bridge status."""

    counts = {status: 0 for status in BRIDGE_STATUSES}
    linked = 0
    for goal in goals:
        metadata = _metadata(goal)
        if metadata.get("bridge_source") != "goal_subsystem":
            continue
        linked += 1
        counts[derive_bridge_status(goal, memory)] += 1
    return {"linked": linked, "counts": counts}


def evaluate_success_predicate(
    predicate: str,
    *,
    sandbox: Any = None,
    result_ok: bool = True,
) -> Tuple[bool, str]:
    """Evaluate a safe, explicit success predicate.

    Supported forms:

    * empty / ``ok`` / ``execution_ok`` — the Delamain task succeeded;
    * ``file_exists:<relative path>``;
    * ``file_contains:<relative path>:<text>``.

    Unknown predicates fail closed with a human-readable reason.  There is no
    arbitrary code execution.
    """

    raw = str(predicate or "").strip()
    if not raw or raw.lower() in {"ok", "execution_ok", "result_ok", "done"}:
        if result_ok:
            return True, "execution ok"
        return False, "execution failed"

    lowered = raw.lower()
    if lowered.startswith("file_exists:"):
        path = raw.split(":", 1)[1].strip()
        if not path:
            return False, "success predicate has an empty file path"
        if sandbox is None:
            return False, "success predicate requires the Delamain sandbox"
        try:
            exists = bool(sandbox.exists(path))
        except Exception as exc:
            return False, f"success predicate path error: {type(exc).__name__}: {exc}"
        if exists:
            return True, f"file exists: {path}"
        return False, f"success predicate not met: file not found: {path}"

    if lowered.startswith("file_contains:"):
        payload = raw.split(":", 1)[1]
        path, sep, needle = payload.partition(":")
        path = path.strip()
        if not sep or not path or not needle:
            return (
                False,
                "file_contains predicate expects: file_contains:<path>:<text>",
            )
        if sandbox is None:
            return False, "success predicate requires the Delamain sandbox"
        try:
            if not sandbox.exists(path):
                return (
                    False,
                    f"success predicate not met: file not found: {path}",
                )
            content = sandbox.read_text(path)
        except Exception as exc:
            return False, f"success predicate read error: {type(exc).__name__}: {exc}"
        if needle in content:
            return True, f"file contains {needle!r}: {path}"
        return (
            False,
            f"success predicate not met: {path} does not contain {needle!r}",
        )

    return False, f"unsupported success predicate: {raw}"


class GoalBridge:
    """Synchronize the active cognitive goal with the Delamain queue."""

    def __init__(self, subsystem: Any) -> None:
        self.subsystem = subsystem
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.subsystem, "bridge_enabled", False))

    def status(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "enabled": self.enabled,
            "last_error": self._last_error,
            "linked": 0,
            "counts": {status: 0 for status in BRIDGE_STATUSES},
        }
        if not self.enabled:
            return summary
        try:
            goals = self.subsystem.list_goals()
        except Exception as exc:  # pragma: no cover - defensive
            self._last_error = f"{type(exc).__name__}: {exc}"
            summary["last_error"] = self._last_error
            return summary
        memory = None
        runtime = getattr(self.subsystem, "runtime", None)
        if runtime is not None:
            memory = getattr(runtime, "memory", None)
        summary.update(bridge_summary(goals, memory))
        return summary

    # ------------------------------------------------------------------
    # Synchronization
    # ------------------------------------------------------------------

    def sync(self, agent: Any = None) -> List[Dict[str, Any]]:
        """Reconcile links and queue the active executable cognitive goal.

        Returns a list of event dicts in the same shape used by subsystem
        ticks: ``{"name": "delamain_bridge", "data": {...}}``.
        """

        if not self.enabled:
            return []

        agent = agent if agent is not None else getattr(self.subsystem, "_agent", None)
        goal_subsystem = getattr(agent, "goal_subsystem", None)
        if goal_subsystem is None:
            return []

        try:
            runtime = self.subsystem._ensure_runtime()
            executable_goals = runtime.memory.list_goals()
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return []

        events: List[Dict[str, Any]] = []
        events.extend(
            self._reconcile_all(
                agent,
                goal_subsystem,
                executable_goals,
            )
        )

        active = getattr(goal_subsystem, "active_goal", None)
        if active is None and agent is not None:
            active = getattr(agent, "active_goal", None)
        if isinstance(active, Mapping) and active.get("status") == "active":
            events.extend(
                self._ensure_link(
                    agent,
                    goal_subsystem,
                    active,
                    executable_goals,
                )
            )
        return events

    def _reconcile_all(
        self,
        agent: Any,
        goal_subsystem: Any,
        executable_goals: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        memory = getattr(getattr(self.subsystem, "runtime", None), "memory", None)
        sandbox = getattr(getattr(self.subsystem, "runtime", None), "sandbox", None)
        agent_name = self._agent_name(agent, goal_subsystem)

        for goal in list(getattr(goal_subsystem, "goals", []) or []):
            link = goal.get("delamain_bridge")
            linked_id = _as_int(goal.get("delamain_goal_id"))
            if not linked_id and not isinstance(link, Mapping):
                continue

            executable = self._find_existing(
                goal,
                executable_goals,
                agent_name,
            )
            if executable is None:
                event = self._apply_link(
                    agent,
                    goal_subsystem,
                    goal,
                    None,
                    "failed",
                    memory=memory,
                    sandbox=sandbox,
                    message="executable Delamain goal not found",
                )
            else:
                status = derive_bridge_status(executable, memory)
                event = self._apply_link(
                    agent,
                    goal_subsystem,
                    goal,
                    executable,
                    status,
                    memory=memory,
                    sandbox=sandbox,
                )
            if event is not None:
                events.append(event)
        return events

    def _ensure_link(
        self,
        agent: Any,
        goal_subsystem: Any,
        goal: Dict[str, Any],
        executable_goals: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        payload = self._execution_payload(goal)
        if payload is None:
            return []

        agent_name = self._agent_name(agent, goal_subsystem)
        executable = self._find_existing(goal, executable_goals, agent_name)
        action = "attached"
        if executable is None:
            command = payload.get("command")
            plan = payload.get("plan")
            predicate = str(
                payload.get("success_predicate")
                or goal.get("success_predicate")
                or ""
            )
            metadata = {
                "bridge_source": "goal_subsystem",
                "bridge_version": 1,
                "cognitive_goal_id": int(goal["id"]),
                "cognitive_goal_title": str(goal.get("title") or ""),
                "cognitive_agent": agent_name,
                "cognitive_drive": goal.get("drive"),
                "cognitive_difficulty": goal.get("difficulty"),
                "bridge_created_at": utc_now_iso(),
            }
            try:
                queued = self.subsystem.queue_goal(
                    str(goal.get("title") or f"goal-{goal['id']}"),
                    command,
                    plan=plan,
                    priority=self._priority(goal),
                    success_predicate=predicate,
                    metadata=metadata,
                )
                runtime = self.subsystem._ensure_runtime()
                executable = runtime.memory.get_goal(int(queued["id"]))
                if executable is None:
                    executable = {
                        "id": int(queued["id"]),
                        "title": queued.get("title"),
                        "status": "pending",
                        "success_predicate": predicate,
                        "metadata": metadata,
                    }
                executable_goals.append(executable)
                action = "linked"
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                return []

        memory = getattr(getattr(self.subsystem, "runtime", None), "memory", None)
        sandbox = getattr(getattr(self.subsystem, "runtime", None), "sandbox", None)
        status = derive_bridge_status(executable, memory)
        event = self._apply_link(
            agent,
            goal_subsystem,
            goal,
            executable,
            status,
            memory=memory,
            sandbox=sandbox,
        )
        if event is not None:
            event["data"]["action"] = action
            return [event]
        return []

    # ------------------------------------------------------------------
    # Link bookkeeping
    # ------------------------------------------------------------------

    def _apply_link(
        self,
        agent: Any,
        goal_subsystem: Any,
        goal: Dict[str, Any],
        executable: Optional[Mapping[str, Any]],
        status: str,
        *,
        memory: Any,
        sandbox: Any,
        message: str = "",
    ) -> Optional[Dict[str, Any]]:
        previous = goal.get("delamain_bridge")
        previous = dict(previous) if isinstance(previous, Mapping) else {}
        previous_status = str(previous.get("status") or "")

        metadata = _metadata(executable) if executable is not None else {}
        predicate = (
            str(executable.get("success_predicate") or "")
            if executable is not None
            else str(previous.get("success_predicate") or "")
        )
        predicate_checked = bool(previous.get("predicate_checked"))
        predicate_ok = previous.get("predicate_ok")
        predicate_reason = str(previous.get("predicate_reason") or "")

        # Evaluate the predicate only once, when the executable goal first
        # reports success.  A later file change must not retroactively alter
        # an already recorded result.
        if status == "done" and not predicate_checked:
            predicate_ok, predicate_reason = evaluate_success_predicate(
                predicate,
                sandbox=sandbox,
                result_ok=True,
            )
            predicate_checked = True
            if not predicate_ok:
                status = "failed"
                message = predicate_reason

        if not message:
            if status == "waiting_approval":
                message = self._approval_message(metadata, memory)
            elif status == "failed":
                message = self._failure_message(metadata, previous)
            elif status == "done":
                message = predicate_reason or "execution ok"
            elif status == "in_progress":
                message = "execution started"

        approval_id = metadata.get("approval_id")
        attempts = _as_int(metadata.get("attempts"), None)
        link: Dict[str, Any] = dict(previous)
        link.update(
            {
                "status": status,
                "goal_id": (
                    _as_int(executable.get("id")) if executable is not None else None
                ),
                "approval_id": str(approval_id) if approval_id else None,
                "attempts": attempts,
                "message": message,
                "success_predicate": predicate,
                "predicate_checked": predicate_checked,
                "predicate_ok": predicate_ok,
                "predicate_reason": predicate_reason,
                "updated_at": utc_now_iso(),
            }
        )
        goal["delamain_bridge"] = link
        goal["delamain_status"] = status
        if link["goal_id"] is not None:
            goal["delamain_goal_id"] = link["goal_id"]

        self._update_progress(agent, goal_subsystem, goal, status)

        if status == "done":
            self._complete_cognitive(agent, goal_subsystem, goal)
        elif status == "failed":
            self._fail_cognitive(agent, goal_subsystem, goal, message)

        changed = (
            previous_status != status
            or str(previous.get("message") or "") != message
            or bool(previous.get("predicate_checked")) != predicate_checked
        )
        if not changed:
            return None

        self._persist_bridge_status(executable, status, message)

        return {
            "name": "delamain_bridge",
            "data": {
                "cognitive_goal_id": _as_int(goal.get("id")),
                "cognitive_goal_title": goal.get("title"),
                "delamain_goal_id": link.get("goal_id"),
                "status": status,
                "message": message,
                "approval_id": link.get("approval_id"),
                "predicate_ok": predicate_ok,
                "action": "updated",
            },
        }

    def _persist_bridge_status(
        self,
        executable: Optional[Mapping[str, Any]],
        status: str,
        message: str,
    ) -> None:
        """Store the bridge's view in the Delamain goal metadata.

        Delamain itself only has ``pending``/``done``/``failed``; the extra
        metadata keeps ``waiting_approval`` and a postcondition failure visible
        in ``/delamain goals`` and after a process restart.
        """

        if executable is None:
            return
        goal_id = _as_int(executable.get("id"))
        runtime = getattr(self.subsystem, "runtime", None)
        if goal_id is None or runtime is None:
            return
        try:
            runtime.memory.update_goal(
                goal_id,
                metadata={
                    "bridge_status": status,
                    "bridge_message": message,
                    "bridge_updated_at": utc_now_iso(),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._last_error = f"{type(exc).__name__}: {exc}"

    def _approval_message(
        self,
        metadata: Mapping[str, Any],
        memory: Any,
    ) -> str:
        approval_id = metadata.get("approval_id")
        dangerous: List[str] = []
        if approval_id and memory is not None:
            try:
                approval = memory.get_approval(str(approval_id))
            except Exception:
                approval = None
            if approval is not None:
                dangerous = [str(item) for item in approval.get("dangerous_actions") or []]
        if dangerous:
            return "approval required: " + ", ".join(dangerous)
        if approval_id:
            return f"approval required: {approval_id}"
        return "approval required"

    @staticmethod
    def _failure_message(
        metadata: Mapping[str, Any],
        previous: Mapping[str, Any],
    ) -> str:
        approval_status = str(metadata.get("approval_status") or "")
        if approval_status == "rejected":
            reason = str(metadata.get("approval_reason") or "").strip()
            return f"approval rejected: {reason}" if reason else "approval rejected"
        error = str(metadata.get("last_error") or "").strip()
        if error:
            return error
        return str(previous.get("message") or "executable goal failed")

    def _update_progress(
        self,
        agent: Any,
        goal_subsystem: Any,
        goal: Mapping[str, Any],
        status: str,
    ) -> None:
        percentages = {
            "pending": 10,
            "waiting_approval": 25,
            "in_progress": 60,
            "done": 100,
        }
        target = percentages.get(status)
        if target is None:
            return
        goal_id = _as_int(goal.get("id"))
        if goal_id is None:
            return
        progress = goal_subsystem._goal_progress.setdefault(
            goal_id,
            {
                "matched_concepts": set(),
                "percentage": 0,
                "last_update_cycle": 0,
            },
        )
        current = _as_int(progress.get("percentage"), 0) or 0
        progress["percentage"] = max(current, target)
        progress["last_update_cycle"] = int(getattr(agent, "cycle_count", 0) or 0)

    def _complete_cognitive(
        self,
        agent: Any,
        goal_subsystem: Any,
        goal: Mapping[str, Any],
    ) -> None:
        if goal.get("status") == "completed":
            return
        goal_id = _as_int(goal.get("id"))
        if goal_id is None:
            return
        complete = getattr(agent, "complete_goal", None)
        if callable(complete):
            complete(goal_id)
        else:
            goal_subsystem.complete_goal(goal_id)
        self._sync_agent_aliases(agent, goal_subsystem)

    def _fail_cognitive(
        self,
        agent: Any,
        goal_subsystem: Any,
        goal: Mapping[str, Any],
        reason: str,
    ) -> None:
        if goal.get("status") in ("completed", "failed"):
            return
        goal_id = _as_int(goal.get("id"))
        if goal_id is None:
            return
        goal_subsystem.fail_goal(goal_id, reason)
        self._sync_agent_aliases(agent, goal_subsystem)

    @staticmethod
    def _sync_agent_aliases(agent: Any, goal_subsystem: Any) -> None:
        if agent is None:
            return
        if hasattr(agent, "goals"):
            agent.goals = goal_subsystem.goals
        if hasattr(agent, "active_goal"):
            agent.active_goal = goal_subsystem.active_goal
        if hasattr(agent, "completed_goals"):
            agent.completed_goals = goal_subsystem.completed_goals
        if hasattr(agent, "_goal_progress"):
            agent._goal_progress = goal_subsystem._goal_progress

    # ------------------------------------------------------------------
    # Payload / lookup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _agent_name(agent: Any, goal_subsystem: Any) -> str:
        return str(
            getattr(agent, "name", None)
            or getattr(goal_subsystem, "agent_name", None)
            or "unknown"
        )

    @staticmethod
    def _execution_payload(goal: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        for key in ("execution", "delamain_execution", "delamain"):
            payload = GoalBridge._coerce_payload(goal.get(key))
            if payload:
                return payload

        command = goal.get("delamain_command") or goal.get("command")
        plan = goal.get("delamain_plan") or goal.get("plan")
        predicate = goal.get("success_predicate") or ""
        if command or plan:
            payload: Dict[str, Any] = {}
            if command:
                payload["command"] = str(command).strip()
            if plan:
                payload["plan"] = list(plan)
            if predicate:
                payload["success_predicate"] = str(predicate).strip()
            return payload
        return None

    @staticmethod
    def _coerce_payload(value: Any) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return {"command": text} if text else None
        if isinstance(value, (list, tuple)):
            return {"plan": list(value)} if value else None
        if not isinstance(value, Mapping):
            return None

        payload: Dict[str, Any] = {}
        command = value.get("command")
        if command:
            text = str(command).strip()
            if text:
                payload["command"] = text
        plan = value.get("plan")
        if plan:
            payload["plan"] = list(plan)
        predicate = value.get("success_predicate")
        if predicate:
            payload["success_predicate"] = str(predicate).strip()
        return payload or None

    @staticmethod
    def _priority(goal: Mapping[str, Any]) -> float:
        raw = goal.get("priority")
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            difficulty = _as_int(goal.get("difficulty"), 1) or 1
            return max(0.05, min(0.95, 0.4 + 0.1 * min(difficulty, 5)))

    def _find_existing(
        self,
        cognitive_goal: Mapping[str, Any],
        executable_goals: Sequence[Mapping[str, Any]],
        agent_name: str,
    ) -> Optional[Dict[str, Any]]:
        cognitive_id = _as_int(cognitive_goal.get("id"))
        if cognitive_id is None:
            return None
        linked_id = _as_int(cognitive_goal.get("delamain_goal_id"))
        matches: List[Dict[str, Any]] = []
        for candidate in executable_goals:
            metadata = _metadata(candidate)
            if metadata.get("bridge_source") != "goal_subsystem":
                continue
            if _as_int(metadata.get("cognitive_goal_id")) != cognitive_id:
                continue
            candidate_agent = str(metadata.get("cognitive_agent") or "")
            if candidate_agent and candidate_agent != agent_name:
                continue
            matches.append(dict(candidate))
        if not matches:
            return None
        if linked_id is not None:
            for candidate in matches:
                if _as_int(candidate.get("id")) == linked_id:
                    return candidate
        # A lost/incorrect in-memory id should attach to the newest existing
        # bridge goal, never create another one.
        return max(matches, key=lambda item: _as_int(item.get("id"), 0) or 0)


__all__ = [
    "BRIDGE_STATUSES",
    "GoalBridge",
    "bridge_summary",
    "derive_bridge_status",
    "evaluate_success_predicate",
]
