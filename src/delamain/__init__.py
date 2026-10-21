"""Delamain-local: the closed action/memory loop for Digital Being.

This package is intentionally small and dependency-free. It contains the
first working vertical slice of the new architecture:

* a path-sandboxed file workspace;
* typed actions with observable results;
* SQLite episodic/semantic memory;
* a runtime that executes a plan and records every step;
* an optional, disabled-by-default subsystem adapter for Digital Being;
* an optional local LLM planner with a deterministic fallback.

The LLM layer is never required: constructing the core does not start Ollama
or make network requests, and every planning failure falls back to the
heuristic planner.
"""

from .actions import Action, ActionError, ActionRegistry
from .memory import MemoryStore
from .models import (
    ActionResult,
    ActionRequest,
    ActionSpec,
    TaskResult,
    utc_now_iso,
)
from .llm_planner import OllamaPlanner
from .planner import FallbackPlanner, HeuristicPlanner, Planner, PlannerError
from .runtime import DelamainRuntime
from .sandbox import Sandbox, SandboxError
from .subsystem import DelamainSubsystem

__all__ = [
    "Action",
    "ActionError",
    "ActionRegistry",
    "ActionResult",
    "ActionRequest",
    "ActionSpec",
    "DelamainRuntime",
    "DelamainSubsystem",
    "FallbackPlanner",
    "HeuristicPlanner",
    "MemoryStore",
    "OllamaPlanner",
    "Planner",
    "PlannerError",
    "Sandbox",
    "SandboxError",
    "TaskResult",
    "utc_now_iso",
]
