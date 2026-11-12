"""Read-only проверка локальных SQLite-баз проекта."""

import json
import sqlite3
from itertools import islice
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def inspect(path):
    result = {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size}
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            result["integrity"] = [
                row[0] for row in connection.execute("PRAGMA integrity_check")
            ]
            result["foreign_key_violations"] = [
                list(row) for row in islice(connection.execute("PRAGMA foreign_key_check"), 20)
            ]
            result["journal_mode"] = connection.execute("PRAGMA journal_mode").fetchone()[0]
            result["user_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )]
            counts = {}
            for table in tables:
                safe = table.replace('"', '""')
                try:
                    counts[table] = connection.execute(
                        f'SELECT COUNT(*) FROM "{safe}"'
                    ).fetchone()[0]
                except sqlite3.Error as exc:
                    counts[table] = f"error: {exc}"
            result["tables"] = counts
    except (OSError, sqlite3.Error) as exc:
        result["error"] = str(exc)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        result[suffix] = sidecar.stat().st_size if sidecar.exists() else None
    return result


def main():
    paths = sorted({
        path for pattern in ("*.db", "*.sqlite", "*.sqlite3")
        for path in DATA.rglob(pattern) if path.is_file()
    })
    print(json.dumps({"databases": [inspect(path) for path in paths]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
