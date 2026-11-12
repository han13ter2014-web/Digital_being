"""Импорт активной жизни во временную SQLite-базу и проверка восстановления.

Источник ``data/`` только читается. Временный каталог удаляется на выходе.
"""

from contextlib import redirect_stdout
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"

COMPARE_FIELDS = (
    "life_id", "name", "cycle_count", "energy", "intelligence",
    "completed_goals", "goals", "active_goal", "success_streak",
    "knowledge_base", "mental_models", "_goal_progress", "_learned_facts",
    "_known_definitions", "open_questions", "emotional_state", "interoception",
    "continuous_time", "motivation", "loop_closure", "intention_history",
    "waiting_intentions", "method_preferences", "personal_state",
    "integrated_experience", "cooperation", "active_inference",
    "internal_simulation",
)


def _compact(value):
    text = repr(value)
    return text if len(text) <= 500 else text[:497] + "..."


def _difference_paths(expected, actual, path="", limit=30):
    """Показать конкретные различия без выгрузки всего состояния жизни."""
    if type(expected) is not type(actual):
        return [{"path": path, "source": _compact(expected),
                 "restored": _compact(actual)}]
    if isinstance(expected, dict):
        differences = []
        for key in sorted(set(expected) | set(actual), key=str):
            if len(differences) >= limit:
                break
            child = f"{path}.{key}" if path else str(key)
            if key not in expected:
                differences.append({"path": child, "source": "<missing>",
                                    "restored": _compact(actual[key])})
            elif key not in actual:
                differences.append({"path": child, "source": _compact(expected[key]),
                                    "restored": "<missing>"})
            else:
                differences.extend(_difference_paths(
                    expected[key], actual[key], child, limit - len(differences)
                ))
        return differences[:limit]
    if isinstance(expected, (list, tuple)):
        if len(expected) != len(actual):
            return [{"path": f"{path}.length", "source": len(expected),
                     "restored": len(actual)}]
        differences = []
        for index, (left, right) in enumerate(zip(expected, actual)):
            differences.extend(_difference_paths(
                left, right, f"{path}[{index}]", limit - len(differences)
            ))
            if len(differences) >= limit:
                break
        return differences[:limit]
    if expected != actual:
        return [{"path": path, "source": _compact(expected),
                 "restored": _compact(actual)}]
    return []


def _semantic_projection(state, pristine_state, legacy_missing=frozenset()):
    """Отделить нажитое состояние от представления JSON и конфигурации кода.

    Исторические снимки не знают подсистем, добавленных позже. Для них
    эталоном служит состояние свежесозданного агента, а не отсутствие объекта.
    """
    projected = deepcopy(state)
    notes = []

    progress = projected.get("_goal_progress")
    if isinstance(progress, dict):
        if any(isinstance(key, int) for key in progress):
            projected["_goal_progress"] = {str(key): value for key, value in progress.items()}
            notes.append("goal_progress: числовые ключи приведены к JSON-строкам")
        for entry in projected["_goal_progress"].values():
            matched = entry.get("matched_concepts")
            if isinstance(matched, list):
                # В runtime это set: порядок сериализации не является опытом.
                entry["matched_concepts"] = sorted(matched)

    levels = (projected.get("emotional_state") or {}).get("levels")
    if isinstance(levels, dict):
        from src.core.emotional_state import EMOTIONS
        added = [name for name in EMOTIONS if name not in levels]
        for name in added:
            levels[name] = 0.0
        if added:
            notes.append(f"emotional_state: {len(added)} новых эмоций инициализированы нулём")

    motivation = projected.get("motivation")
    if isinstance(motivation, dict):
        # Эти списки и пороги from_checkpoint_dict сознательно берёт из
        # текущего кода; нажитыми являются уровни, счётчики и история.
        for need in (motivation.get("needs") or {}).values():
            for key in ("label", "decay_rate", "threshold", "priority",
                        "related_concepts", "related_actions"):
                need.pop(key, None)
        for drive in (motivation.get("drives") or {}).values():
            for key in ("label", "contributing_needs", "activation_threshold",
                        "goal_types"):
                drive.pop(key, None)
        notes.append("motivation: статическая конфигурация взята из текущего кода")

    for field in ("integrated_experience", "cooperation", "internal_simulation"):
        if projected.get(field) is None:
            projected[field] = deepcopy(pristine_state.get(field))
            if field == "cooperation" and projected[field] is not None:
                projected[field]["agent_relationships"] = {state.get("life_id"): {}}
            notes.append(f"{field}: отсутствующая legacy-секция инициализирована по умолчанию")
    if "integrated_experience" in legacy_missing:
        patterns = (
            (projected.get("integrated_experience") or {})
            .get("thinking_patterns", {}).get("patterns", {})
        )
        for pattern in patterns.values():
            # Это момент создания встроенного шаблона при инициализации,
            # а не время пережитого событием опыта.
            pattern.pop("created_at", None)
        notes.append("integrated_experience: время инициализации встроенных шаблонов не сравнивается")
    return projected, notes


def main():
    temp_root = ROOT / "tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sqlite_migration_", dir=temp_root) as isolated:
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(Path(isolated) / "runtime_data")
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        os.environ["VOICE_CONSOLE_QUIET"] = "1"
        for name in (
            "DIGITAL_BEING_TELEGRAM_TOKEN", "DIGITAL_BEING_TELEGRAM_CHAT_ID",
            "DIGITAL_BEING_DISCORD_WEBHOOK_URL",
        ):
            os.environ.pop(name, None)

        from src.memory.life_migration import migrate_life_to_sqlite
        from src.memory.life_database import LifeDatabase

        profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
        life_id = profile["life_id"]
        report = migrate_life_to_sqlite(DATA, life_id, isolated)
        database = LifeDatabase(report["database"], life_id)
        state = database.checkpoints.load(report["latest_snapshot_id"])

        from src.core.agent import DigitalBeing
        from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent

        agent = DigitalBeing(state.get("name") or "MigrationCopy", profile_managed=True)
        pristine_state = build_state_from_agent(agent)
        log_path = Path(isolated) / "restore.log"
        with log_path.open("w", encoding="utf-8") as log, redirect_stdout(log):
            apply_state_to_agent(agent, state)
        searcher = getattr(agent, "web_searcher", None)
        if searcher is not None:
            searcher.toggle(False)
        restored_state = build_state_from_agent(agent)
        legacy_missing = {
            field for field in ("integrated_experience", "cooperation", "internal_simulation")
            if state.get(field) is None
        }
        source_projection, source_notes = _semantic_projection(
            state, pristine_state, legacy_missing
        )
        restored_projection, restored_notes = _semantic_projection(
            restored_state, pristine_state, legacy_missing
        )
        mismatches = [
            field for field in COMPARE_FIELDS
            if restored_projection.get(field) != source_projection.get(field)
        ]
        result = {
            **report,
            "source_checkpoint_cycle": state.get("cycle_count"),
            "restored_agent_name": agent.name,
            "restored_cycle": agent.cycle_count,
            "restore_fields_compared": len(COMPARE_FIELDS),
            "restore_comparison": "semantic_state_with_explicit_runtime_normalizations",
            "restore_runtime_normalizations": sorted(set(source_notes + restored_notes)),
            "restore_mismatches": mismatches,
            "restore_mismatch_details": {
                field: _difference_paths(
                    source_projection.get(field), restored_projection.get(field), field
                )
                for field in mismatches
            },
            "restore_equivalent": not mismatches,
            "temporary_copy_removed_on_exit": True,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        from src.core.buffered_logger import flush_logs
        flush_logs()
        if mismatches:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
