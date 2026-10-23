"""Delamain-local: the closed action/memory loop for Digital Being.

This package is intentionally small and dependency-free. It contains the
first working vertical slice of the new architecture:

* a path-sandboxed file workspace;
* typed actions with observable results;
* SQLite episodic/semantic memory;
* a runtime that executes a plan and records every step;
* an optional, disabled-by-default subsystem adapter for Digital Being;
* an optional local LLM planner with a deterministic fallback;
* an optional approval gate for dangerous actions, disabled by default;
* an optional bridge from cognitive goals to executable goals, disabled by
  default;
* an optional authoring layer for explicit or planner-proposed executable
  payloads (proposals never execute themselves);
* optional retry backoff and failure-aware replanning, disabled by default;
* optional bounded step repair inside one attempt, disabled by default;
* an offline, deterministic capability evaluation harness.

The LLM layer is never required: constructing the core does not start Ollama
or make network requests, and every planning failure falls back to the
heuristic planner.
"""

from .actions import Action, ActionError, ActionRegistry
from .approval import ApprovalPolicy, VALID_APPROVAL_MODES, normalize_approval_mode
from .goal_authoring import (
    AUTHORABLE_GOAL_STATUSES,
    PROPOSAL_STATUSES,
    GoalAuthoring,
    GoalExecutionProposal,
)
from .goal_bridge import (
    BRIDGE_STATUSES,
    GoalBridge,
    bridge_summary,
    derive_bridge_status,
    evaluate_success_predicate,
)
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
    "ApprovalPolicy",
    "ActionResult",
    "ActionRequest",
    "ActionSpec",
    "AUTHORABLE_GOAL_STATUSES",
    "BRIDGE_STATUSES",
    "CaseResult",
    "DelamainRuntime",
    "DelamainSubsystem",
    "EvalSuite",
    "EvaluationError",
    "FallbackPlanner",
    "GoalAuthoring",
    "GoalBridge",
    "GoalExecutionProposal",
    "HeuristicPlanner",
    "MemoryStore",
    "OllamaPlanner",
    "PROPOSAL_STATUSES",
    "Planner",
    "PlannerError",
    "Sandbox",
    "SandboxError",
    "ScriptedPlanner",
    "SuiteResult",
    "TaskResult",
    "VALID_APPROVAL_MODES",
    "bridge_summary",
    "derive_bridge_status",
    "evaluate_success_predicate",
    "load_suite",
    "normalize_approval_mode",
    "run_suite",
    "utc_now_iso",
]

_EVALUATION_EXPORTS = {
    "CaseResult",
    "EvalSuite",
    "EvaluationError",
    "ScriptedPlanner",
    "SuiteResult",
    "load_suite",
    "run_suite",
}


def __getattr__(name: str):
    """Keep the evaluation harness out of normal package import paths."""

    if name in _EVALUATION_EXPORTS:
        from . import evaluation

        value = getattr(evaluation, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
