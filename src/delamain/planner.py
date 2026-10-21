"""Deterministic fallback planner.

This is not an LLM. It recognizes a small set of explicit Russian/English
commands and turns them into action requests. It exists so the runtime is
useful even when no model is installed, and so tests can exercise the whole
loop without network access or model downloads.

A model-backed planner can later produce the same ``ActionRequest`` objects.
"""

from __future__ import annotations

import re
from typing import List

from .models import ActionRequest


class PlannerError(Exception):
    """Raised when a task cannot be converted into a plan."""


def _clean(value: str) -> str:
    return value.strip().strip('"').strip("'").strip()


class HeuristicPlanner:
    """Recognize simple file/memory commands in Russian and English."""

    examples = (
        "список файлов",
        "прочитай notes/a.txt",
        "запиши в notes/a.txt: привет",
        "проверь notes/a.txt на привет",
        "найди TODO в **/*.py",
        "запомни язык = Python",
        "вспомни язык",
    )

    def plan(self, task: str) -> List[ActionRequest]:
        text = str(task or "").strip()
        if not text:
            raise PlannerError("task is empty")

        match = re.match(
            r"^(?:список\s+файлов|list\s+files)(?:\s+(?P<pattern>.+))?$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            pattern = _clean(match.group("pattern") or "**/*")
            return [ActionRequest("list_files", {"pattern": pattern})]

        match = re.match(
            r"^(?:запиши|write)\s+(?:в\s+)?(?P<path>[^:]+):\s*(?P<content>.*)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return [
                ActionRequest(
                    "write_file",
                    {
                        "path": _clean(match.group("path")),
                        "content": match.group("content"),
                    },
                )
            ]

        match = re.match(
            r"^(?:проверь|verify)\s+(?P<path>\S+)"
            r"(?:\s+(?:на|содержит|contains?)\s+(?P<needle>.+))?$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            args = {"path": _clean(match.group("path"))}
            if match.group("needle") is not None:
                args["contains"] = match.group("needle")
            return [ActionRequest("verify_file", args)]

        match = re.match(
            r"^(?:прочитай|прочти|read)\s+(?P<path>.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return [ActionRequest("read_file", {"path": _clean(match.group("path"))})]

        match = re.match(
            r"^(?:найди|поищи|search)\s+(?P<rest>.+)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            rest = match.group("rest").strip()
            parts = re.split(r"\s+(?:в|in)\s+", rest, maxsplit=1, flags=re.IGNORECASE)
            query = _clean(parts[0])
            pattern = _clean(parts[1]) if len(parts) > 1 else "**/*"
            if not query:
                raise PlannerError("search query is empty")
            return [
                ActionRequest(
                    "search_files",
                    {"query": query, "pattern": pattern},
                )
            ]

        match = re.match(
            r"^(?:запомни|remember)\s+(?P<key>[^=]+?)\s*=\s*(?P<value>.+)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            key = _clean(match.group("key"))
            value = match.group("value").strip()
            if not key or not value:
                raise PlannerError("remember command needs a non-empty key and value")
            return [
                ActionRequest(
                    "remember_fact",
                    {"key": key, "value": value, "source": "user"},
                )
            ]

        match = re.match(
            r"^(?:вспомни|recall)\s+(?P<query>.+)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            query = _clean(match.group("query"))
            if not query:
                raise PlannerError("recall query is empty")
            return [ActionRequest("recall_facts", {"query": query})]

        match = re.match(
            r"^(?:цель|goal)\s*:\s*(?P<title>.+)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return [
                ActionRequest(
                    "save_goal",
                    {"title": match.group("title").strip(), "priority": 0.6},
                )
            ]

        examples = "; ".join(self.examples)
        raise PlannerError(f"cannot parse task into actions; examples: {examples}")
