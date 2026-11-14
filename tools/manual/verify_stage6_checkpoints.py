"""Read-only verifier первого кандидата этапа 6; ничего не удаляет."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.memory.checkpoint_verifier import verify_checkpoint_batch  # noqa: E402


def _inventory(root: Path) -> dict:
    files = {}
    combined = hashlib.sha256()
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        relative = path.relative_to(root).as_posix()
        content_hash = digest.hexdigest()
        files[relative] = content_hash
        combined.update(relative.encode("utf-8"))
        combined.update(b"\0")
        combined.update(content_hash.encode("ascii"))
        combined.update(b"\n")
        total_bytes += path.stat().st_size
    return {
        "files": files,
        "file_count": len(files),
        "bytes": total_bytes,
        "aggregate_sha256": combined.hexdigest(),
    }


def _outside_data(output: Path, data_root: Path) -> None:
    try:
        output.relative_to(data_root)
    except ValueError:
        return
    raise ValueError(f"Манифест нельзя записывать внутрь data/: {output}")


def _write_manifest(output: Path, report: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output.parent,
            prefix=output.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Сверить legacy JSON активного UUID со SQLite snapshots. "
            "Манифест не является разрешением на удаление."
        )
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--life-id", help="UUID; по умолчанию из active_profile.json")
    parser.add_argument("--expected-count", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tmp" / "stage6_checkpoint_manifest.json",
        help="Новый JSON-файл строго вне data/",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    data_root = args.data_root.resolve()
    output = args.output.resolve()
    _outside_data(output, data_root)
    if output.exists():
        raise FileExistsError(f"Манифест уже существует, не перезаписываю: {output}")

    life_id = args.life_id
    profile_name = None
    profile_path = data_root / "active_profile.json"
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        life_id = life_id or profile["life_id"]
        profile_name = profile.get("name")
    if not life_id:
        raise ValueError("UUID не указан и active_profile.json недоступен")

    before = _inventory(data_root)
    report = verify_checkpoint_batch(
        data_root, life_id, expected_count=args.expected_count
    )
    after = _inventory(data_root)
    changed = [
        path
        for path in sorted(set(before["files"]) | set(after["files"]))
        if before["files"].get(path) != after["files"].get(path)
    ]
    comparison_ok = report["ok"]
    report["profile_name"] = profile_name
    report["source_data"] = {
        "before": {key: value for key, value in before.items() if key != "files"},
        "after": {key: value for key, value in after.items() if key != "files"},
        "unchanged": before == after,
        "changed_paths": changed,
    }
    report["ok"] = comparison_ok and not changed
    report["autonomous_ticks"] = 0
    report["deleted_paths"] = []
    _write_manifest(output, report)
    print(json.dumps({
        "ok": report["ok"],
        "comparison_ok": comparison_ok,
        "manifest": str(output),
        "life_id": report["life_id"],
        "legacy_count": report["legacy_count"],
        "snapshot_count": report["database"]["snapshot_count"],
        "matched_count": sum(entry["matched"] for entry in report["entries"]),
        "source_data_unchanged": report["source_data"]["unchanged"],
        "deletion_authorized": False,
        "errors": report["errors"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
