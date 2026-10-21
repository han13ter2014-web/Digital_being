"""Smoke-прогон N циклов агента в изолированной временной папке.

Зачем: сравнить поведение до/после этапа 1 на одинаковых условиях.
Скрипт не трогает рабочую папку проекта: все данные (лог, KB, чекпоинты)
пишутся в temp-директорию.

Использование:
    python tools/stage1_smoke.py --cycles 200
    python tools/stage1_smoke.py --cycles 200 --json before.json

Работает и на старой версии кода (до этапа 1): если
``select_novel_stimulus`` ещё нет, используется обычный
``generate_prioritized_stimulus`` без кулдауна — это и есть поведение «до».
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=200)
    parser.add_argument("--tick-seconds", type=float, default=5.0,
                        help="Сколько «реального времени» проходит между тиками")
    parser.add_argument("--json", default=None, help="Куда сохранить результат")
    parser.add_argument("--keep", action="store_true", help="Не удалять temp-папку")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    workdir = Path(tempfile.mkdtemp(prefix="db_stage1_"))
    os.chdir(workdir)

    from src.core.agent import DigitalBeing
    from src.core.energy_policy import EnergyPolicy
    from src.core.stimulus_selector import generate_prioritized_stimulus
    from config.simulation_config import LR_CONFIG

    try:
        from src.core.stimulus_selector import select_novel_stimulus
        has_dedup = True
    except ImportError:
        select_novel_stimulus = None
        has_dedup = False

    cooldown = int(getattr(LR_CONFIG, "STIMULUS_COOLDOWN_TICKS", 0) or 0)

    agent = DigitalBeing("Smoke")
    # Оффлайн: одинаковые условия для обоих прогонов, без сети и Wikipedia.
    if getattr(agent, "thinking", None) is not None:
        agent.thinking.web_searcher = None
    initial_concepts = set(getattr(agent.mental_models, "concepts", {}) or {})

    policy = EnergyPolicy(
        get_energy=lambda: agent.energy,
        max_energy=LR_CONFIG.ENERGY_MAX,
    )
    policy.attach_setter(lambda value: setattr(agent, "energy", value))

    recent: dict[str, int] = {}
    tick = 0
    idle = 0
    errors = 0
    stimuli: set[str] = set()
    energy_min = agent.energy
    started = time.time()

    for _ in range(args.cycles):
        if has_dedup:
            stimulus = select_novel_stimulus(
                agent, recent, tick, cooldown, goal_priority_prob=0.7
            )
        else:
            stimulus = generate_prioritized_stimulus(agent)
        tick += 1
        # Как в main.py: cycle_count агента — источник правды для
        # чекпоинтов, эволюции и внутренней мотивации.
        agent.cycle_count = tick

        if stimulus is None:
            idle += 1
            try:
                agent.autonomous_tick()
            except Exception:
                errors += 1
            policy.regenerate(args.tick_seconds)
            energy_min = min(energy_min, agent.energy)
            continue

        stimuli.add(stimulus)
        if has_dedup and "[стратегия=" not in stimulus:
            recent[stimulus.strip().lower()] = tick

        try:
            perceived = agent.perceive(stimulus)
            thought = agent.think(perceived)
            agent.act(thought)
            agent.evolve()
            if stimulus.startswith("вопрос: "):
                agent._record_open_question_exploration(stimulus, thought)
        except Exception:
            errors += 1

        policy.regenerate(args.tick_seconds)
        energy_min = min(energy_min, agent.energy)

    log_path = workdir / "data" / "logs" / "agent_log.txt"
    log_lines = actions = bad_decomposition = 0
    unique_actions: set[str] = set()
    action_counts: dict[str, int] = {}
    action_types: dict[str, int] = {}
    if log_path.exists():
        with log_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                log_lines += 1
                if "Выполняет " in line:
                    actions += 1
                    payload = line.split("Выполняет ", 1)[1].strip()
                    match = re.match(r"\[([a-z_]+)\]:\s*(.*)", payload)
                    if match:
                        action_type, action = match.group(1), match.group(2)
                    else:
                        action_type, action = "unknown", payload
                    if action.startswith("Ответ: "):
                        action = action[len("Ответ: "):]
                    action = action[:80]
                    action_types[action_type] = action_types.get(action_type, 0) + 1
                    unique_actions.add(action)
                    action_counts[action] = action_counts.get(action, 0) + 1
                if "что такое такое" in line:
                    bad_decomposition += 1

    # Служебные слова, которые не должны становиться концепциями.
    garbage = {"такое", "это", "как", "что", "меня", "ты", "работает"}
    concepts = set(getattr(getattr(agent, "mental_models", None), "concepts", {}) or {})
    new_concepts = concepts - initial_concepts
    garbage_concepts = sorted(new_concepts & garbage)

    result = {
        "cycles": args.cycles,
        "has_dedup": has_dedup,
        "cooldown_ticks": cooldown,
        "idle_ticks": idle,
        "unique_stimuli": len(stimuli),
        "log_lines": log_lines,
        "actions": actions,
        "unique_actions": len(unique_actions),
        "max_same_action": max(action_counts.values()) if action_counts else 0,
        "action_types": dict(
            sorted(action_types.items(), key=lambda item: -item[1])
        ),
        "completed_goals": int(getattr(agent, "completed_goals", 0)),
        "active_goal": (
            agent.active_goal["title"] if getattr(agent, "active_goal", None) else None
        ),
        "goal_progress": {
            str(gid): int(p.get("percentage", 0))
            for gid, p in (getattr(agent, "_goal_progress", {}) or {}).items()
        },
        "bad_decomposition": bad_decomposition,
        "mental_concepts": len(concepts),
        "new_concepts": len(new_concepts),
        "garbage_concepts": garbage_concepts,
        "kb_entries": len(agent.knowledge_base),
        "energy_min": round(energy_min, 2),
        "energy_final": round(agent.energy, 2),
        "errors": errors,
        "duration_sec": round(time.time() - started, 1),
        "workdir": str(workdir),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json:
        Path(args.json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if not args.keep:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
