"""Typed actions available to the local agent.

An action is a small, named capability with a JSON-like argument dictionary.
The registry turns exceptions into observable ``ActionResult`` objects, so a
failed step can be recorded and inspected instead of crashing the whole task.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .memory import MemoryStore
from .models import ActionResult, ActionSpec, utc_now_iso
from .sandbox import Sandbox, SandboxError


class ActionError(Exception):
    """An expected action failure that should be shown to the planner."""


def _required(args: Mapping[str, Any], name: str) -> Any:
    if name not in args:
        raise ActionError(f"missing required argument: {name}")
    value = args[name]
    if value is None:
        raise ActionError(f"argument must not be null: {name}")
    return value


def _text_arg(args: Mapping[str, Any], name: str, default: Optional[str] = None) -> str:
    value = args.get(name, default)
    if value is None:
        raise ActionError(f"missing required argument: {name}")
    value = str(value)
    if not value and default is None:
        raise ActionError(f"argument must not be empty: {name}")
    return value


def _int_arg(
    args: Mapping[str, Any],
    name: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: Optional[int] = None,
) -> int:
    value = args.get(name, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ActionError(f"argument {name!r} must be an integer") from None
    if parsed < minimum:
        raise ActionError(f"argument {name!r} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def _bool_arg(args: Mapping[str, Any], name: str, default: bool) -> bool:
    value = args.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "да"}
    return bool(value)


class Action:
    """Base class for one capability."""

    spec: ActionSpec

    def run(self, args: Mapping[str, Any]) -> Any:  # pragma: no cover - interface
        raise NotImplementedError


class ActionRegistry:
    """Name-to-action registry with uniform error handling."""

    def __init__(self) -> None:
        self._actions: Dict[str, Action] = {}

    def register(self, action: Action) -> None:
        name = action.spec.name
        if not name:
            raise ValueError("action spec must have a name")
        if name in self._actions:
            raise ValueError(f"action already registered: {name}")
        self._actions[name] = action

    def get(self, name: str) -> Optional[Action]:
        return self._actions.get(str(name))

    def specs(self) -> List[ActionSpec]:
        return [self._actions[name].spec for name in sorted(self._actions)]

    def execute(
        self,
        name: str,
        args: Optional[Mapping[str, Any]] = None,
    ) -> ActionResult:
        action = self.get(name)
        started_at = utc_now_iso()
        started = time.perf_counter()
        if action is None:
            return ActionResult(
                action=str(name),
                ok=False,
                error=f"unknown action: {name}",
                started_at=started_at,
                duration_ms=0.0,
            )

        try:
            output = action.run(dict(args or {}))
            ok = True
            error = None
        except ActionError as exc:
            output = None
            ok = False
            error = str(exc)
        except (SandboxError, FileNotFoundError, FileExistsError, OSError) as exc:
            output = None
            ok = False
            error = str(exc)
        except Exception as exc:  # keep the loop alive and record the failure
            output = None
            ok = False
            error = f"{type(exc).__name__}: {exc}"

        return ActionResult(
            action=str(name),
            ok=ok,
            output=output,
            error=error,
            started_at=started_at,
            duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )

    @classmethod
    def default(cls, sandbox: Sandbox, memory: MemoryStore) -> "ActionRegistry":
        registry = cls()
        for action in (
            ListFilesAction(sandbox),
            ReadFileAction(sandbox),
            WriteFileAction(sandbox),
            WriteCreativeDraftAction(Sandbox(sandbox.root / "creative", max_file_bytes=8192, max_results=32)),
            SearchFilesAction(sandbox),
            VerifyFileAction(sandbox),
            RememberFactAction(memory),
            RecallFactsAction(memory),
            SetSelfModelAction(memory),
            GetSelfModelAction(memory),
            SaveGoalAction(memory),
            ListGoalsAction(memory),
        ):
            registry.register(action)
        return registry


class ListFilesAction(Action):
    spec = ActionSpec(
        name="list_files",
        description="List files inside the workspace matching a glob pattern.",
        parameters={"pattern": "glob, default '**/*'", "limit": "integer"},
    )

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        pattern = _text_arg(args, "pattern", "**/*")
        limit = _int_arg(args, "limit", 50, minimum=1)
        files = self.sandbox.list_files(pattern, limit=limit)
        return {"pattern": pattern, "files": files, "count": len(files)}


class ReadFileAction(Action):
    spec = ActionSpec(
        name="read_file",
        description="Read a UTF-8 text file from the workspace.",
        parameters={"path": "workspace-relative file path"},
    )

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        path = _text_arg(args, "path")
        text = self.sandbox.read_text(path)
        return {
            "path": path,
            "text": text,
            "bytes": len(text.encode("utf-8")),
            "lines": len(text.splitlines()),
        }


class WriteFileAction(Action):
    spec = ActionSpec(
        name="write_file",
        description="Atomically write a UTF-8 text file inside the workspace.",
        parameters={
            "path": "workspace-relative file path",
            "content": "text to write",
            "overwrite": "boolean, default true",
        },
        dangerous=True,
    )

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        path = _text_arg(args, "path")
        if "content" not in args:
            raise ActionError("missing required argument: content")
        content = args["content"]
        overwrite = _bool_arg(args, "overwrite", True)
        return self.sandbox.write_text(path, content, overwrite=overwrite)


class WriteCreativeDraftAction(Action):
    spec = ActionSpec(
        name="write_creative_draft",
        description="Write a bounded creative artifact inside the creative workspace only.",
        parameters={"path": "creative-relative .txt path", "content": "text", "overwrite": "boolean"},
        dangerous=True,
    )

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        path = _text_arg(args, "path")
        if Path(path).is_absolute() or ".." in Path(path).parts or path.startswith("creative/") or not path.lower().endswith(".txt"):
            raise ActionError("creative artifact must be a relative .txt path")
        content = _text_arg(args, "content")
        return self.sandbox.write_text(path, content, overwrite=_bool_arg(args, "overwrite", True))


class SearchFilesAction(Action):
    spec = ActionSpec(
        name="search_files",
        description="Case-insensitive text search across workspace files.",
        parameters={
            "query": "text to find",
            "pattern": "glob, default '**/*'",
            "limit": "integer",
            "context_lines": "integer, default 1",
        },
    )

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        query = _text_arg(args, "query")
        pattern = _text_arg(args, "pattern", "**/*")
        limit = _int_arg(args, "limit", 20, minimum=1)
        context_lines = _int_arg(args, "context_lines", 1, minimum=0, maximum=20)
        matches = self.sandbox.search_text(
            query,
            pattern,
            limit=limit,
            context_lines=context_lines,
        )
        return {"query": query, "matches": matches, "count": len(matches)}


class VerifyFileAction(Action):
    spec = ActionSpec(
        name="verify_file",
        description="Check that a file exists and optionally contains a substring.",
        parameters={
            "path": "workspace-relative file path",
            "contains": "optional substring",
            "min_bytes": "optional minimum size",
        },
    )

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        path = _text_arg(args, "path")
        info = self.sandbox.stat(path)
        text: Optional[str] = None
        if "contains" in args:
            needle = str(args["contains"])
            text = self.sandbox.read_text(path)
            if needle not in text:
                raise ActionError(f"file does not contain {needle!r}: {path}")
        if "min_bytes" in args:
            minimum = _int_arg(args, "min_bytes", 0, minimum=0)
            if int(info["bytes"]) < minimum:
                raise ActionError(
                    f"file is too small: {info['bytes']} bytes < {minimum}"
                )
        return {
            "path": path,
            "bytes": info["bytes"],
            "contains": str(args["contains"]) if "contains" in args else None,
            "verified": True,
        }


class RememberFactAction(Action):
    spec = ActionSpec(
        name="remember_fact",
        description="Store a small explicit fact in semantic memory.",
        parameters={
            "key": "fact key",
            "value": "fact value",
            "source": "optional source label",
            "confidence": "0..1, default 0.5",
        },
    )

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        key = _text_arg(args, "key")
        value = _text_arg(args, "value")
        source = str(args.get("source", "agent"))
        confidence = float(args.get("confidence", 0.5))
        return self.memory.remember_fact(
            key,
            value,
            source=source,
            confidence=confidence,
        )


class RecallFactsAction(Action):
    spec = ActionSpec(
        name="recall_facts",
        description="Search semantic memory for facts matching a query.",
        parameters={"query": "search query", "limit": "integer, default 10"},
    )

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        query = _text_arg(args, "query")
        limit = _int_arg(args, "limit", 10, minimum=1)
        facts = self.memory.recall_facts(query, limit=limit)
        return {"query": query, "facts": facts, "count": len(facts)}


class SetSelfModelAction(Action):
    spec = ActionSpec(
        name="set_self_model",
        description="Update one key of the agent's self-model.",
        parameters={"key": "self-model key", "value": "JSON-like value"},
        dangerous=True,
    )

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        key = _text_arg(args, "key")
        if "value" not in args:
            raise ActionError("missing required argument: value")
        self.memory.set_self_model(key, args["value"])
        return {"key": key, "updated": True}


class GetSelfModelAction(Action):
    spec = ActionSpec(
        name="get_self_model",
        description="Read the agent's self-model, or one key from it.",
        parameters={"key": "optional self-model key"},
    )

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        key = args.get("key")
        if key is None:
            return {"self_model": self.memory.get_self_model()}
        return {"key": str(key), "value": self.memory.get_self_model(str(key))}


class SaveGoalAction(Action):
    spec = ActionSpec(
        name="save_goal",
        description="Create a durable goal in memory.",
        parameters={
            "title": "goal title",
            "status": "default 'pending'",
            "success_predicate": "how completion will be checked",
            "priority": "0..1",
        },
    )

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        title = _text_arg(args, "title")
        goal_id = self.memory.save_goal(
            title,
            status=str(args.get("status", "pending")),
            success_predicate=str(args.get("success_predicate", "")),
            priority=float(args.get("priority", 0.5)),
            metadata=dict(args.get("metadata", {}) or {}),
        )
        return {"id": goal_id, "title": title}


class ListGoalsAction(Action):
    spec = ActionSpec(
        name="list_goals",
        description="List durable goals, optionally filtered by status.",
        parameters={"status": "optional goal status"},
    )

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def run(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        status = args.get("status")
        goals = self.memory.list_goals(status=str(status) if status is not None else None)
        return {"goals": goals, "count": len(goals)}
