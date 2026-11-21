"""D5-00…D5-07: изолированные наблюдения curiosity и поиска тем.

Запуск из корня проекта:
    .venv/Scripts/python.exe tests/observations/d5_curiosity.py

Скрипт не задаёт желаемое поведение assertion-ами и не исправляет production-код.
Реальная сеть не используется. Метрики сохраняются в
 tmp/motivation_d5/results_d5_00_07.json.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import random
import subprocess
import sys
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_ROOT = PROJECT_ROOT / "tmp" / "motivation_d5"
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
from src.cognition.activity_goals import active_goal_candidate  # noqa: E402
from src.cognition.intention_continuation import (  # noqa: E402
    ACTIONS as CONTINUATION_ACTIONS,
)
from src.core.agent import DigitalBeing  # noqa: E402
from src.core.agent_autonomous_tick import autonomous_tick_impl  # noqa: E402
from src.core.checkpoint_serializer import (  # noqa: E402
    CheckpointSerializer,
    apply_state_to_agent,
)
from src.core.motivation.unified_motivation import UnifiedMotivationSystem  # noqa: E402
from src.core.world_delta import capture  # noqa: E402

SEED = 20261121
TARGET = "как связаны слои нейросети"
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


def need_state(system: UnifiedMotivationSystem, name: str = "curiosity") -> dict:
    need = system.needs[name]
    return {
        "current_level": need.current_level,
        "base_level": need.base_level,
        "decay_rate": need.decay_rate,
        "threshold": need.threshold,
        "priority": need.priority,
        "pressing": need.is_pressing(),
        "pressure": need.pressure(),
        "urgency": need.urgency(),
    }


def candidate_metrics(candidates: list[dict]) -> list[dict]:
    return [
        {
            "source": item.get("source"),
            "action": item.get("action"),
            "strength": item.get("strength"),
            "priority": item.get("priority"),
            "type": item.get("type"),
            "need": item.get("need"),
            "drive": item.get("drive"),
            "params": deepcopy(item.get("params") or {}),
        }
        for item in candidates
    ]


def concept_metrics(agent: DigitalBeing) -> dict:
    concepts = getattr(agent.mental_models, "concepts", {})
    return {
        name: {
            "confidence": float(getattr(node, "confidence", 0.0) or 0.0),
            "definition_hypothesis": str(
                getattr(node, "definition_hypothesis", "") or ""
            ),
            "experiences": len(getattr(node, "experiences", []) or []),
            "connections": sorted((getattr(node, "connections", {}) or {}).keys()),
        }
        for name, node in sorted(concepts.items())
    }


def repo_data_manifest() -> dict[str, list[int]]:
    root = PROJECT_ROOT / "data"
    manifest = {}
    if not root.exists():
        return manifest
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        manifest[str(path.relative_to(root))] = [stat.st_size, stat.st_mtime_ns]
    return manifest


def git_output(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def new_agent(
    name: str, *, low_curiosity: bool = True, without_active_goal: bool = False
) -> DigitalBeing:
    random.seed(SEED)
    agent = DigitalBeing(name=name)
    satisfy_all(agent.motivation_system)
    if low_curiosity:
        agent.motivation_system.needs["curiosity"].current_level = 0.1
    if without_active_goal:
        if agent.active_goal is not None:
            agent.active_goal["status"] = "pending"
        agent.active_goal = None
        agent.goal_subsystem.active_goal = None
    agent._last_action_outcome = None
    return agent


def perform_action(
    agent: DigitalBeing,
    action: str,
    *,
    intention: dict | None = None,
    response: dict | None = None,
    search_error: Exception | None = None,
    search_enabled: bool = True,
    denied: bool = False,
    use_real_search: bool = False,
) -> dict:
    """Исполняет реальный act с управляемой внешней границей поиска."""
    agent.web_searcher.toggle(search_enabled)
    if denied:
        agent.energy = 0.0
    agent._last_action_outcome = None
    before_levels = all_levels(agent.motivation_system)
    before_world = asdict(capture(agent))
    before_energy = agent.energy
    before_web_stats = agent.web_searcher.get_stats()
    feedback = {}
    goal_feedback = []
    real_feedback = agent.motivation_system.on_action_result
    real_goal_feedback = agent.motivation_system.on_goal_achieved

    def observe_feedback(action_type, success, valence):
        before = all_levels(agent.motivation_system)
        result = real_feedback(action_type, success, valence)
        after = all_levels(agent.motivation_system)
        feedback.update(
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

    search_controls = (
        {"wraps": agent.web_searcher.search}
        if use_real_search
        else {"return_value": deepcopy(response), "side_effect": search_error}
    )
    result_text = None
    error = None
    with (
        patch.object(agent.web_searcher, "search", **search_controls) as search_mock,
        patch.object(
            agent.motivation_system,
            "on_action_result",
            side_effect=observe_feedback,
        ),
        patch.object(
            agent.motivation_system,
            "on_goal_achieved",
            side_effect=observe_goal_feedback,
        ),
    ):
        try:
            result_text = agent.act(action, intention=intention)
        except Exception as exc:  # ошибка действия тоже является наблюдением
            error = f"{type(exc).__name__}: {exc}"

    after_levels = all_levels(agent.motivation_system)
    outcome = agent._last_action_outcome
    return {
        "requested_action": action,
        "cycle_count": agent.cycle_count,
        "intention": deepcopy(intention),
        "controlled_response": deepcopy(response),
        "controlled_error": (
            f"{type(search_error).__name__}: {search_error}" if search_error else None
        ),
        "search_enabled": search_enabled,
        "denied_control": denied,
        "real_search_used": use_real_search,
        "result_text": result_text,
        "action_error": error,
        "observation_status": "observed_error" if error else "observed",
        "search_queries": [call.args[0] for call in search_mock.call_args_list],
        "search_call_count": search_mock.call_count,
        "web_search_stats_before": before_web_stats,
        "web_search_stats_after": agent.web_searcher.get_stats(),
        "web_cache_size_after": len(agent.web_searcher._cache),
        "outcome": outcome.as_dict() if outcome else None,
        "world_before": before_world,
        "world_after": asdict(capture(agent)),
        "knowledge_base": deepcopy(agent.knowledge_base),
        "known_definition_keys": sorted(agent._known_definitions),
        "concepts": concept_metrics(agent),
        "hunt_misses": deepcopy(agent._hunt_misses),
        "motivation_feedback": feedback or None,
        "goal_achievement_feedback": goal_feedback,
        "need_deltas": need_deltas(before_levels, after_levels),
        "all_needs_before": before_levels,
        "all_needs_after": after_levels,
        "energy_before": before_energy,
        "energy_after": agent.energy,
    }


def baseline_run(run_name: str) -> dict:
    sandbox = use_sandbox(f"d5_00/{run_name}")
    agent = new_agent("D5Baseline", low_curiosity=False)
    system = agent.motivation_system
    need = system.needs["curiosity"]
    expected_ticks = (
        math.floor((need.base_level - need.threshold) / need.decay_rate) + 1
    )
    initial = need_state(system)
    history = []
    ticks = 0
    while not need.is_pressing() and ticks <= 1000:
        system.tick({})
        ticks += 1
        history.append(
            {
                "tick": ticks,
                "curiosity_level": need.current_level,
                "pressing": need.is_pressing(),
                "all_levels": all_levels(system),
            }
        )
    candidates = candidate_metrics(system.get_action_candidates({}))
    before_search = need_state(system)
    search = perform_action(
        agent,
        "web_search",
        intention={"source": "d5_controlled_baseline", "params": {"target": TARGET}},
        response=SUCCESS_RESPONSE,
    )
    return {
        "sandbox": sandbox,
        "metrics": {
            "seed": SEED,
            "initial_curiosity": initial,
            "expected_ticks_floor_plus_1_precomputed": expected_ticks,
            "actual_ticks": ticks,
            "tick_history": history,
            "candidates_before_controlled_search": candidates,
            "curiosity_before_search": before_search,
            "execution_mode": "controlled_direct_act_not_natural_arbitration",
            "search": search,
        },
    }


def observe_d5_00() -> dict:
    first = baseline_run("run_a")
    second = baseline_run("run_b")
    return {
        "first": first,
        "second": second,
        "identical_metrics": first["metrics"] == second["metrics"],
        "real_network_used": False,
    }


def observe_d5_01() -> dict:
    decomposition_sandbox = use_sandbox("d5_01/decomposition_and_target")
    agent = new_agent("D5Topic")
    decomposition = perform_action(
        agent,
        "decomposition",
        intention={
            "source": "d5_controlled_topic",
            "params": {"target": "нейросеть архитектура"},
        },
    )
    questions = deepcopy(agent.get_open_questions())
    selected = next(
        (item.get("text") for item in questions if item.get("text") == TARGET),
        None,
    )
    repeated = []
    if selected is not None:
        for index in range(3):
            repeated.append(
                perform_action(
                    agent,
                    "web_search",
                    intention={
                        "source": "d5_explicit_target",
                        "params": {"concept": selected},
                    },
                    response=SUCCESS_RESPONSE,
                )
            )

    fallback_sandbox = use_sandbox("d5_01/fallback")
    fallback_agent = new_agent("D5Fallback")
    with patch.object(
        fallback_agent, "_pick_exploration_target", return_value="свободная тема"
    ) as selector:
        fallback = perform_action(
            fallback_agent,
            "web_search",
            intention={"source": "d5_without_target", "params": {}},
            response={
                **SUCCESS_RESPONSE,
                "title": "Свободная тема",
                "extract": (
                    "Свободная тема используется как контрольная метка для проверки "
                    "передачи селектора исследования в обработчик поиска."
                ),
            },
        )
    fallback["selector_call_count"] = selector.call_count

    conflict_sandbox = use_sandbox("d5_01/conflicting_targets")
    conflict_agent = new_agent("D5Conflict")
    conflict = perform_action(
        conflict_agent,
        "web_search",
        intention={
            "source": "d5_validation_control",
            "params": {"topic": TARGET, "target": "другая тема"},
        },
        response=SUCCESS_RESPONSE,
    )
    return {
        "decomposition": {
            "sandbox": decomposition_sandbox,
            "action": decomposition,
            "open_questions": questions,
            "selected_target": selected,
            "repeated_explicit_target": repeated,
        },
        "fallback": {"sandbox": fallback_sandbox, "action": fallback},
        "conflicting_targets": {"sandbox": conflict_sandbox, "action": conflict},
        "real_network_used": False,
    }


def outcome_cases() -> dict[str, dict[str, Any]]:
    return {
        "success_relevant": {
            "response": {
                **SUCCESS_RESPONSE,
                "title": "Память",
                "extract": (
                    "Память — это процесс сохранения и последующего восстановления "
                    "сведений, поддерживающий обучение и использование опыта."
                ),
            }
        },
        "success_neighbor": {
            "response": {
                **SUCCESS_RESPONSE,
                "title": "Мнемоника",
                "extract": (
                    "Мнемоника — это система приёмов запоминания, которая связывает "
                    "новые сведения с образами и помогает восстанавливать память."
                ),
            }
        },
        "miss_no_extract": {
            "response": {
                "found": False,
                "title": "",
                "extract": "",
                "error": "no_extract",
            }
        },
        "empty_extract": {
            "response": {
                **SUCCESS_RESPONSE,
                "title": "Память",
                "extract": "",
            }
        },
        "weak_disambiguation": {
            "response": {
                **SUCCESS_RESPONSE,
                "title": "Память",
                "extract": "Память may refer to: несколько разных значений термина.",
            }
        },
        "search_exception": {"search_error": RuntimeError("controlled search failure")},
        "disabled": {"search_enabled": False, "response": SUCCESS_RESPONSE},
        "denied": {"denied": True, "response": SUCCESS_RESPONSE},
    }


def observe_d5_02() -> dict:
    observations = {}
    for case, control in outcome_cases().items():
        sandbox = use_sandbox(f"d5_02/{case}")
        agent = new_agent(f"D5Outcome_{case}")
        action = perform_action(
            agent,
            "web_search",
            intention={"source": "d5_outcome_matrix", "params": {"target": "память"}},
            **control,
        )
        observations[case] = {
            "sandbox": sandbox,
            "execution_mode": "controlled_direct_act_not_natural_arbitration",
            "action": action,
        }
    return {
        "cases": observations,
        "real_network_used": False,
        "relevance_filter_inside_web_searcher_exercised": False,
        "limitation": (
            "Double находится на границе WebSearcher.search; внутренняя HTTP-цепочка "
            "и is_relevant не выполняются. weak_disambiguation проверяет check_entry "
            "в реальном _act_web_search."
        ),
    }


def memory_success_response() -> dict:
    return deepcopy(outcome_cases()["success_relevant"]["response"])


def miss_response() -> dict:
    return deepcopy(outcome_cases()["miss_no_extract"]["response"])


def search_intention(source: str, target: str = "память") -> dict:
    return {"source": source, "params": {"target": target}}


def controlled_search(
    agent: DigitalBeing,
    cycle: int,
    *,
    source: str,
    target: str = "память",
    response: dict | None = None,
    **controls: Any,
) -> dict:
    agent.cycle_count = cycle
    return perform_action(
        agent,
        "web_search",
        intention=search_intention(source, target),
        response=response,
        **controls,
    )


def observe_d5_03() -> dict:
    cooldown = int(LR_CONFIG.HUNT_MISS_COOLDOWN_CYCLES)
    boundary_sandbox = use_sandbox("d5_03/cooldown_boundary")
    boundary_agent = new_agent("D5Cooldown", without_active_goal=True)
    boundary_start = 10
    boundary_steps = [
        {
            "offset_from_miss": offset,
            "action": controlled_search(
                boundary_agent,
                boundary_start + offset,
                source="d5_03_cooldown_boundary",
                response=miss_response(),
            ),
        }
        for offset in (0, 1, cooldown - 1, cooldown)
    ]

    recovery_sandbox = use_sandbox("d5_03/success_after_miss")
    recovery_agent = new_agent("D5HuntRecovery", without_active_goal=True)
    recovery_steps = [
        controlled_search(
            recovery_agent,
            40,
            source="d5_03_initial_miss",
            response=miss_response(),
        ),
        controlled_search(
            recovery_agent,
            40 + cooldown,
            source="d5_03_success_after_miss",
            response=memory_success_response(),
        ),
    ]

    topics_sandbox = use_sandbox("d5_03/same_and_new_topics")
    topics_agent = new_agent("D5RepeatedTopics", without_active_goal=True)
    topic_steps = [
        controlled_search(
            topics_agent,
            0,
            source="d5_03_first_success",
            response=memory_success_response(),
        ),
        controlled_search(
            topics_agent,
            1,
            source="d5_03_repeat_same_success",
            response=memory_success_response(),
        ),
        controlled_search(
            topics_agent,
            2,
            source="d5_03_success_new_topic",
            target="внимание",
            response={
                **SUCCESS_RESPONSE,
                "title": "Внимание",
                "extract": (
                    "Внимание — это процесс избирательного выделения сведений "
                    "для обработки, который поддерживает восприятие и обучение."
                ),
            },
        ),
    ]

    cache_sandbox = use_sandbox("d5_03/lru_cache")
    cache_agent = new_agent("D5Cache", without_active_goal=True)
    cache_key = f"{cache_agent.web_searcher.lang}:память"
    cache_agent.web_searcher._cache[cache_key] = memory_success_response()
    with patch.object(
        cache_agent.web_searcher,
        "_fetch",
        side_effect=RuntimeError("real network forbidden in D5"),
    ) as network_guard:
        cache_steps = [
            controlled_search(
                cache_agent,
                cycle,
                source="d5_03_lru_cache",
                use_real_search=True,
            )
            for cycle in (0, 1)
        ]
    return {
        "cooldown_cycles": cooldown,
        "boundary": {
            "sandbox": boundary_sandbox,
            "initial_miss_cycle": boundary_start,
            "steps": boundary_steps,
        },
        "success_after_miss": {
            "sandbox": recovery_sandbox,
            "steps": recovery_steps,
        },
        "same_and_new_topics": {"sandbox": topics_sandbox, "steps": topic_steps},
        "lru_cache": {
            "sandbox": cache_sandbox,
            "cache_key": cache_key,
            "preloaded_response": memory_success_response(),
            "steps": cache_steps,
            "network_guard_call_count": network_guard.call_count,
            "observation_status": "observed_from_preloaded_cache_without_network",
        },
        "execution_mode": "controlled_direct_act_not_natural_arbitration",
        "real_network_used": False,
    }


def install_active_motivational_search(
    agent: DigitalBeing, *, near_completion: bool = False
) -> dict:
    """Создаёт настоящую цель мотивации и контрольно делает её активной."""
    curiosity = agent.motivation_system.needs["curiosity"]

    def choose_web_search(templates):
        return next(item for item in templates if item.get("action") == "web_search")

    with (
        patch.object(random, "choice", side_effect=choose_web_search),
        patch.object(
            agent.motivation_system, "_pick_relevant_concept", return_value="память"
        ),
    ):
        generated = agent.motivation_system.generate_goals(
            pressing_needs=[curiosity], active_drives=[]
        )
    agent._ingest_motivation_goals(generated)
    goal = next(
        item
        for item in agent.goals
        if item.get("motivation_origin", {}).get("action_hint") == "web_search"
    )
    if agent.active_goal is not None and agent.active_goal is not goal:
        agent.active_goal["status"] = "pending"
    goal["status"] = "active"
    agent.active_goal = goal
    agent.goal_subsystem.active_goal = goal
    if near_completion:
        progress = agent._goal_progress[goal["id"]]
        progress["matched_concepts"] = {"вопрос", "понимать", "знать", "обучение"}
        progress["percentage"] = 80
    candidate = active_goal_candidate(agent)
    return {
        "generated": deepcopy(generated),
        "goal": deepcopy(goal),
        "candidate": deepcopy(candidate),
        "activation_mode": "controlled_activation_of_real_motivation_goal",
        "near_completion_control": near_completion,
    }


def observe_d5_04() -> dict:
    cases = {}
    for case, controls in (
        ("success_without_goal", {"response": memory_success_response()}),
        ("search_miss", {"response": miss_response()}),
        ("disabled", {"response": memory_success_response(), "search_enabled": False}),
        ("denied", {"response": memory_success_response(), "denied": True}),
    ):
        sandbox = use_sandbox(f"d5_04/{case}")
        agent = new_agent(f"D5Feedback_{case}", without_active_goal=True)
        cases[case] = {
            "sandbox": sandbox,
            "action": controlled_search(agent, 0, source=f"d5_04_{case}", **controls),
        }

    for case, near_completion in (
        ("active_goal_step", False),
        ("active_goal_completion", True),
    ):
        sandbox = use_sandbox(f"d5_04/{case}")
        agent = new_agent(f"D5Feedback_{case}", without_active_goal=True)
        setup = install_active_motivational_search(
            agent, near_completion=near_completion
        )
        goal_id = setup["goal"]["id"]
        action = perform_action(
            agent,
            "web_search",
            intention=setup["candidate"],
            response=memory_success_response(),
        )
        cases[case] = {
            "sandbox": sandbox,
            "setup": setup,
            "action": action,
            "goal_after": deepcopy(
                next(item for item in agent.goals if item.get("id") == goal_id)
            ),
            "goal_history_after": deepcopy(agent.motivation_system.goal_history),
        }

    cooldown_sandbox = use_sandbox("d5_04/cooldown_no_effect")
    cooldown_agent = new_agent("D5FeedbackCooldown", without_active_goal=True)
    cooldown_steps = [
        controlled_search(
            cooldown_agent,
            70,
            source="d5_04_cooldown_initial_miss",
            response=miss_response(),
        ),
        controlled_search(
            cooldown_agent,
            71,
            source="d5_04_cooldown_no_effect",
            response=memory_success_response(),
        ),
    ]
    cases["cooldown_no_effect"] = {
        "sandbox": cooldown_sandbox,
        "steps": cooldown_steps,
        "action": cooldown_steps[-1],
    }

    provenance = {}
    for source in ("social", "active_goal", "intention_continuation", "direct"):
        sandbox = use_sandbox(f"d5_04/provenance_{source}")
        agent = new_agent(f"D5Provenance_{source}", without_active_goal=True)
        if source == "active_goal":
            setup = install_active_motivational_search(agent)
            intention = setup["candidate"]
        else:
            setup = None
            intention = search_intention(source)
        provenance[source] = {
            "sandbox": sandbox,
            "setup": setup,
            "action": perform_action(
                agent,
                "web_search",
                intention=intention,
                response=memory_success_response(),
            ),
        }

    explore_sandbox = use_sandbox("d5_04/explore_no_effect")
    explore_agent = new_agent("D5ExploreControl", without_active_goal=True)
    with patch.object(
        explore_agent,
        "_act_explore",
        return_value={"text": "Ответ: новых свидетельств нет", "target": "память"},
    ):
        explore = perform_action(
            explore_agent,
            "explore",
            intention=search_intention("d2r_no_effect_control"),
        )
    return {
        "cases": cases,
        "provenance": provenance,
        "explore_no_effect_control": {
            "sandbox": explore_sandbox,
            "action": explore,
            "control": "same_controlled_handler_as_D2-R_R03",
        },
        "execution_mode": "controlled_direct_act_not_natural_arbitration",
        "real_network_used": False,
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


def same_action_target(candidate: dict, selection: dict | None) -> bool:
    if not selection:
        return False
    return candidate.get("action") == selection.get("action") and candidate_target(
        candidate
    ) == candidate_target(selection)


def same_candidate_channel(candidate: dict, selection: dict | None) -> bool:
    return same_action_target(candidate, selection) and candidate.get(
        "source"
    ) == selection.get("source")


def observe_natural_tick(agent: DigitalBeing, *, response: dict | None = None) -> dict:
    """Прогоняет настоящий autonomous_tick, только копируя границы выбора."""
    captured: dict[str, Any] = {}
    motivation_method = UnifiedMotivationSystem.get_action_candidates
    tick_lines, tick_first_line = inspect.getsourcelines(autonomous_tick_impl)
    availability_offset = next(
        index
        for index, line in enumerate(tick_lines)
        if "candidate for candidate in candidates if self._is_candidate_available"
        in line
    )
    availability_line = tick_first_line + availability_offset

    def tracer(frame, event, arg):
        if frame.f_code is motivation_method.__code__:
            if event == "return":
                captured["motivation_pre_top5"] = deepcopy(frame.f_locals["candidates"])
                captured["motivation_post_top5"] = deepcopy(arg)
            return tracer
        if frame.f_code is autonomous_tick_impl.__code__:
            if event == "line" and frame.f_lineno == availability_line:
                captured["pre_availability"] = deepcopy(frame.f_locals["candidates"])
            return tracer
        return None

    real_choose = agent.decision_arbitrator.choose_action

    def observe_choice(candidates, context):
        captured["arbitrator_input"] = deepcopy(candidates)
        captured["arbitrator_context"] = deepcopy(context)
        selected = real_choose(candidates, context)
        captured["arbitrator_output"] = deepcopy(selected)
        return selected

    before_levels = all_levels(agent.motivation_system)
    before_world = asdict(capture(agent))
    before_energy = agent.energy
    previous_outcome = agent._last_action_outcome
    with ExitStack() as stack:
        search_mock = stack.enter_context(
            patch.object(
                agent.web_searcher,
                "search",
                return_value=deepcopy(response or memory_success_response()),
            )
        )
        network_guard = stack.enter_context(
            patch.object(
                agent.web_searcher,
                "_fetch",
                side_effect=RuntimeError("real network forbidden in D5"),
            )
        )
        stack.enter_context(
            patch.object(
                agent.decision_arbitrator,
                "choose_action",
                side_effect=observe_choice,
            )
        )
        interaction = getattr(agent, "user_interaction", None)
        if interaction is not None and callable(
            getattr(interaction, "send_message", None)
        ):
            stack.enter_context(
                patch.object(interaction, "send_message", return_value=None)
            )
        sys.settrace(tracer)
        try:
            report = agent.autonomous_tick()
        finally:
            sys.settrace(None)

    initial_choice = captured.get("arbitrator_output") or {}
    final_choice = report.get("arbitrator") or {}
    executed = report.get("executed_intention")
    pre_availability = captured.get("pre_availability") or []
    arbitrator_input = captured.get("arbitrator_input") or []
    proposed_web = [
        item
        for item in pre_availability
        if agent._normalize_action(item.get("action")) == "web_search"
    ]
    arbitrator_web = [
        item
        for item in arbitrator_input
        if agent._normalize_action(item.get("action")) == "web_search"
    ]
    channels = {}
    for source in (
        "motivation",
        "active_goal",
        "social",
        "intention_continuation",
    ):
        proposed = [item for item in proposed_web if item.get("source") == source]
        reached = [item for item in arbitrator_web if item.get("source") == source]
        channels[source] = {
            "proposed": candidate_metrics(proposed),
            "reached_arbitrator": candidate_metrics(reached),
            "selected_by_arbitrator": candidate_metrics(
                [
                    item
                    for item in reached
                    if same_candidate_channel(item, initial_choice)
                ]
            ),
            "executed": candidate_metrics(
                [item for item in reached if same_action_target(item, executed)]
            ),
        }

    outcome = agent._last_action_outcome
    after_levels = all_levels(agent.motivation_system)
    pre_top5 = captured.get("motivation_pre_top5") or []
    post_top5 = captured.get("motivation_post_top5") or []
    return {
        "execution_mode": "real_autonomous_tick_real_arbitrator_real_act",
        "capture": {
            "motivation": "sys.settrace return: sorted candidates and returned top-5",
            "pre_availability_line": availability_line,
            "arbitrator": "pass-through wrapper around real choose_action",
            "instrumentation_changes_strength_or_choice": False,
        },
        "cycle": report.get("cycle"),
        "motivation_pre_top5": candidate_metrics(pre_top5),
        "motivation_post_top5": candidate_metrics(post_top5),
        "motivation_dropped_by_top5": candidate_metrics(pre_top5[len(post_top5) :]),
        "pre_availability": candidate_metrics(pre_availability),
        "arbitrator_input": candidate_metrics(arbitrator_input),
        "arbitrator_context": captured.get("arbitrator_context"),
        "initial_arbitration": deepcopy(initial_choice),
        "final_arbitration": deepcopy(final_choice),
        "web_search_channels": channels,
        "continuation_proposal": deepcopy(report.get("continuation_proposal")),
        "continuation_supported_actions": sorted(CONTINUATION_ACTIONS),
        "executed_intention": deepcopy(executed),
        "autonomous_action": deepcopy(report.get("autonomous_action")),
        "action_refused": deepcopy(report.get("action_refused")),
        "loop_escape": deepcopy(report.get("loop_escape")),
        "outcome": outcome.as_dict() if outcome else None,
        "outcome_current_tick": (
            outcome.as_dict() if outcome is not previous_outcome and outcome else None
        ),
        "previous_outcome_before_tick": (
            previous_outcome.as_dict() if previous_outcome else None
        ),
        "search_queries": [call.args[0] for call in search_mock.call_args_list],
        "search_call_count": search_mock.call_count,
        "network_guard_call_count": network_guard.call_count,
        "real_search_network_used": False,
        "all_needs_before": before_levels,
        "all_needs_after": after_levels,
        "need_deltas": need_deltas(before_levels, after_levels),
        "world_before": before_world,
        "world_after": asdict(capture(agent)),
        "energy_before": before_energy,
        "energy_after": agent.energy,
        "intention_history": deepcopy(getattr(agent, "_intention_history", [])),
    }


def add_social_search_topic(agent: DigitalBeing, topic: str) -> dict:
    """Создаёт реальное exposure-событие без собственной формулировки темы."""
    node = agent.mental_models.encounter_concept(
        topic,
        context="D5-05 controlled social-topic setup",
        outcome="Тема встречена, но собственного определения ещё нет",
    )
    return {
        "topic": topic,
        "definition_hypothesis": node.definition_hypothesis,
        "experience_count": len(node.experiences),
        "setup_mode": "real_mental_model_exposure_control",
    }


def clear_active_goal(agent: DigitalBeing) -> None:
    if agent.active_goal is not None:
        agent.active_goal["status"] = "pending"
    agent.active_goal = None
    agent.goal_subsystem.active_goal = None


def observe_d5_05() -> dict:
    cases = {}

    sandbox = use_sandbox("d5_05/pressing_curiosity")
    agent = new_agent("D5PressingCuriosity", without_active_goal=True)
    cases["pressing_curiosity"] = {
        "sandbox": sandbox,
        "setup": {"curiosity": need_state(agent.motivation_system)},
        "tick": observe_natural_tick(agent),
    }

    sandbox = use_sandbox("d5_05/active_goal")
    agent = new_agent("D5ActiveGoalSelection", without_active_goal=True)
    setup = install_active_motivational_search(agent)
    satisfy_all(agent.motivation_system)
    cases["active_goal"] = {
        "sandbox": sandbox,
        "setup": setup,
        "tick": observe_natural_tick(agent),
    }

    sandbox = use_sandbox("d5_05/social")
    agent = new_agent(
        "D5SocialSelection", low_curiosity=False, without_active_goal=True
    )
    setup = add_social_search_topic(agent, "память")
    cases["social"] = {
        "sandbox": sandbox,
        "setup": setup,
        "tick": observe_natural_tick(agent),
    }

    sandbox = use_sandbox("d5_05/disabled")
    agent = new_agent("D5DisabledSelection", without_active_goal=True)
    setup = install_active_motivational_search(agent)
    satisfy_all(agent.motivation_system)
    agent.web_searcher.toggle(False)
    cases["disabled"] = {
        "sandbox": sandbox,
        "setup": setup,
        "search_enabled": agent.web_searcher.is_enabled,
        "tick": observe_natural_tick(agent),
    }

    sandbox = use_sandbox("d5_05/continuation")
    agent = new_agent("D5ContinuationSelection", without_active_goal=True)
    setup = install_active_motivational_search(agent)
    satisfy_all(agent.motivation_system)
    first = observe_natural_tick(agent)
    history_before_second = deepcopy(agent._intention_history)
    clear_active_goal(agent)
    agent.cycle_count = 1
    second = observe_natural_tick(agent)
    cases["continuation"] = {
        "sandbox": sandbox,
        "setup": setup,
        "first_tick": first,
        "history_before_second": history_before_second,
        "second_tick": second,
        "control": "active goal removed after the first real selected search",
    }

    sandbox = use_sandbox("d5_05/competition")
    agent = new_agent("D5Competition", without_active_goal=True)
    goal_setup = install_active_motivational_search(agent)
    social_setup = add_social_search_topic(agent, "внимание")
    agent.motivation_system.needs["autonomy"].current_level = 0.1
    agent.motivation_system.needs["play"].current_level = 0.05
    for drive in agent.motivation_system.drives.values():
        drive.calculate_intensity(agent.motivation_system.needs)
    agent.interoception.state.fatigue = 0.95
    cases["competition"] = {
        "sandbox": sandbox,
        "setup": {
            "active_goal": goal_setup,
            "social": social_setup,
            "needs": all_levels(agent.motivation_system),
            "drives": {
                name: drive.current_level
                for name, drive in agent.motivation_system.drives.items()
            },
            "fatigue": agent.interoception.state.fatigue,
        },
        "tick": observe_natural_tick(agent),
    }

    return {
        "cases": cases,
        "execution_mode": "real_autonomous_tick_real_arbitrator_real_act",
        "real_network_used": False,
        "limitation": (
            "Controlled setup supplies needs, goals, exposure and fatigue; "
            "candidate generation, filtering, arbitration and execution are real."
        ),
    }


def restart_state_metrics(agent: DigitalBeing) -> dict:
    active_goal = agent.active_goal
    return {
        "open_questions": deepcopy(agent.get_open_questions()),
        "answered_flags": {
            item.get("text"): item.get("answered")
            for item in agent.get_open_questions()
        },
        "mental_models": concept_metrics(agent),
        "active_goal": (
            {
                "id": active_goal.get("id"),
                "title": active_goal.get("title"),
                "status": active_goal.get("status"),
            }
            if active_goal is not None
            else None
        ),
        "exploration_history": deepcopy(getattr(agent, "_exploration_history", [])),
        "needs": all_levels(agent.motivation_system),
        "hunt_misses": deepcopy(getattr(agent, "_hunt_misses", {})),
    }


def observe_d5_06() -> dict:
    sandbox_a = use_sandbox("d5_06/life_a")
    first = new_agent("D5LifeA", without_active_goal=True)
    decomposition = perform_action(
        first,
        "decomposition",
        intention={
            "source": "d5_06_open_question_setup",
            "params": {"target": "нейросеть архитектура"},
        },
    )
    mental_setup = add_social_search_topic(first, "память")
    goal_setup = install_active_motivational_search(first)
    miss = controlled_search(
        first,
        10,
        source="d5_06_before_restart_miss",
        response=miss_response(),
    )
    for index, need in enumerate(first.motivation_system.needs.values()):
        need.current_level = 0.111 + index * 0.061
    before = restart_state_metrics(first)

    restored = None
    after = None
    repeat = None
    restore_error = None
    checkpoint_path = None
    try:
        checkpoint_path = first.save_state(force=True)
        if checkpoint_path is None:
            raise RuntimeError("D5-06 checkpoint save returned None")
        snapshot = CheckpointSerializer().load(checkpoint_path)
        restored = new_agent("D5LifeARestarted", without_active_goal=True)
        apply_state_to_agent(restored, snapshot)
        after = restart_state_metrics(restored)
        repeat = controlled_search(
            restored,
            restored.cycle_count + 1,
            source="d5_06_after_restart_success",
            response=memory_success_response(),
        )
    except Exception as exc:  # недоступный restore фиксируется без имитации
        restore_error = f"{type(exc).__name__}: {exc}"

    compared_fields = (
        "open_questions",
        "answered_flags",
        "mental_models",
        "active_goal",
        "exploration_history",
        "needs",
    )
    comparisons = (
        {field: before[field] == after[field] for field in compared_fields}
        if after is not None
        else None
    )

    sandbox_b = use_sandbox("d5_06/life_b")
    second = new_agent("D5LifeB", low_curiosity=False, without_active_goal=True)
    second_state = restart_state_metrics(second)
    isolation = {
        "first_open_question_absent": all(
            item.get("text") != TARGET for item in second_state["open_questions"]
        ),
        "first_mental_topic_absent": "память" not in second_state["mental_models"],
        "active_goal_absent": second_state["active_goal"] is None,
        "needs_differ_from_first": second_state["needs"] != before["needs"],
        "exploration_history_empty": not second_state["exploration_history"],
        "hunt_misses_empty": not second_state["hunt_misses"],
    }
    return {
        "sandbox_life_a": sandbox_a,
        "sandbox_life_b": sandbox_b,
        "observation_status": "not_observed" if restore_error else "observed",
        "restore_error": restore_error,
        "checkpoint_path": str(checkpoint_path) if checkpoint_path else None,
        "setup": {
            "decomposition": decomposition,
            "mental_model": mental_setup,
            "active_goal": goal_setup,
            "miss": miss,
        },
        "before_restart": before,
        "after_restart": after,
        "after_repeat_search": (
            restart_state_metrics(restored) if restored is not None else None
        ),
        "field_comparisons": comparisons,
        "hunt_trace_erased": (
            bool(before["hunt_misses"]) and not after["hunt_misses"]
            if after is not None
            else None
        ),
        "repeat_search": repeat,
        "second_life": second_state,
        "second_life_isolation": isolation,
        "execution_mode": "real_save_load_restore_and_controlled_direct_act",
        "real_network_used": False,
    }


def observe_d5_07() -> dict:
    sandbox = use_sandbox("d5_07/end_to_end")
    agent = new_agent("D5EndToEnd", without_active_goal=True)
    decomposition = perform_action(
        agent,
        "decomposition",
        intention={
            "source": "d5_07_controlled_decomposition",
            "params": {"target": "нейросеть архитектура"},
        },
    )
    questions = deepcopy(agent.get_open_questions())
    selected_target = next(
        (item.get("text") for item in questions if item.get("text") == TARGET),
        None,
    )
    social_setup = (
        add_social_search_topic(agent, selected_target)
        if selected_target is not None
        else None
    )
    satisfy_all(agent.motivation_system)

    agent.cycle_count = 0
    initial_miss = observe_natural_tick(agent, response=miss_response())
    agent.cycle_count = 1
    before_cooldown = observe_natural_tick(agent, response=SUCCESS_RESPONSE)
    agent.cycle_count = int(LR_CONFIG.HUNT_MISS_COOLDOWN_CYCLES)
    at_cooldown = observe_natural_tick(agent, response=miss_response())
    before_restart = restart_state_metrics(agent)

    restored = None
    after_restart = None
    restart_repeat = None
    restore_error = None
    checkpoint_path = None
    try:
        checkpoint_path = agent.save_state(force=True)
        if checkpoint_path is None:
            raise RuntimeError("D5-07 checkpoint save returned None")
        snapshot = CheckpointSerializer().load(checkpoint_path)
        restored = new_agent("D5EndToEndRestarted", without_active_goal=True)
        apply_state_to_agent(restored, snapshot)
        after_restart = restart_state_metrics(restored)
        restart_repeat = controlled_search(
            restored,
            restored.cycle_count + 1,
            source="d5_07_controlled_after_restart",
            target=selected_target or TARGET,
            response=SUCCESS_RESPONSE,
        )
    except Exception as exc:  # недоступный restore фиксируется без имитации
        restore_error = f"{type(exc).__name__}: {exc}"

    previous_miss = before_restart["hunt_misses"].get(selected_target)
    repeat_cycle = restart_repeat.get("cycle_count") if restart_repeat else None
    return {
        "sandbox": sandbox,
        "observation_status": "not_observed" if restore_error else "observed",
        "restore_error": restore_error,
        "decomposition": {
            "execution_mode": "controlled_direct_act",
            "action": decomposition,
            "open_questions": questions,
            "selected_subquestion": selected_target,
        },
        "social_setup": social_setup,
        "initial_natural_miss": initial_miss,
        "natural_repeat_before_cooldown": before_cooldown,
        "natural_repeat_at_cooldown": at_cooldown,
        "before_restart": before_restart,
        "checkpoint_path": str(checkpoint_path) if checkpoint_path else None,
        "after_restart": after_restart,
        "restart_repeat": restart_repeat,
        "restart_repeat_within_former_cooldown": (
            repeat_cycle - previous_miss < int(LR_CONFIG.HUNT_MISS_COOLDOWN_CYCLES)
            if previous_miss is not None and repeat_cycle is not None
            else None
        ),
        "natural_execution_mode": "real_autonomous_tick_real_arbitrator_real_act",
        "restart_repeat_execution_mode": "controlled_direct_act_not_natural_arbitration",
        "real_network_used": False,
    }


def main() -> None:
    OBSERVATION_ROOT.mkdir(parents=True, exist_ok=True)
    live_before = repo_data_manifest()
    result = {
        "schema": "d5_curiosity_observation_v1",
        "scope": [
            "D5-00",
            "D5-01",
            "D5-02",
            "D5-03",
            "D5-04",
            "D5-05",
            "D5-06",
            "D5-07",
        ],
        "revision": git_output(["rev-parse", "HEAD"]),
        "dirty_state_before": git_output(["status", "--short"]).splitlines(),
        "production_tracked_diff_before": git_output(
            ["diff", "--name-only", "--", "src", "config"]
        ).splitlines(),
        "seed": SEED,
        "constants": {
            "HUNT_MISS_COOLDOWN_CYCLES": LR_CONFIG.HUNT_MISS_COOLDOWN_CYCLES,
            "EXPLORATION_DEPTH_RATIO": LR_CONFIG.EXPLORATION_DEPTH_RATIO,
            "GOAL_PROGRESS_ENABLED": LR_CONFIG.GOAL_PROGRESS_ENABLED,
            "PROGRESS_KNOWLEDGE_MATCHES": LR_CONFIG.PROGRESS_KNOWLEDGE_MATCHES,
            "MIN_PROGRESS_INCREMENT": LR_CONFIG.MIN_PROGRESS_INCREMENT,
        },
        "observation_root": str(OBSERVATION_ROOT),
        "d5_00": observe_d5_00(),
        "d5_01": observe_d5_01(),
        "d5_02": observe_d5_02(),
        "d5_03": observe_d5_03(),
        "d5_04": observe_d5_04(),
        "d5_05": observe_d5_05(),
        "d5_06": observe_d5_06(),
        "d5_07": observe_d5_07(),
    }
    live_after = repo_data_manifest()
    result["live_data_unchanged"] = live_before == live_after
    result["live_data_files_observed"] = len(live_before)
    result["production_tracked_diff_after"] = git_output(
        ["diff", "--name-only", "--", "src", "config"]
    ).splitlines()
    output = OBSERVATION_ROOT / "results_d5_00_07.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "revision": result["revision"],
                "scope": result["scope"],
                "baseline_identical": result["d5_00"]["identical_metrics"],
                "d5_01_selected_target": result["d5_01"]["decomposition"][
                    "selected_target"
                ],
                "d5_02_cases": list(result["d5_02"]["cases"]),
                "d5_03_search_calls": [
                    step["action"]["search_call_count"]
                    for step in result["d5_03"]["boundary"]["steps"]
                ],
                "d5_04_cases": list(result["d5_04"]["cases"]),
                "d5_05_cases": {
                    name: {
                        "selected": case["tick"]["initial_arbitration"].get("action"),
                        "source": case["tick"]["initial_arbitration"].get("source"),
                        "search_calls": case["tick"]["search_call_count"],
                    }
                    for name, case in result["d5_05"]["cases"].items()
                    if "tick" in case
                },
                "d5_05_continuation_second": {
                    "proposal": result["d5_05"]["cases"]["continuation"]["second_tick"][
                        "continuation_proposal"
                    ],
                    "search_calls": result["d5_05"]["cases"]["continuation"][
                        "second_tick"
                    ]["search_call_count"],
                },
                "d5_06": {
                    "status": result["d5_06"]["observation_status"],
                    "field_comparisons": result["d5_06"]["field_comparisons"],
                    "hunt_trace_erased": result["d5_06"]["hunt_trace_erased"],
                    "repeat_search_calls": (
                        result["d5_06"]["repeat_search"]["search_call_count"]
                        if result["d5_06"]["repeat_search"]
                        else None
                    ),
                    "second_life_isolation": result["d5_06"]["second_life_isolation"],
                },
                "d5_07": {
                    "selected_target": result["d5_07"]["decomposition"][
                        "selected_subquestion"
                    ],
                    "natural": {
                        name: {
                            "selected": tick["initial_arbitration"].get("action"),
                            "source": tick["initial_arbitration"].get("source"),
                            "target": candidate_target(tick["initial_arbitration"]),
                            "search_calls": tick["search_call_count"],
                        }
                        for name, tick in (
                            (
                                "initial_miss",
                                result["d5_07"]["initial_natural_miss"],
                            ),
                            (
                                "before_cooldown",
                                result["d5_07"]["natural_repeat_before_cooldown"],
                            ),
                            (
                                "at_cooldown",
                                result["d5_07"]["natural_repeat_at_cooldown"],
                            ),
                        )
                    },
                    "restart_status": result["d5_07"]["observation_status"],
                    "restart_repeat_calls": (
                        result["d5_07"]["restart_repeat"]["search_call_count"]
                        if result["d5_07"]["restart_repeat"]
                        else None
                    ),
                },
                "live_data_unchanged": result["live_data_unchanged"],
                "production_tracked_diff_after": result[
                    "production_tracked_diff_after"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
