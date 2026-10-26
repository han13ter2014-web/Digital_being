"""Явный импорт старого JSON и сборка недостижимых блоков SQLite.

Старые файлы не удаляются. GC освобождает страницы для повторного использования,
но не гарантирует уменьшение размера файла на диске (VACUUM отдельно).
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.checkpoint_serializer import CheckpointSerializer
from src.memory.checkpoint_store import SQLiteCheckpointStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--import-json", type=Path)
    parser.add_argument("--gc", action="store_true")
    args = parser.parse_args()
    store = SQLiteCheckpointStore(args.database)
    if args.import_json:
        state = CheckpointSerializer().load(str(args.import_json))
        if state is None:
            parser.error("Файл не найден")
        # Та же совместимость ключей, что при обычном JSON roundtrip.
        import json

        if state.get("meta_learning", {}).get("best_fitness") == float("-inf"):
            state["meta_learning"]["best_fitness"] = None
        state = json.loads(json.dumps(state, allow_nan=False))
        snapshot_id = store.save(state, state["name"], state["cycle_count"])
        if store.load(snapshot_id) != state:
            raise RuntimeError("Импорт не прошёл проверку обратного чтения")
        print(f"Imported snapshot {snapshot_id}; original file unchanged")
    if args.gc:
        print(f"Unreachable blobs removed: {store.gc()}")


if __name__ == "__main__":
    main()
