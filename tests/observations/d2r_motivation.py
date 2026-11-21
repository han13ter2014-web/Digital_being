"""D2-R: уточняющие наблюдения мотивации после decision gate D3.

Запуск из корня проекта:
    .venv/Scripts/python.exe tests/observations/d2r_motivation.py

Скрипт не задаёт желаемое поведение assertion-ами и не исправляет production-код.
Фактические метрики сохраняются в tmp/motivation_d2r/results.json.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import random
import subprocess
import sys
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_ROOT = PROJECT_ROOT / "tmp" / "motivation_d2r"
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

from src.cognition.creative_catalog import perform_creative  # noqa: E402
from src.core.agent import DigitalBeing  # noqa: E402
from src.core.agent_act import classify_decision  # noqa: E402
from src.core.motivation.unified_motivation import (  # noqa: E402
    DEFAULT_NEEDS,
    UnifiedMotivationSystem,
    create_motivation_system,
)
from src.core.subsystems.decision_arbitrator import DecisionArbitrator  # noqa: E402

SEED = 20261121
R01_ACTIONS = {
    "curiosity": "web_search",
    "competence": "synthesis",
    "autonomy": "set_own_goal",
    "connection": "user_answer",
    "play": "create_draft",
    "meaning": "reflection",
    "coherence": "repair",
}
R01_EXECUTORS = {
    "curiosity": (
        "DigitalBeing.act → _act_web_search → WebSearcher.search "
        "→ knowledge_base/_known_definitions"
    ),
    "competence": (
        "DigitalBeing.act → _act_synthesize → mental_models.encounter_concept"
    ),
    "autonomy": "DigitalBeing.act → _act_set_own_goal → set_goal",
    "connection": (
        "DigitalBeing.act(user_answer) → classify as communicate → "
        "_act_communicate → UserInteraction.send_message"
    ),
    "play": "DigitalBeing.act → perform_creative → creative catalog revision",
    "meaning": "DigitalBeing.act → _act_reflect → reflect; confirmed_result не задан",
    "coherence": (
        "DigitalBeing.act → StructuralIntegrity.manual_repair → confirmed_result"
    ),
}


class ObservationAgent:
    """Минимальный владелец UnifiedMotivationSystem без живого профиля."""

    def __init__(self):
        self.cycle_count = 1
        self.knowledge_base = {"python": "language", "память": "concept"}
        self.beliefs = {}
        self.goals = []


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


def candidate_key(item: dict) -> tuple:
    return (
        item.get("type"),
        item.get("need"),
        item.get("drive"),
        item.get("action"),
    )


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


def current_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def new_action_agent(name: str, target_need: str) -> DigitalBeing:
    random.seed(SEED)
    agent = DigitalBeing(name=name)
    satisfy_all(agent.motivation_system)
    agent.motivation_system.needs[target_need].current_level = 0.1
    agent._last_action_outcome = None
    return agent


def seed_concept(agent: DigitalBeing, name: str = "память", definition: str = ""):
    agent.mental_models.encounter_concept(
        name,
        "d2r_controlled_setup",
        definition,
        evidence_kind="testimony",
        source="d2r:controlled_setup",
    )
    return agent.mental_models.concepts[name]


def action_intention(action: str, case: str) -> dict | None:
    if action in {"web_search", "synthesis"}:
        return {"source": "d2r", "params": {"target": "память"}}
    if action == "create_draft":
        if case == "no_effect":
            return {
                "source": "d2r",
                "params": {"draft_mode": "leave", "reason": "контроль без награды"},
            }
        return {"source": "d2r", "params": {"draft_mode": "new"}}
    return None


def prepare_action_case(
    agent: DigitalBeing, action: str, case: str, stack: ExitStack
) -> None:
    if case == "denied":
        agent.energy = 0.0
        return
    if action == "web_search":
        if case == "positive":
            agent.web_searcher.toggle(True)
            stack.enter_context(
                patch.object(
                    agent.web_searcher,
                    "search",
                    return_value={
                        "found": True,
                        "title": "Память",
                        "extract": (
                            "Память — это процесс сохранения и последующего "
                            "восстановления сведений, поддерживающий обучение."
                        ),
                    },
                )
            )
        else:
            agent.web_searcher.toggle(False)
    elif action == "synthesis" and case == "positive":
        seed_concept(agent, "память")
        seed_concept(agent, "обучение")
        agent.mental_models.concepts["память"].connect_to("обучение", 0.8)
    elif action == "set_own_goal":
        target = "память" if case == "positive" else None
        stack.enter_context(
            patch.object(agent, "_pick_exploration_target", return_value=target)
        )
    elif action == "user_answer":
        if case == "positive":
            seed_concept(
                agent,
                definition="Память сохраняет сведения и позволяет использовать их позже.",
            )
        else:
            agent.mental_models.concepts.clear()
    elif action == "create_draft" and case == "no_effect":
        perform_creative(agent, "new")
    elif action == "reflection":
        patterns = (
            [{"description": "контрольный паттерн", "confidence": 0.8}]
            if case == "positive"
            else []
        )
        stack.enter_context(
            patch.object(agent, "reflect", return_value={"patterns": patterns})
        )
    elif action == "repair" and case == "positive":
        agent.death_risk.integrity.cognitive_coherence = 0.5


def run_action_case(need_name: str, case: str) -> dict:
    action = R01_ACTIONS[need_name]
    sandbox = use_sandbox(f"r01/{need_name}/{case}")
    agent = new_action_agent(f"D2R_{need_name}_{case}", need_name)
    before = all_levels(agent.motivation_system)
    feedback = {}
    real_feedback = agent.motivation_system.on_action_result

    def observe_feedback(action_type, success, valence):
        feedback.update(
            {"action_type": action_type, "success": success, "valence": valence}
        )
        return real_feedback(action_type, success, valence)

    error = None
    result_text = None
    with ExitStack() as stack:
        prepare_action_case(agent, action, case, stack)
        before = all_levels(agent.motivation_system)
        stack.enter_context(
            patch.object(
                agent.motivation_system,
                "on_action_result",
                side_effect=observe_feedback,
            )
        )
        try:
            result_text = agent.act(action, intention=action_intention(action, case))
        except Exception as exc:  # наблюдение фиксирует сбой, не подменяет исход
            error = f"{type(exc).__name__}: {exc}"
    after = all_levels(agent.motivation_system)
    outcome = agent._last_action_outcome
    return {
        "sandbox": sandbox,
        "requested_action": action,
        "classified_action": classify_decision(action),
        "case": case,
        "result_text": result_text,
        "error": error,
        "observation_status": "not_observed" if error else "observed",
        "outcome": outcome.as_dict() if outcome else None,
        "world_evidence": bool(outcome and outcome.had_effect),
        "motivation_feedback": feedback or None,
        "need_deltas": need_deltas(before, after),
    }


def observe_r01() -> dict:
    return {
        need_name: {
            "need": need_name,
            "control_action": action,
            "executor": R01_EXECUTORS[need_name],
            "cases": {
                case: run_action_case(need_name, case)
                for case in ("positive", "no_effect", "denied")
            },
        }
        for need_name, action in R01_ACTIONS.items()
    }


def exact_need_state(need) -> dict:
    return {
        "current_level": need.current_level,
        "current_level_repr": repr(need.current_level),
        "base_level": need.base_level,
        "threshold": need.threshold,
        "priority": need.priority,
        "pressing": need.is_pressing(),
        "pressure": need.pressure(),
        "urgency": need.urgency(),
    }


def status_case(name: str, levels: dict[str, float]) -> dict:
    sandbox = use_sandbox(f"r02/{name}")
    system = create_motivation_system(ObservationAgent())
    satisfy_all(system)
    for need_name, level in levels.items():
        system.needs[need_name].current_level = level
    status = system.get_status()
    most = system.get_most_pressing_need()
    return {
        "sandbox": sandbox,
        "injected_levels": levels,
        "needs": {
            need_name: exact_need_state(need)
            for need_name, need in system.needs.items()
        },
        "status_most_pressing_need": status["most_pressing_need"],
        "status_pressing_needs": status["pressing_needs"],
        "get_most_pressing_need": most.name if most else None,
    }


def source_references(needle: str) -> list[dict]:
    references = []
    current_file = Path(__file__).resolve()
    for root_name in ("src", "tests", "tools"):
        for path in sorted((PROJECT_ROOT / root_name).rglob("*.py")):
            if path.resolve() == current_file:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(lines, 1):
                if needle in line:
                    references.append(
                        {
                            "path": str(path.relative_to(PROJECT_ROOT)),
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
    return references


def observe_r02() -> dict:
    return {
        "states": {
            "no_pressing": status_case("no_pressing", {}),
            "one_pressing": status_case("one_pressing", {"curiosity": 0.1}),
            "several_pressing": status_case(
                "several_pressing",
                {"curiosity": 0.1, "meaning": 0.1, "autonomy": 0.1},
            ),
            "equal_urgency": status_case(
                "equal_urgency", {"competence": 0.0, "coherence": 0.0}
            ),
        },
        "consumers": {
            "motivation_system.get_status()": source_references(
                "motivation_system.get_status()"
            ),
            "get_most_pressing_need()": source_references(".get_most_pressing_need()"),
            "status most_pressing_need": source_references(
                'motivation.get("most_pressing_need")'
            ),
            "status pressing_needs": source_references(
                'motivation.get("pressing_needs")'
            ),
        },
    }


def run_explore_case(case: str) -> dict:
    sandbox = use_sandbox(f"r03/{case}")
    random.seed(SEED)
    agent = DigitalBeing(name=f"D2RExplore_{case}")
    satisfy_all(agent.motivation_system)
    agent.motivation_system.needs["curiosity"].current_level = 0.5
    agent.motivation_system.needs["autonomy"].current_level = 0.5
    agent._last_action_outcome = None
    intention = {"source": "d2r_no_goal", "params": {"target": "память"}}
    own_goal = None
    if case == "own_goal":
        goal_id = agent.set_goal("Собственное исследование: память", difficulty=1)
        own_goal = next(
            (goal for goal in agent.goals if goal.get("id") == goal_id), None
        )
        intention = {
            "source": "own_goal",
            "params": {"target": "память", "goal_id": goal_id},
        }
    elif case == "external_instruction":
        intention = {"source": "user", "params": {"target": "память"}}
    elif case == "no_effect":
        intention = {"source": "d2r_control", "params": {"target": "память"}}
    elif case == "denied":
        agent.energy = 0.0
        intention = {"source": "own_goal", "params": {"target": "память"}}

    before = all_levels(agent.motivation_system)
    feedback = {}
    real_feedback = agent.motivation_system.on_action_result

    def observe_feedback(action_type, success, valence):
        feedback.update(
            {"action_type": action_type, "success": success, "valence": valence}
        )
        return real_feedback(action_type, success, valence)

    error = None
    result_text = None
    with (
        patch.object(
            agent,
            "_act_explore",
            return_value={"text": "Ответ: новых свидетельств нет", "target": "память"},
        ),
        patch.object(
            agent.motivation_system,
            "on_action_result",
            side_effect=observe_feedback,
        ),
    ):
        try:
            result_text = agent.act("explore", intention=intention)
        except Exception as exc:  # наблюдение фиксирует сбой, не подменяет исход
            error = f"{type(exc).__name__}: {exc}"
    after = all_levels(agent.motivation_system)
    outcome = agent._last_action_outcome
    return {
        "sandbox": sandbox,
        "case": case,
        "intention": intention,
        "own_goal": deepcopy(own_goal),
        "result_text": result_text,
        "error": error,
        "observation_status": "not_observed" if error else "observed",
        "outcome": outcome.as_dict() if outcome else None,
        "motivation_feedback": feedback or None,
        "all_need_deltas": need_deltas(before, after),
    }


def observe_r03() -> dict:
    return {
        case: run_explore_case(case)
        for case in (
            "own_goal",
            "no_own_goal",
            "external_instruction",
            "no_effect",
            "denied",
        )
    }


def candidates_with_pre_sort_trace(system: UnifiedMotivationSystem) -> dict:
    method = UnifiedMotivationSystem.get_action_candidates
    source_lines, first_line = inspect.getsourcelines(method)
    sort_offset = next(
        index for index, line in enumerate(source_lines) if "candidates.sort" in line
    )
    sort_line = first_line + sort_offset
    captured = {"pre_sort": None}

    def tracer(frame, event, arg):
        if frame.f_code is not method.__code__:
            return None
        if event == "line" and frame.f_lineno == sort_line:
            captured["pre_sort"] = deepcopy(frame.f_locals["candidates"])
        return tracer

    sys.settrace(tracer)
    try:
        final = system.get_action_candidates({})
    finally:
        sys.settrace(None)
    return {
        "capture_method": "sys.settrace: фактический locals перед candidates.sort",
        "source_sort_line": sort_line,
        "pre_sort": captured["pre_sort"],
        "post_top5": final,
    }


def observe_r04() -> dict:
    sandbox = use_sandbox("r04/top5")
    random.seed(SEED)
    system = create_motivation_system(ObservationAgent())
    satisfy_all(system)
    system.needs["curiosity"].current_level = 0.1
    system.needs["autonomy"].current_level = 0.1
    system.needs["play"].current_level = 0.05
    for drive in system.drives.values():
        drive.calculate_intensity(system.needs)
    pressing = [need for need in system.needs.values() if need.is_pressing()]
    active_drives = [drive for drive in system.drives.values() if drive.is_active()]
    traced = candidates_with_pre_sort_trace(system)
    pre_sort = traced["pre_sort"]
    post_top5 = traced["post_top5"]
    choice = DecisionArbitrator().choose_action(
        deepcopy(post_top5), {"simulation_mode": "shadow"}
    )
    generated = system.generate_goals(pressing, active_drives)

    remaining = Counter(candidate_key(item) for item in post_top5)
    dropped = []
    for item in pre_sort or []:
        key = candidate_key(item)
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            dropped.append(item)
    final_drive_names = {
        item.get("drive") for item in post_top5 if item.get("drive") is not None
    }
    return {
        "sandbox": sandbox,
        "executed": False,
        "capture_method": traced["capture_method"],
        "source_sort_line": traced["source_sort_line"],
        "pressing_needs": [need.name for need in pressing],
        "active_drives_before": {
            drive.name: drive.current_level for drive in active_drives
        },
        "pre_sort": candidate_metrics(pre_sort or []),
        "post_top5": candidate_metrics(post_top5),
        "dropped_by_top5": candidate_metrics(dropped),
        "active_drives_absent_from_top5": [
            drive.name for drive in active_drives if drive.name not in final_drive_names
        ],
        "after_arbitration_not_executed": choice,
        "subsequent_generated_goals": [
            {
                "title": goal.get("title"),
                "need": goal.get("need"),
                "drive": goal.get("drive"),
                "action_hint": goal.get("action_hint"),
                "priority": goal.get("priority"),
            }
            for goal in generated
        ],
    }


def observe_r05() -> dict:
    observations = {}
    for name in DEFAULT_NEEDS:
        sandbox = use_sandbox(f"r05/{name}")
        system = create_motivation_system(ObservationAgent())
        need = system.needs[name]
        need.current_level = need.base_level
        expected_ticks = (
            math.floor((need.base_level - need.threshold) / need.decay_rate) + 1
        )
        initial = exact_need_state(need)
        history = []
        ticks = 0
        while not need.is_pressing() and ticks <= 1000:
            need.tick()
            ticks += 1
            history.append(
                {
                    "tick": ticks,
                    "level": need.current_level,
                    "level_repr": repr(need.current_level),
                    "threshold": need.threshold,
                    "level_minus_threshold": need.current_level - need.threshold,
                    "strict_less_than_threshold": need.current_level < need.threshold,
                    "pressing": need.is_pressing(),
                }
            )
        first_pressing = history[-1] if history else None
        previous = history[-2] if len(history) >= 2 else None
        observations[name] = {
            "sandbox": sandbox,
            "initial": initial,
            "decay_rate": need.decay_rate,
            "expected_ticks_floor_plus_1_precomputed": expected_ticks,
            "actual_ticks": ticks,
            "matches_precomputed": ticks == expected_ticks,
            "last_non_pressing": previous,
            "first_pressing": first_pressing,
            "near_threshold_history": history[-3:],
        }
    return observations


def main() -> None:
    OBSERVATION_ROOT.mkdir(parents=True, exist_ok=True)
    live_before = repo_data_manifest()
    result = {
        "schema": "d2r_motivation_observation_v1",
        "revision": current_revision(),
        "seed": SEED,
        "observation_root": str(OBSERVATION_ROOT),
        "r01": observe_r01(),
        "r02": observe_r02(),
        "r03": observe_r03(),
        "r04": observe_r04(),
        "r05": observe_r05(),
    }
    live_after = repo_data_manifest()
    result["live_data_unchanged"] = live_before == live_after
    result["live_data_files_observed"] = len(live_before)
    output = OBSERVATION_ROOT / "results.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "revision": result["revision"],
                "r01_needs": len(result["r01"]),
                "r02_states": len(result["r02"]["states"]),
                "r03_cases": len(result["r03"]),
                "r04_pre_sort": len(result["r04"]["pre_sort"]),
                "r04_post_top5": len(result["r04"]["post_top5"]),
                "r05_needs": len(result["r05"]),
                "live_data_unchanged": result["live_data_unchanged"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
