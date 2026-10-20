"""Чистит базу знаний от некачественных записей.

Использование:

    python tools/clean_kb.py                 # dry-run: показать, что будет удалено
    python tools/clean_kb.py --apply         # удалить и перезаписать файл
    python tools/clean_kb.py --file other.json --apply

Правила те же, что и в рантайме (``src/memory/knowledge_quality.py``),
поэтому ручная чистка и автоматический фильтр не расходятся.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.memory.knowledge_quality import (  # noqa: E402
    REASON_TITLES,
    clean_knowledge_base,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        default=str(PROJECT_ROOT / "data" / "knowledge_base.json"),
        help="Путь к JSON базы знаний",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать очищенный файл (без флага — только показать)",
    )
    args = parser.parse_args()

    path = Path(args.file)
    data = json.loads(path.read_text(encoding="utf-8"))
    cleaned, removed = clean_knowledge_base(data)

    print(f"Файл: {path}")
    print(f"Записей: {len(data)}")
    print(f"Некачественных: {len(removed)}")
    print(f"Останется: {len(cleaned)}")
    for key, reason in removed.items():
        title = REASON_TITLES.get(reason, reason)
        preview = str(data[key]).replace("\n", " ")[:70]
        print(f"  - {key!r}: {title} — {preview!r}")

    if not removed:
        return 0
    if not args.apply:
        print("\nDry-run. Для записи добавьте --apply.")
        return 0

    path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nЗаписано: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
