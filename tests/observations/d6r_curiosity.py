"""D6-R-00…D6-R-04: уточняющие наблюдения curiosity.

Запуск из корня проекта:
    .venv/Scripts/python.exe tests/observations/d6r_curiosity.py --phase controlled
    .venv/Scripts/python.exe tests/observations/d6r_curiosity.py --phase network

Controlled-контур не использует реальную сеть. Network-контур выполняет только
два заранее заданных прямых act("web_search") в изолированном профиле.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import random
import subprocess
import sys
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_ROOT = PROJECT_ROOT / "tmp" / "motivation_d6r"
os.environ["DIGITAL_BEING_DATA_DIR"] = str(OBSERVATION_ROOT / "bootstrap")
os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
os.environ["VOICE_CONSOLE_QUIET"] = "1"
for endpoint in (
    "DIGITAL_BEING_TELEGRAM_TOKEN",
    "DIGITAL_BEING_TELEGRAM_CHAT_ID",
    "DIGITAL_BEING_DISCORD_WEBHOOK_URL",
):
    os.environ.pop(endpoint, None)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.simulation_config import LR_CONFIG  # noqa: E402
from src.core.agent import DigitalBeing  # noqa: E402
from src.core.agent_autonomous_tick import autonomous_tick_impl  # noqa: E402
from src.core.motivation.unified_motivation import UnifiedMotivationSystem  # noqa: E402
from src.core.world_delta import between, capture  # noqa: E402
from src.memory import knowledge_quality  # noqa: E402
from src.memory.knowledge_quality import (  # noqa: E402
    check_entry,
    is_relevant,
    meaningful_tokens,
    normalize_concept_name,
)
from src.perception import web_search as web_search_module  # noqa: E402

SEEDS = (20261121, 20261122, 20261123)
TARGET = "как связаны слои нейросети"
CONTROL_TARGET = "нейронная сеть"
MISS_RESPONSE = {
    "found": False,
    "title": "",
    "extract": "",
    "url": "",
    "lang": "ru",
    "source": "controlled_double",
    "error": "no_extract",
}
SUCCESS_RESPONSE = {
    "found": True,
    "title": "Слои нейросети",
    "extract": (
        "Слои нейросети преобразуют представления данных и передают результат "
        "следующему слою, образуя последовательную модель обработки информации."
    ),
    "url": "https://example.invalid/layers",
    "lang": "ru",
    "source": "controlled_double",
    "error": None,
}
NETWORK_FAILURE_REASONS = {"network_error", "timeout", "json_error", "unknown_error"}


def use_sandbox(name: str) -> str:
    path = OBSERVATION_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    os.environ["DIGITAL_BEING_DATA_DIR"] = str(path)
    return str(path)


def satisfy_all(system: UnifiedMotivationSystem) -> None:
    for need in system.needs.values():
        need.current_level = need.base_level
    for drive in system.drives.values():
        drive.current_level = 0.0


def all_levels(system: UnifiedMotivationSystem) -> dict[str, float]:
    return {name: need.current_level for name, need in system.needs.items()}


def need_deltas(before: dict[str, float], after: dict[str, float]) -> dict:
    return {
        name: {
            "before": before[name],
            "after": level,
            "delta": level - before[name],
        }
        for name, level in after.items()
        if level != before[name]
    }


def candidate_target(candidate: dict | None) -> str | None:
    params = (candidate or {}).get("params") or {}
    if not isinstance(params, dict):
        return None
    for key in ("topic", "concept", "target"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def candidate_metrics(candidates: list[dict]) -> list[dict]:
    fields = (
        "source",
        "action",
        "strength",
        "priority",
        "type",
        "need",
        "drive",
        "params",
        "simulation",
        "free_energy",
    )
    return [
        {field: deepcopy(item.get(field)) for field in fields if field in item}
        | {"target": candidate_target(item)}
        for item in candidates
    ]


def is_search(candidate: dict | None) -> bool:
    return bool(candidate) and candidate.get("action") == "web_search"


def new_agent(seed: int, name: str) -> DigitalBeing:
    random.seed(seed)
    np.random.seed(seed)
    agent = DigitalBeing(name=name)
    satisfy_all(agent.motivation_system)
    if agent.active_goal is not None:
        agent.active_goal["status"] = "pending"
    agent.active_goal = None
    agent.goal_subsystem.active_goal = None
    agent._last_action_outcome = None
    return agent


def add_social_topic(agent: DigitalBeing, topic: str) -> dict:
    node = agent.mental_models.encounter_concept(
        topic,
        context="D6-R controlled social-topic setup",
        outcome="Тема встречена, но собственного определения ещё нет",
    )
    return {
        "topic": topic,
        "definition_hypothesis": node.definition_hypothesis,
        "experience_count": len(node.experiences),
        "setup_mode": "real_mental_model_exposure_control",
    }


def git_output(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_data_manifest() -> dict[str, dict[str, Any]]:
    root = PROJECT_ROOT / "data"
    manifest: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return manifest
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            manifest[path.relative_to(root).as_posix()] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256(path),
            }
        except OSError as exc:
            manifest[path.relative_to(root).as_posix()] = {
                "observation_error": f"{type(exc).__name__}: {exc}"
            }
    return manifest


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def canonical_observation(value: Any) -> Any:
    """Сравнивает поведение, не требуя совпадения случайных opaque UUID."""
    if isinstance(value, dict):
        return {key: canonical_observation(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonical_observation(item) for item in value]
    if isinstance(value, str):
        parts = value.split("-")
        if [len(part) for part in parts] == [8, 4, 4, 4, 12] and all(
            part and all(char in "0123456789abcdefABCDEF" for char in part)
            for part in parts
        ):
            return "<opaque-uuid>"
    return value


def result_summary(result: dict | None) -> dict | None:
    if result is None:
        return None
    return {
        key: deepcopy(result.get(key))
        for key in ("found", "title", "url", "lang", "source", "error")
    } | {"extract_length": len(str(result.get("extract") or ""))}


def perform_direct_miss(agent: DigitalBeing) -> dict:
    """Контрольная подготовка следа; не входит в естественные метрики."""
    agent.cycle_count = 0
    before_needs = all_levels(agent.motivation_system)
    before_world = capture(agent)
    before_stats = agent.web_searcher.get_stats()
    before_misses = deepcopy(agent._hunt_misses)
    with (
        patch.object(
            agent.web_searcher, "search", return_value=deepcopy(MISS_RESPONSE)
        ) as search_mock,
        patch.object(
            agent.web_searcher,
            "_fetch",
            side_effect=RuntimeError("real network forbidden in controlled D6-R"),
        ) as network_guard,
    ):
        text = agent.act(
            "web_search",
            intention={"source": "d6r_controlled_setup", "params": {"target": TARGET}},
        )
    after_world = capture(agent)
    outcome = agent._last_action_outcome
    return {
        "execution_mode": "controlled_direct_act_not_natural_arbitration",
        "cycle": agent.cycle_count,
        "query": TARGET,
        "controlled_response": deepcopy(MISS_RESPONSE),
        "result_text": text,
        "search_queries": [call.args[0] for call in search_mock.call_args_list],
        "search_call_count": search_mock.call_count,
        "network_guard_call_count": network_guard.call_count,
        "network_calls_delta": (
            agent.web_searcher.get_stats()["network_calls"]
            - before_stats["network_calls"]
        ),
        "hunt_misses_before": before_misses,
        "hunt_misses_after": deepcopy(agent._hunt_misses),
        "outcome": outcome.as_dict() if outcome else None,
        "world_delta": between(before_world, after_world).as_dict(),
        "all_needs_before": before_needs,
        "all_needs_after": all_levels(agent.motivation_system),
        "need_deltas": need_deltas(before_needs, all_levels(agent.motivation_system)),
    }


def availability_line() -> int:
    lines, first = inspect.getsourcelines(autonomous_tick_impl)
    offset = next(
        index
        for index, line in enumerate(lines)
        if "candidate for candidate in candidates if self._is_candidate_available"
        in line
    )
    return first + offset


AVAILABILITY_LINE = availability_line()


def observe_natural_tick(
    agent: DigitalBeing,
    response_factory: Callable[[str, int], dict],
) -> dict:
    """Настоящий autonomous tick; меняется только ответ внешнего поисковика."""
    captured: dict[str, Any] = {}
    instrumentation_errors: list[str] = []
    search_events: list[dict] = []
    availability_events: list[dict] = []
    act_events: list[dict] = []
    action_feedback: list[dict] = []
    goal_feedback: list[dict] = []
    before_levels = all_levels(agent.motivation_system)
    before_world = capture(agent)
    before_stats = agent.web_searcher.get_stats()
    before_misses = deepcopy(agent._hunt_misses)
    previous_outcome = agent._last_action_outcome
    motivation_method = UnifiedMotivationSystem.get_action_candidates

    def tracer(frame, event, arg):
        try:
            if frame.f_code is motivation_method.__code__ and event == "return":
                captured["motivation_pre_top5"] = deepcopy(frame.f_locals["candidates"])
                captured["motivation_post_top5"] = deepcopy(arg)
                return tracer
            if (
                frame.f_code is autonomous_tick_impl.__code__
                and event == "line"
                and frame.f_lineno == AVAILABILITY_LINE
            ):
                captured["pre_availability"] = deepcopy(frame.f_locals["candidates"])
                return tracer
        except Exception as exc:
            instrumentation_errors.append(f"tracer: {type(exc).__name__}: {exc}")
        return (
            tracer
            if frame.f_code
            in {
                motivation_method.__code__,
                autonomous_tick_impl.__code__,
            }
            else None
        )

    real_choose = agent.decision_arbitrator.choose_action
    real_available = agent._is_candidate_available
    real_act = agent.act
    real_feedback = agent.motivation_system.on_action_result
    real_goal_feedback = agent.motivation_system.on_goal_achieved

    def observe_choice(candidates, context):
        try:
            captured["arbitrator_input"] = deepcopy(candidates)
            captured["arbitrator_context"] = deepcopy(context)
        except Exception as exc:
            instrumentation_errors.append(f"choice input: {type(exc).__name__}: {exc}")
        selected = real_choose(candidates, context)
        try:
            captured["arbitrator_output"] = deepcopy(selected)
        except Exception as exc:
            instrumentation_errors.append(f"choice output: {type(exc).__name__}: {exc}")
        return selected

    def observe_availability(candidate):
        available = real_available(candidate)
        try:
            availability_events.append(
                {
                    "candidate": candidate_metrics([candidate])[0],
                    "available": bool(available),
                }
            )
        except Exception as exc:
            instrumentation_errors.append(
                f"availability capture: {type(exc).__name__}: {exc}"
            )
        return available

    def observe_act(action, *args, **kwargs):
        event = {
            "action": action,
            "args": deepcopy(args),
            "intention": deepcopy(kwargs.get("intention")),
            "cycle": agent.cycle_count,
        }
        try:
            result = real_act(action, *args, **kwargs)
            event["result"] = result
            event["error"] = None
            return result
        except Exception as exc:
            event["result"] = None
            event["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            act_events.append(event)

    def observe_feedback(action_type, success, valence):
        before = all_levels(agent.motivation_system)
        result = real_feedback(action_type, success, valence)
        after = all_levels(agent.motivation_system)
        action_feedback.append(
            {
                "action_type": action_type,
                "success": success,
                "valence": valence,
                "need_deltas": need_deltas(before, after),
            }
        )
        return result

    def observe_goal_feedback(goal_title, goal_id=None):
        before = all_levels(agent.motivation_system)
        result = real_goal_feedback(goal_title, goal_id=goal_id)
        after = all_levels(agent.motivation_system)
        goal_feedback.append(
            {
                "goal_title": goal_title,
                "goal_id": goal_id,
                "need_deltas": need_deltas(before, after),
            }
        )
        return result

    def controlled_search(query):
        stats_before = agent.web_searcher.get_stats()
        response = deepcopy(response_factory(query, agent.cycle_count))
        search_events.append(
            {
                "cycle": agent.cycle_count,
                "query": query,
                "controlled_response": deepcopy(response),
                "hunt_misses_before_call": deepcopy(agent._hunt_misses),
                "stats_before": stats_before,
                "stats_after": agent.web_searcher.get_stats(),
            }
        )
        return response

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(agent.web_searcher, "search", side_effect=controlled_search)
        )
        network_guard = stack.enter_context(
            patch.object(
                agent.web_searcher,
                "_fetch",
                side_effect=RuntimeError("real network forbidden in controlled D6-R"),
            )
        )
        stack.enter_context(
            patch.object(
                agent.decision_arbitrator,
                "choose_action",
                side_effect=observe_choice,
            )
        )
        stack.enter_context(
            patch.object(
                agent, "_is_candidate_available", side_effect=observe_availability
            )
        )
        stack.enter_context(patch.object(agent, "act", side_effect=observe_act))
        stack.enter_context(
            patch.object(
                agent.motivation_system,
                "on_action_result",
                side_effect=observe_feedback,
            )
        )
        stack.enter_context(
            patch.object(
                agent.motivation_system,
                "on_goal_achieved",
                side_effect=observe_goal_feedback,
            )
        )
        interaction = getattr(agent, "user_interaction", None)
        if interaction is not None and callable(
            getattr(interaction, "send_message", None)
        ):
            stack.enter_context(
                patch.object(interaction, "send_message", return_value=None)
            )
        previous_trace = sys.gettrace()
        sys.settrace(tracer)
        try:
            report = agent.autonomous_tick()
        finally:
            sys.settrace(previous_trace)

    after_levels = all_levels(agent.motivation_system)
    after_world = capture(agent)
    after_stats = agent.web_searcher.get_stats()
    initial_choice = captured.get("arbitrator_output") or {}
    final_choice = report.get("arbitrator") or {}
    executed = report.get("executed_intention")
    pre_top5 = captured.get("motivation_pre_top5") or []
    post_top5 = captured.get("motivation_post_top5") or []
    pre_availability = captured.get("pre_availability") or []
    arbitrator_input = captured.get("arbitrator_input") or []
    outcome = agent._last_action_outcome
    action_result = (report.get("autonomous_action") or {}).get("result")
    last_miss = before_misses.get(TARGET)
    cooldown_answer = bool(
        executed
        and executed.get("action") == "web_search"
        and "след ещё свеж" in str(action_result)
    )
    world_delta = between(before_world, after_world).as_dict()
    proposed = any(is_search(item) for item in pre_top5 + pre_availability)
    post_top5_search = any(is_search(item) for item in post_top5 + pre_availability)
    entered = any(is_search(item) for item in arbitrator_input)
    selected = is_search(initial_choice)
    web_executed = bool(executed and executed.get("action") == "web_search")
    if not proposed:
        outcome_class = "search_not_proposed"
    elif not post_top5_search:
        outcome_class = "search_dropped_by_top5"
    elif not entered:
        outcome_class = "search_filtered_before_arbitrator"
    elif not selected:
        outcome_class = "search_lost_arbitration"
    elif not web_executed:
        outcome_class = "search_selected_not_executed"
    elif cooldown_answer:
        outcome_class = "search_cooldown_without_searcher"
    elif search_events:
        outcome_class = "search_called_searcher"
    else:
        outcome_class = "search_executed_other_outcome"
    return {
        "execution_mode": "real_autonomous_tick_real_arbitrator_real_act",
        "capture": {
            "motivation": "sys.settrace return: candidates and returned top-5",
            "pre_availability_line": AVAILABILITY_LINE,
            "availability": "pass-through wrapper around real filter",
            "arbitrator": "pass-through wrapper around real choose_action",
            "act": "pass-through wrapper around real act",
            "instrumentation_changes_strength_or_choice": False,
        },
        "seed_initial_setup": getattr(agent, "_d6r_seed", None),
        "cycle": report.get("cycle"),
        "current_topic": TARGET,
        "motivation_pre_top5": candidate_metrics(pre_top5),
        "motivation_post_top5": candidate_metrics(post_top5),
        "motivation_dropped_by_top5": candidate_metrics(pre_top5[len(post_top5) :]),
        "pre_availability": candidate_metrics(pre_availability),
        "availability_events": availability_events,
        "arbitrator_input": candidate_metrics(arbitrator_input),
        "arbitrator_context": captured.get("arbitrator_context"),
        "initial_arbitration": deepcopy(initial_choice),
        "final_arbitration": deepcopy(final_choice),
        "executed_intention": deepcopy(executed),
        "autonomous_action": deepcopy(report.get("autonomous_action")),
        "action_refused": deepcopy(report.get("action_refused")),
        "loop_escape": deepcopy(report.get("loop_escape")),
        "act_events": act_events,
        "outcome": outcome.as_dict() if outcome else None,
        "outcome_current_tick": (
            outcome.as_dict()
            if outcome is not previous_outcome and outcome is not None
            else None
        ),
        "search_events": search_events,
        "search_call_count": len(search_events),
        "network_guard_call_count": network_guard.call_count,
        "network_calls_before": before_stats["network_calls"],
        "network_calls_after": after_stats["network_calls"],
        "network_calls_delta": after_stats["network_calls"]
        - before_stats["network_calls"],
        "cache_hits_delta": after_stats["cache_hits"] - before_stats["cache_hits"],
        "real_search_network_used": False,
        "cooldown": {
            "hunt_misses_before": before_misses,
            "hunt_misses_after": deepcopy(agent._hunt_misses),
            "target_last_miss_before": last_miss,
            "cycle_difference_before": (
                report.get("cycle") - last_miss if last_miss is not None else None
            ),
            "cooldown_answer": cooldown_answer,
        },
        "world_before": asdict(before_world),
        "world_after": asdict(after_world),
        "world_delta": world_delta,
        "all_needs_before": before_levels,
        "all_needs_after": after_levels,
        "need_deltas": need_deltas(before_levels, after_levels),
        "action_feedback": action_feedback,
        "goal_achievement_feedback": goal_feedback,
        "instrumentation_errors": instrumentation_errors,
        "outcome_class": outcome_class,
    }


def long_series(scenario: str, seed: int, cycles: int, run_name: str) -> dict:
    sandbox = use_sandbox(f"controlled/{scenario}/{run_name}")
    agent = new_agent(seed, f"D6R_{scenario}_{run_name}")
    agent._d6r_seed = seed
    social_setup = add_social_topic(agent, TARGET)
    setup = perform_direct_miss(agent)
    success_delivered = False

    def stable_miss(query: str, cycle: int) -> dict:
        del query, cycle
        return deepcopy(MISS_RESPONSE)

    def miss_then_success(query: str, cycle: int) -> dict:
        nonlocal success_delivered
        last_miss = agent._hunt_misses.get(query)
        if (
            query == TARGET
            and not success_delivered
            and last_miss is not None
            and cycle - last_miss >= int(LR_CONFIG.HUNT_MISS_COOLDOWN_CYCLES)
        ):
            success_delivered = True
            return deepcopy(SUCCESS_RESPONSE)
        return deepcopy(MISS_RESPONSE)

    factory = stable_miss if scenario == "d6r_01" else miss_then_success
    observations = []
    for cycle in range(1, cycles + 1):
        agent.cycle_count = cycle
        observations.append(observe_natural_tick(agent, factory))
    return {
        "scenario": scenario,
        "seed": seed,
        "run_name": run_name,
        "sandbox": sandbox,
        "initial_arrangement": {
            "needs": "all needs at base before controlled initial miss",
            "active_goal": None,
            "social_topic": social_setup,
            "initial_miss_cycle": 0,
            "natural_cycles": cycles,
            "search_response_policy": (
                "stable no_extract"
                if scenario == "d6r_01"
                else "no_extract until first permitted TARGET repeat; one relevant success; then no_extract"
            ),
        },
        "controlled_setup": setup,
        "cycles": observations,
        "summary": summarize_cycles(observations),
        "post_cooldown_success_observed": success_delivered,
        "real_network_used": False,
    }


def ratio(numerator: int, denominator: int) -> dict:
    if denominator == 0:
        return {"value": None, "status": "not_observed", "denominator": 0}
    return {
        "value": numerator / denominator,
        "status": "observed",
        "numerator": numerator,
        "denominator": denominator,
    }


def summarize_cycles(cycles: list[dict]) -> dict:
    total = len(cycles)
    proposed = sum(
        any(is_search(item) for item in cycle["motivation_pre_top5"])
        or any(is_search(item) for item in cycle["pre_availability"])
        for cycle in cycles
    )
    entered = sum(
        any(is_search(item) for item in cycle["arbitrator_input"]) for cycle in cycles
    )
    selected_cycles = [
        cycle for cycle in cycles if is_search(cycle["initial_arbitration"])
    ]
    executed_cycles = [
        cycle
        for cycle in cycles
        if (cycle["executed_intention"] or {}).get("action") == "web_search"
    ]
    executed_ids = {id(cycle) for cycle in executed_cycles}
    cooldown_cycles = [
        cycle for cycle in cycles if cycle["cooldown"]["cooldown_answer"]
    ]
    handler_search_calls = sum(cycle["search_call_count"] for cycle in executed_cycles)
    web_searcher_calls_total = sum(cycle["search_call_count"] for cycle in cycles)
    other_action_search_calls = web_searcher_calls_total - handler_search_calls
    network_calls = sum(cycle["network_calls_delta"] for cycle in cycles)
    network_guard_calls = sum(cycle["network_guard_call_count"] for cycle in cycles)
    outcome_classes = Counter(cycle["outcome_class"] for cycle in cycles)
    outcome_cycles = {
        name: [cycle["cycle"] for cycle in cycles if cycle["outcome_class"] == name]
        for name in sorted(outcome_classes)
    }
    losses = Counter()
    wins = Counter()
    for cycle in cycles:
        if not any(is_search(item) for item in cycle["arbitrator_input"]):
            continue
        choice = cycle["initial_arbitration"]
        key = f"{choice.get('source')}:{choice.get('action')}"
        if is_search(choice):
            wins[key] += 1
        else:
            losses[key] += 1
    curiosity = {}
    for name in sorted(outcome_classes):
        members = [cycle for cycle in cycles if cycle["outcome_class"] == name]
        curiosity[name] = {
            "count": len(members),
            "delta_sum": sum(
                cycle["all_needs_after"]["curiosity"]
                - cycle["all_needs_before"]["curiosity"]
                for cycle in members
            ),
            "world_delta_nonempty": sum(
                any(cycle["world_delta"].values()) for cycle in members
            ),
        }
    success_cycles = [
        cycle["cycle"]
        for cycle in cycles
        if id(cycle) in executed_ids
        and cycle["search_events"]
        and any(
            event["controlled_response"].get("found")
            for event in cycle["search_events"]
        )
        and (cycle["outcome_current_tick"] or {}).get("had_effect") is True
    ]
    return {
        "cycles": total,
        "outcome_classes": dict(outcome_classes),
        "outcome_cycles": outcome_cycles,
        "ratios": {
            "search_proposal_per_cycle": ratio(proposed, total),
            "search_entering_arbitrator_per_cycle": ratio(entered, total),
            "natural_search_selection_per_cycle": ratio(len(selected_cycles), total),
            "executed_web_search_per_natural_selection": ratio(
                len(executed_cycles), len(selected_cycles)
            ),
            "cooldown_per_executed_web_search": ratio(
                len(cooldown_cycles), len(executed_cycles)
            ),
            "actual_search_calls_per_natural_selection": ratio(
                handler_search_calls, len(selected_cycles)
            ),
            "network_calls_per_actual_search_call": ratio(
                network_calls, handler_search_calls
            ),
        },
        "counts": {
            "search_proposals": proposed,
            "search_entering_arbitrator": entered,
            "natural_search_selections": len(selected_cycles),
            "executed_web_search": len(executed_cycles),
            "cooldown_answers": len(cooldown_cycles),
            "actual_search_calls": handler_search_calls,
            "web_searcher_calls_total": web_searcher_calls_total,
            "other_action_search_calls": other_action_search_calls,
            "network_calls": network_calls,
            "network_guard_calls": network_guard_calls,
        },
        "natural_selection_cycles": [cycle["cycle"] for cycle in selected_cycles],
        "executed_cycles": [cycle["cycle"] for cycle in executed_cycles],
        "cooldown_cycles": [cycle["cycle"] for cycle in cooldown_cycles],
        "search_call_cycles": [
            cycle["cycle"] for cycle in executed_cycles if cycle["search_call_count"]
        ],
        "success_after_cooldown": (
            {"status": "observed", "cycles": success_cycles}
            if success_cycles
            else {"status": "not_observed", "cycles": []}
        ),
        "search_wins_by_source_action": dict(wins),
        "search_losses_to_source_action": dict(losses),
        "curiosity_and_world_by_outcome": curiosity,
        "instrumentation_errors": [
            {"cycle": cycle["cycle"], "errors": cycle["instrumentation_errors"]}
            for cycle in cycles
            if cycle["instrumentation_errors"]
        ],
    }


def combined_summary(runs: list[dict]) -> dict:
    return summarize_cycles([cycle for run in runs for cycle in run["cycles"]])


def observe_relevance_matrix() -> dict:
    query = TARGET
    fixtures = [
        {
            "id": "exact_topic",
            "title": "Слои нейросети",
            "extract": "Слои нейросети последовательно преобразуют представления данных.",
        },
        {
            "id": "one_meaningful_word",
            "title": "Слои",
            "extract": "Отдельный уровень выполняет преобразование входного сигнала.",
        },
        {
            "id": "neighbor_without_query_words",
            "title": "Градиентный спуск",
            "extract": "Метод оптимизации параметров модели по градиенту функции потерь.",
        },
        {
            "id": "stop_words_only",
            "query": "как и что",
            "title": "Как и что",
            "extract": "Как и что — только служебные слова этого synthetic fixture.",
        },
        {"id": "empty_title_extract", "title": "", "extract": ""},
        {
            "id": "historical_title_neural_network",
            "title": "Нейронная сеть",
            "extract": "Synthetic extract: нейронная сеть состоит из связанных узлов и слоёв.",
        },
        {
            "id": "historical_title_convolutional",
            "title": "Свёрточная нейронная сеть",
            "extract": "Synthetic extract: архитектура применяет свёртки к входным данным.",
        },
        {
            "id": "historical_title_perceptron",
            "title": "Перцептрон",
            "extract": "Synthetic extract: перцептрон относит входной вектор к одному из классов.",
        },
    ]
    rows = []
    for fixture in fixtures:
        fixture_query = fixture.get("query", query)
        rows.append(
            {
                **deepcopy(fixture),
                "query": fixture_query,
                "meaningful_tokens": meaningful_tokens(fixture_query),
                "is_relevant": is_relevant(
                    fixture_query, fixture["title"], fixture["extract"]
                ),
                "evidence_kind": "synthetic_fixture_not_historical_text",
            }
        )
    return {
        "network_used": False,
        "real_function": "src.memory.knowledge_quality.is_relevant",
        "rows": rows,
    }


def run_controlled(cycles: int, baseline_cycles: int) -> dict:
    OBSERVATION_ROOT.mkdir(parents=True, exist_ok=True)
    live_before = repo_data_manifest()
    output = OBSERVATION_ROOT / "results_d6r_controlled.json"
    result: dict[str, Any] = {
        "schema": "d6r_curiosity_controlled_v1",
        "status": "running",
        "scope": ["D6-R-00", "D6-R-01", "D6-R-02", "D6-R-03"],
        "revision": git_output(["rev-parse", "HEAD"]),
        "command": (
            ".venv/Scripts/python.exe tests/observations/d6r_curiosity.py "
            "--phase controlled"
        ),
        "dirty_state_before": git_output(["status", "--short"]).splitlines(),
        "production_tracked_diff_before": git_output(
            ["diff", "--name-only", "--", "src", "config"]
        ).splitlines(),
        "seeds": list(SEEDS),
        "requested_cycles_per_seed": cycles,
        "baseline_cycles": baseline_cycles,
        "constants": {
            "HUNT_MISS_COOLDOWN_CYCLES": LR_CONFIG.HUNT_MISS_COOLDOWN_CYCLES,
            "EXPLORATION_DEPTH_RATIO": LR_CONFIG.EXPLORATION_DEPTH_RATIO,
        },
        "observation_root": str(OBSERVATION_ROOT / "controlled"),
        "live_data_files_observed": len(live_before),
        "live_data_manifest_fields": ["relative_path", "size", "mtime_ns", "sha256"],
    }
    baseline_a = long_series("d6r_00", SEEDS[0], baseline_cycles, "run_a")
    baseline_b = long_series("d6r_00", SEEDS[0], baseline_cycles, "run_b")
    baseline_metrics_a = {
        "controlled_setup": baseline_a["controlled_setup"],
        "cycles": baseline_a["cycles"],
        "summary": baseline_a["summary"],
    }
    baseline_metrics_b = {
        "controlled_setup": baseline_b["controlled_setup"],
        "cycles": baseline_b["cycles"],
        "summary": baseline_b["summary"],
    }
    result["d6r_00"] = {
        "run_a": baseline_a,
        "run_b": baseline_b,
        "identical_metrics": canonical_observation(baseline_metrics_a)
        == canonical_observation(baseline_metrics_b),
        "comparison_note": "Random opaque UUID values are canonicalized; all behavioral fields remain",
        "real_network_used": False,
    }
    write_json(output, result)
    if not result["d6r_00"]["identical_metrics"]:
        result["status"] = "stopped_baseline_not_reproducible"
        write_json(output, result)
        raise RuntimeError("D6-R-00 baseline mismatch; long series not started")

    for scenario in ("d6r_01", "d6r_02"):
        runs = []
        result[scenario] = {"runs": runs, "real_network_used": False}
        for seed in SEEDS:
            print(f"{scenario}: seed={seed}, cycles={cycles}", flush=True)
            runs.append(long_series(scenario, seed, cycles, str(seed)))
            result[scenario]["combined"] = combined_summary(runs)
            write_json(output, result)
    result["d6r_03"] = observe_relevance_matrix()
    live_after = repo_data_manifest()
    result["live_data_unchanged"] = live_before == live_after
    result["production_tracked_diff_after"] = git_output(
        ["diff", "--name-only", "--", "src", "config"]
    ).splitlines()
    result["status"] = "completed"
    write_json(output, result)
    return result


def observe_network_query(agent: DigitalBeing, query: str) -> dict:
    before_levels = all_levels(agent.motivation_system)
    before_world = capture(agent)
    before_stats = agent.web_searcher.get_stats()
    before_misses = deepcopy(agent._hunt_misses)
    request_events: list[dict] = []
    fetch_events: list[dict] = []
    relevance_events: list[dict] = []
    quality_events: list[dict] = []
    search_errors: list[str] = []
    real_request = agent.web_searcher._request_json
    real_fetch = agent.web_searcher._fetch
    real_search = agent.web_searcher.search

    def observe_request(url, lang, query):
        data, error = real_request(url, lang, query)
        pages = []
        hits = []
        if isinstance(data, dict):
            pages = [
                {
                    "title": str(page.get("title") or ""),
                    "url": str(page.get("fullurl") or ""),
                    "extract_length": len(str(page.get("extract") or "")),
                }
                for page in ((data.get("query") or {}).get("pages") or {}).values()
            ]
            hits = [
                str(hit.get("title") or "")
                for hit in ((data.get("query") or {}).get("search") or [])
            ]
        request_events.append(
            {
                "url": url,
                "lang": lang,
                "query": query,
                "error": error,
                "pages": pages,
                "fulltext_hit_titles": hits,
            }
        )
        return data, error

    def observe_relevance(relevance_query, title, extract):
        decision = is_relevant(relevance_query, title, extract)
        relevance_events.append(
            {
                "query": relevance_query,
                "meaningful_tokens": meaningful_tokens(relevance_query),
                "title": title,
                "extract_length": len(str(extract or "")),
                "decision": decision,
            }
        )
        return decision

    def observe_fetch(fetch_query, lang, **kwargs):
        request_start = len(request_events)
        relevance_start = len(relevance_events)
        result = real_fetch(fetch_query, lang, **kwargs)
        fetch_events.append(
            {
                "query": fetch_query,
                "lang": lang,
                "source_argument": kwargs.get("source", "wikipedia:title"),
                "base_url": kwargs.get("base_url"),
                "relevance_query": kwargs.get("relevance_query"),
                "result": result_summary(result),
                "request_events": deepcopy(request_events[request_start:]),
                "relevance_events": deepcopy(relevance_events[relevance_start:]),
            }
        )
        return result

    def observe_quality(key, definition):
        reason = check_entry(key, definition)
        quality_events.append(
            {
                "key": key,
                "definition_length": len(str(definition or "")),
                "rejection_reason": reason,
                "accepted": reason is None,
            }
        )
        return reason

    def observe_search(search_query):
        try:
            return real_search(search_query)
        except Exception as exc:
            search_errors.append(f"{type(exc).__name__}: {exc}")
            raise

    with (
        patch.object(agent.web_searcher, "search", side_effect=observe_search),
        patch.object(agent.web_searcher, "_request_json", side_effect=observe_request),
        patch.object(agent.web_searcher, "_fetch", side_effect=observe_fetch),
        patch.object(web_search_module, "is_relevant", side_effect=observe_relevance),
        patch.object(knowledge_quality, "check_entry", side_effect=observe_quality),
    ):
        text = agent.act(
            "web_search",
            intention={
                "source": "d6r_real_network_direct",
                "params": {"target": query},
            },
        )
    after_world = capture(agent)
    after_stats = agent.web_searcher.get_stats()
    outcome = agent._last_action_outcome
    response_error = search_errors[-1] if search_errors else None
    for event in reversed(fetch_events):
        if response_error is None and event["result"] is not None:
            response_error = event["result"].get("error")
            if response_error:
                break
    not_observed = bool(
        search_errors
        or (
            response_error
            and (
                response_error in NETWORK_FAILURE_REASONS
                or response_error.startswith("http_")
            )
        )
    )
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "real_network_direct_act_not_natural_arbitration",
        "query": query,
        "normalized_query": normalize_concept_name(query),
        "observation_status": "not_observed" if not_observed else "observed",
        "final_response_error": response_error,
        "instrumentation_errors": search_errors,
        "result_text": text,
        "outcome": outcome.as_dict() if outcome else None,
        "request_events": request_events,
        "fetch_events": fetch_events,
        "relevance_events": relevance_events,
        "check_entry_events": quality_events,
        "stats_before": before_stats,
        "stats_after": after_stats,
        "network_calls_delta": after_stats["network_calls"]
        - before_stats["network_calls"],
        "cache_hits_delta": after_stats["cache_hits"] - before_stats["cache_hits"],
        "cache_size_after": len(agent.web_searcher._cache),
        "hunt_misses_before": before_misses,
        "hunt_misses_after": deepcopy(agent._hunt_misses),
        "world_before": asdict(before_world),
        "world_after": asdict(after_world),
        "world_delta": between(before_world, after_world).as_dict(),
        "all_needs_before": before_levels,
        "all_needs_after": all_levels(agent.motivation_system),
        "need_deltas": need_deltas(before_levels, all_levels(agent.motivation_system)),
        "full_article_text_recorded": False,
    }


def run_network() -> dict:
    live_before = repo_data_manifest()
    sandbox = use_sandbox("network/profile")
    agent = new_agent(SEEDS[0], "D6R_RealNetwork")
    queries = []
    for query in (TARGET, CONTROL_TARGET):
        print(f"d6r_04: real network query={query}", flush=True)
        queries.append(observe_network_query(agent, query))
    live_after = repo_data_manifest()
    result = {
        "schema": "d6r_curiosity_network_v1",
        "status": "completed",
        "scope": ["D6-R-04"],
        "revision": git_output(["rev-parse", "HEAD"]),
        "command": (
            ".venv/Scripts/python.exe tests/observations/d6r_curiosity.py --phase network"
        ),
        "sandbox": sandbox,
        "queries": queries,
        "allowed_queries": [TARGET, CONTROL_TARGET],
        "direct_act_count": len(queries),
        "natural_arbitration_used": False,
        "live_data_files_observed": len(live_before),
        "live_data_manifest_fields": ["relative_path", "size", "mtime_ns", "sha256"],
        "live_data_unchanged": live_before == live_after,
        "production_tracked_diff_after": git_output(
            ["diff", "--name-only", "--", "src", "config"]
        ).splitlines(),
    }
    output = OBSERVATION_ROOT / "results_d6r_network.json"
    write_json(output, result)
    return result


def console_controlled_summary(result: dict) -> dict:
    return {
        "status": result["status"],
        "baseline_identical": result["d6r_00"]["identical_metrics"],
        "d6r_01": result.get("d6r_01", {}).get("combined"),
        "d6r_02": result.get("d6r_02", {}).get("combined"),
        "d6r_03_decisions": {
            row["id"]: row["is_relevant"]
            for row in result.get("d6r_03", {}).get("rows", [])
        },
        "live_data_unchanged": result.get("live_data_unchanged"),
        "production_tracked_diff_after": result.get("production_tracked_diff_after"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase", choices=("controlled", "network", "all"), default="all"
    )
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--baseline-cycles", type=int, default=12)
    args = parser.parse_args()
    if args.cycles < 1 or args.baseline_cycles < 1:
        parser.error("cycle counts must be positive")
    if args.phase in {"controlled", "all"}:
        controlled = run_controlled(args.cycles, args.baseline_cycles)
        print(
            json.dumps(
                console_controlled_summary(controlled), ensure_ascii=False, indent=2
            )
        )
    if args.phase in {"network", "all"}:
        network = run_network()
        print(
            json.dumps(
                {
                    "status": network["status"],
                    "queries": [
                        {
                            "query": item["query"],
                            "observation_status": item["observation_status"],
                            "network_calls": item["network_calls_delta"],
                            "cache_hits": item["cache_hits_delta"],
                            "relevance_decisions": [
                                event["decision"] for event in item["relevance_events"]
                            ],
                            "result_text": item["result_text"],
                        }
                        for item in network["queries"]
                    ],
                    "live_data_unchanged": network["live_data_unchanged"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
