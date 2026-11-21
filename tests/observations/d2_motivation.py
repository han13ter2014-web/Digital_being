"""D2: воспроизводимые наблюдения мотивации без изменения production-кода.

Запуск из корня проекта:
    .venv/Scripts/python.exe tests/observations/d2_motivation.py

Скрипт не проверяет желаемое поведение assertion-ами и не исправляет
расхождения. Он сохраняет фактические метрики в tmp/motivation_d2/results.json.
"""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_ROOT = PROJECT_ROOT / "tmp" / "motivation_d2"
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

from src.core.agent import DigitalBeing  # noqa: E402
from src.core.checkpoint_serializer import (  # noqa: E402
    CheckpointSerializer,
    apply_state_to_agent,
)
from src.core.motivation.unified_motivation import (  # noqa: E402
    DEFAULT_DRIVES,
    DEFAULT_NEEDS,
    UnifiedMotivationSystem,
    create_motivation_system,
)
from src.core.subsystems.decision_arbitrator import DecisionArbitrator  # noqa: E402

NEED_ACTIONS = {
    "curiosity": "web_search",
    "competence": "synthesis",
    "autonomy": "set_own_goal",
    "connection": "user_answer",
    "play": "create_draft",
    "meaning": "reflection",
    "coherence": "repair",
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


def new_system() -> UnifiedMotivationSystem:
    return create_motivation_system(ObservationAgent())


def satisfy_all(system: UnifiedMotivationSystem) -> None:
    for need in system.needs.values():
        need.current_level = need.base_level
    for drive in system.drives.values():
        drive.current_level = 0.0


def need_metrics(need) -> dict:
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


def all_levels(system: UnifiedMotivationSystem) -> dict[str, float]:
    return {name: need.current_level for name, need in system.needs.items()}


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


def close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)


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


def baseline_run(seed: int) -> dict:
    random.seed(seed)
    system = new_system()
    tick = system.tick({})
    candidates = system.get_action_candidates({})
    return {
        "seed": seed,
        "cycles": 1,
        "initial_levels": dict(DEFAULT_NEEDS_LEVELS),
        "tick": tick,
        "levels_after": all_levels(system),
        "candidates": candidate_metrics(candidates),
        "status": system.get_status(),
    }


def observe_m00() -> dict:
    sandbox = use_sandbox("m00_baseline")
    first = baseline_run(20261120)
    second = baseline_run(20261120)
    return {
        "sandbox": sandbox,
        "first": first,
        "second": second,
        "identical_metrics": first == second,
    }


def observe_needs() -> dict[str, dict]:
    observations = {}
    for name in DEFAULT_NEEDS:
        sandbox = use_sandbox(f"m01_m02_{name}")
        system = new_system()
        need = system.needs[name]
        need.current_level = need.base_level
        initial = need_metrics(need)
        expected_ticks = (
            math.floor((need.base_level - need.threshold) / need.decay_rate) + 1
        )
        ticks = 0
        while not need.is_pressing() and ticks <= 1000:
            need.tick()
            ticks += 1
        pressing_metrics = need_metrics(need)
        pressing_candidates = system.get_action_candidates({})
        need_candidate_present = any(
            item.get("need") == name and item.get("type") == "need_driven"
            for item in pressing_candidates
        )

        before_outcome = all_levels(system)
        before = need.current_level
        action = NEED_ACTIONS[name]
        system.on_action_result(action, True, 0.8)
        after = need.current_level
        expected_after = before + 0.4 * (1.0 - before)
        final_candidates = system.get_action_candidates({})
        observations[name] = {
            "sandbox": sandbox,
            "return": {
                "initial": initial,
                "expected_ticks_from_constants": expected_ticks,
                "actual_ticks": ticks,
                "matches_precomputed_ticks": ticks == expected_ticks,
                "final": pressing_metrics,
                "candidate_present": need_candidate_present,
                "candidates": candidate_metrics(pressing_candidates),
            },
            "saturation": {
                "action_type": action,
                "success": True,
                "valence": 0.8,
                "evidence_source": "controlled confirmed outcome via on_action_result",
                "before": before,
                "after": after,
                "delta": after - before,
                "expected_after_from_constants": expected_after,
                "matches_precomputed_delta": close(after, expected_after),
                "final": need_metrics(need),
                "candidate_present_after": any(
                    item.get("need") == name for item in final_candidates
                ),
                "cross_need_deltas": {
                    key: after_level - before_outcome[key]
                    for key, after_level in all_levels(system).items()
                    if not close(after_level, before_outcome[key])
                },
                "candidates": candidate_metrics(final_candidates),
            },
        }
    return observations


def observe_drives() -> dict[str, dict]:
    observations = {}
    for name, template in DEFAULT_DRIVES.items():
        sandbox = use_sandbox(f"drive_{name}")
        satisfied = new_system()
        satisfy_all(satisfied)
        satisfied_level = satisfied.drives[name].calculate_intensity(satisfied.needs)

        deficit = new_system()
        satisfy_all(deficit)
        for need_name in template.contributing_needs:
            deficit.needs[need_name].current_level = 0.0
        deficit_level = deficit.drives[name].calculate_intensity(deficit.needs)

        missing = new_system()
        missing_level = missing.drives[name].calculate_intensity({})

        # Наличие исполнимых кандидатов наблюдаем отдельно от композиции:
        # иначе прямые need-driven кандидаты и top-5 могут скрыть drive-канал.
        candidates_system = new_system()
        satisfy_all(candidates_system)
        drive = candidates_system.drives[name]
        drive.current_level = drive.activation_threshold
        candidates = candidates_system.get_action_candidates({})
        drive_candidates = [item for item in candidates if item.get("drive") == name]
        observations[name] = {
            "sandbox": sandbox,
            "contributing_needs": dict(template.contributing_needs),
            "activation_threshold": template.activation_threshold,
            "satisfied": {
                "level": satisfied_level,
                "active": satisfied.drives[name].is_active(),
            },
            "controlled_deficit": {
                "need_levels": {
                    key: deficit.needs[key].current_level
                    for key in template.contributing_needs
                },
                "level": deficit_level,
                "active": deficit.drives[name].is_active(),
            },
            "missing_contributions": {
                "level": missing_level,
                "active": missing.drives[name].is_active(),
            },
            "candidate_probe": {
                "injected_drive_level": drive.current_level,
                "count": len(drive_candidates),
                "candidates": candidate_metrics(drive_candidates),
            },
        }
    return observations


def observe_m03() -> dict:
    sandbox = use_sandbox("m03_failure_denied_no_effect")
    negative = new_system()
    satisfy_all(negative)
    negative.needs["curiosity"].current_level = 0.5
    before_negative = all_levels(negative)
    negative.on_action_result("search_miss", True, -0.2)
    negative_deltas = {
        name: level - before_negative[name]
        for name, level in all_levels(negative).items()
        if not close(level, before_negative[name])
    }

    no_effect_agent = DigitalBeing(name="D2NoEffect")
    satisfy_all(no_effect_agent.motivation_system)
    no_effect_agent.motivation_system.needs["curiosity"].current_level = 0.5
    before_no_effect = all_levels(no_effect_agent.motivation_system)
    with patch.object(
        no_effect_agent,
        "_act_explore",
        return_value={"text": "Новых свидетельств нет", "target": "пусто"},
    ):
        no_effect_result = no_effect_agent.act("explore")
    no_effect_outcome = no_effect_agent._last_action_outcome
    after_no_effect = all_levels(no_effect_agent.motivation_system)

    denied_agent = DigitalBeing(name="D2Denied")
    satisfy_all(denied_agent.motivation_system)
    denied_agent.motivation_system.needs["curiosity"].current_level = 0.5
    denied_agent.energy = 0.0
    before_denied = all_levels(denied_agent.motivation_system)
    denied_result = denied_agent.act("explore")
    denied_outcome = denied_agent._last_action_outcome
    after_denied = all_levels(denied_agent.motivation_system)
    return {
        "sandbox": sandbox,
        "negative_valence": {
            "action_type": "search_miss",
            "success": True,
            "valence": -0.2,
            "deltas": negative_deltas,
        },
        "no_effect": {
            "result": no_effect_result,
            "outcome": no_effect_outcome.as_dict() if no_effect_outcome else None,
            "curiosity_delta": after_no_effect["curiosity"]
            - before_no_effect["curiosity"],
            "all_deltas": {
                name: level - before_no_effect[name]
                for name, level in after_no_effect.items()
                if not close(level, before_no_effect[name])
            },
        },
        "denied": {
            "result": denied_result,
            "outcome": denied_outcome.as_dict() if denied_outcome else None,
            "needs_unchanged": after_denied == before_denied,
            "curiosity_delta": after_denied["curiosity"] - before_denied["curiosity"],
        },
    }


def observe_m04_m09() -> dict:
    sandbox = use_sandbox("m04_m09_scales")
    system = new_system()
    satisfy_all(system)
    system.needs["curiosity"].current_level = 0.4
    non_pressing = need_metrics(system.needs["curiosity"])
    non_pressing_candidates = system.get_action_candidates({})
    status_non_pressing = system.get_status()
    most_pressing_non_pressing = system.get_most_pressing_need()

    system.needs["curiosity"].current_level = 0.1
    system.needs["meaning"].current_level = 0.1
    candidates = system.get_action_candidates({})
    status_pressing = system.get_status()
    most_pressing = system.get_most_pressing_need()
    return {
        "sandbox": sandbox,
        "non_pressing_positive_urgency": {
            "need": non_pressing,
            "need_candidate_present": any(
                item.get("need") == "curiosity" for item in non_pressing_candidates
            ),
            "status_most_pressing_need": status_non_pressing["most_pressing_need"],
            "status_pressing_needs": status_non_pressing["pressing_needs"],
            "get_most_pressing_need": (
                most_pressing_non_pressing.name if most_pressing_non_pressing else None
            ),
        },
        "two_pressing_needs": {
            "curiosity": need_metrics(system.needs["curiosity"]),
            "meaning": need_metrics(system.needs["meaning"]),
            "candidates": candidate_metrics(candidates),
            "status_most_pressing_need": status_pressing["most_pressing_need"],
            "status_pressing_needs": status_pressing["pressing_needs"],
            "get_most_pressing_need": most_pressing.name if most_pressing else None,
        },
    }


def observe_m05() -> dict:
    sandbox = use_sandbox("m05_competition")
    random.seed(20261120)
    system = new_system()
    satisfy_all(system)
    system.needs["curiosity"].current_level = 0.1
    system.needs["autonomy"].current_level = 0.1
    system.needs["play"].current_level = 0.05
    for drive in system.drives.values():
        drive.calculate_intensity(system.needs)
    candidates = system.get_action_candidates({})
    candidates.extend(
        [
            {
                "source": "embodiment",
                "action": "deep_rest",
                "strength": 0.75,
                "params": {"reason": "controlled_observation"},
            },
            {
                "source": "social",
                "action": "communicate",
                "strength": 0.72,
                "params": {},
            },
            {
                "source": "active_goal",
                "action": "explore",
                "strength": 0.5,
                "params": {"concept": "память", "goal_id": 1},
            },
        ]
    )
    choice = DecisionArbitrator().choose_action(
        deepcopy(candidates), {"simulation_mode": "shadow"}
    )
    return {
        "sandbox": sandbox,
        "executed": False,
        "needs": {
            name: need_metrics(system.needs[name])
            for name in ("curiosity", "autonomy", "play")
        },
        "drives": {name: drive.to_dict() for name, drive in system.drives.items()},
        "candidates_before_arbitration": candidate_metrics(candidates),
        "choice": choice,
    }


def observe_m06() -> dict:
    sandbox = use_sandbox("m06_pause")
    agent = DigitalBeing(name="D2Pause")
    satisfy_all(agent.motivation_system)
    before = all_levels(agent.motivation_system)
    candidates = agent.motivation_system.get_action_candidates({})
    goals = agent.motivation_system.generate_goals()
    choice = agent.decision_arbitrator.choose_action(deepcopy(candidates), {})
    return {
        "sandbox": sandbox,
        "executed": False,
        "needs_unchanged": all_levels(agent.motivation_system) == before,
        "candidates": candidate_metrics(candidates),
        "generated_goals": goals,
        "choice": {
            "action": choice.get("action"),
            "source": choice.get("source"),
            "verdict": choice.get("verdict"),
        },
    }


def observe_m07() -> dict:
    sandbox_a = use_sandbox("m07_life_a")
    random.seed(20261120)
    first = DigitalBeing(name="D2LifeA")
    motivation = first.motivation_system
    satisfy_all(motivation)
    motivation.needs["curiosity"].current_level = 0.123
    motivation.needs["autonomy"].current_level = 0.456
    generated = motivation.generate_goals(
        pressing_needs=[motivation.needs["curiosity"]], active_drives=[]
    )
    first._ingest_motivation_goals(generated)
    goal_id = generated[0]["goal_id"]
    first.cycle_count = 100
    checkpoint_path = first.save_state(force=True)
    if checkpoint_path is None:
        raise RuntimeError("D2 restart observation could not save checkpoint")
    snapshot = CheckpointSerializer().load(checkpoint_path)

    restored = DigitalBeing(name="D2LifeARestarted")
    apply_state_to_agent(restored, snapshot)
    restored_levels = all_levels(restored.motivation_system)
    restored_history = deepcopy(restored.motivation_system.goal_history)

    sandbox_b = use_sandbox("m07_life_b")
    second = DigitalBeing(name="D2LifeB")
    second_levels = all_levels(second.motivation_system)
    return {
        "sandbox_life_a": sandbox_a,
        "sandbox_life_b": sandbox_b,
        "checkpoint_path": str(checkpoint_path),
        "goal_id": goal_id,
        "goal_origin_before": deepcopy(generated[0]),
        "needs_restored_exactly": restored_levels == all_levels(motivation),
        "levels_before": all_levels(motivation),
        "levels_after_restart": restored_levels,
        "goal_history_after_restart": restored_history,
        "goal_origin_restored": any(
            item.get("goal_id") == goal_id and item.get("need") == "curiosity"
            for item in restored_history
        ),
        "second_life_has_default_needs": second_levels
        == {name: need.current_level for name, need in DEFAULT_NEEDS.items()},
        "second_life_levels": second_levels,
        "second_life_goal_history": deepcopy(second.motivation_system.goal_history),
    }


def observe_m08() -> dict:
    sandbox = use_sandbox("m08_neighbour_channels")
    agent = DigitalBeing(name="D2Channels")
    searcher = getattr(agent, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    satisfy_all(agent.motivation_system)
    agent.motivation_system.needs["curiosity"].current_level = 0.05
    agent.interoception.state.fatigue = 0.8
    agent._open_questions = [
        {
            "text": "Как устроена память?",
            "answered": False,
            "explorations": [1, 2, 3, 4],
            "max_explorations": 5,
        }
    ]
    # Убираем только стартовые цели песочницы: иначе экзистенциальный квест
    # занимает active_goal и мешает наблюдать отдельный goal-driven канал.
    agent.goals.clear()
    agent.goal_subsystem.goals = agent.goals
    agent.goal_subsystem.active_goal = None
    agent.active_goal = None
    agent._ingest_motivation_goals(
        [
            {
                "title": "Картирование: память",
                "source": "need",
                "need": "curiosity",
                "action_hint": "explore",
                "type": "mapping",
                "priority": 0.5,
            }
        ]
    )
    agent.emotional_state.handle_event("abuse", cycle=1, cause="контроль")
    agent.emotional_state.handle_event("abuse", cycle=2, cause="контроль")

    captured = {}
    real_choose = agent.decision_arbitrator.choose_action

    def observe_choice(candidates, context):
        captured["candidates"] = deepcopy(candidates)
        captured["context"] = deepcopy(context)
        captured["real_choice"] = real_choose(deepcopy(candidates), deepcopy(context))
        return {
            "action": "wait",
            "source": "d2_observation_only",
            "verdict": "proceed",
            "params": {"reason": "do_not_execute"},
        }

    with patch.object(
        agent.decision_arbitrator, "choose_action", side_effect=observe_choice
    ):
        report = agent.autonomous_tick()
    candidates = captured.get("candidates", [])
    return {
        "sandbox": sandbox,
        "cycles": 1,
        "executed": "autonomous_action" in report,
        "sources": sorted({str(item.get("source")) for item in candidates}),
        "candidates_before_observed_choice": candidate_metrics(candidates),
        "real_choice_not_executed": captured.get("real_choice"),
        "emotional_bias": report.get("emotional_bias"),
        "active_inference": report.get("active_inference"),
        "motivation_after_tick": report.get("motivation"),
    }


def main() -> None:
    OBSERVATION_ROOT.mkdir(parents=True, exist_ok=True)
    live_before = repo_data_manifest()
    result = {
        "schema": "d2_motivation_observation_v1",
        "revision": current_revision(),
        "seed": 20261120,
        "observation_root": str(OBSERVATION_ROOT),
        "production_code_changed_by_harness": False,
        "m00": observe_m00(),
        "needs": observe_needs(),
        "drives": observe_drives(),
        "m03": observe_m03(),
        "m04_m09": observe_m04_m09(),
        "m05": observe_m05(),
        "m06": observe_m06(),
        "m07": observe_m07(),
        "m08": observe_m08(),
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
                "m00_identical": result["m00"]["identical_metrics"],
                "needs": len(result["needs"]),
                "drives": len(result["drives"]),
                "live_data_unchanged": result["live_data_unchanged"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


DEFAULT_NEEDS_LEVELS = {
    name: need.current_level for name, need in DEFAULT_NEEDS.items()
}


if __name__ == "__main__":
    main()
