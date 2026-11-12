"""Fail-closed объединение read-only доказательств checkpoints этапа 6."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.life_identity import validate_life_id
from src.memory.checkpoint_verifier import _file_hash
from tools.manual.verify_stage6_checkpoints import (
    _inventory,
    _outside_data,
    _write_manifest,
)


ALLOWED_ACTIVE_ERRORS = Counter({
    "Повторяющийся SQLite cycle=10553": 2,
    "Корневые хеши не совпадают с последним verified migration run": 1,
    "cycle=9472: SQLite snapshot отсутствует": 1,
    "cycle=9532: SQLite snapshot отсутствует": 1,
})


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _source_fingerprint(report):
    return report.get("source_data", {}).get("after", {})


def build_coverage(
    data_root,
    life_id,
    active_report,
    history_report,
    consolidation_report,
    *,
    current_inventory=None,
):
    """Объединить доказательства без повторного decode SQL или записи в data/."""
    data_root = Path(data_root).resolve()
    life_id = validate_life_id(life_id)
    active = _load(active_report)
    history = _load(history_report)
    consolidation = _load(consolidation_report)
    current_inventory = current_inventory or _inventory(data_root)
    current_fingerprint = {
        key: current_inventory[key]
        for key in ("file_count", "bytes", "aggregate_sha256")
    }
    errors = []

    reports = {
        "active": active,
        "history": history,
        "consolidation": consolidation,
    }
    for name, report in reports.items():
        if report.get("life_id") != life_id:
            errors.append(f"{name}: life_id не совпадает")
        if report.get("deletion_authorized") is not False:
            errors.append(f"{name}: небезопасный deletion_authorized")
        fingerprint = _source_fingerprint(report)
        if fingerprint != current_fingerprint:
            errors.append(f"{name}: fingerprint исходных данных не совпадает с текущим")
        if report.get("source_data", {}).get("unchanged") is not True:
            errors.append(f"{name}: исходная проверка не подтвердила неизменность data")
        if report.get("deleted_paths") != []:
            errors.append(f"{name}: непустой deleted_paths")

    migration_ids = {
        active.get("database", {}).get("verified_migration_run", {}).get("id"),
        history.get("migration_run_id"),
        consolidation.get("migration_run_id"),
    }
    if len(migration_ids) != 1 or None in migration_ids:
        errors.append(f"Migration run не согласован: {sorted(migration_ids, key=str)}")
    migration_id = migration_ids.pop() if len(migration_ids) == 1 else None

    if active.get("ok") is not False or Counter(active.get("errors", [])) != ALLOWED_ACTIVE_ERRORS:
        errors.append("active: набор исходных ошибок отличается от объяснённого в 6.5")
    if active.get("legacy_count") != 20 or active.get("expected_count") != 20:
        errors.append("active: ожидалось ровно 20 legacy-файлов")
    if active.get("unexpected_entries") != []:
        errors.append("active: есть unexpected_entries")
    if active.get("database", {}).get("snapshot_count") != 20:
        errors.append("active: ожидалось 20 текущих snapshots")
    if active.get("database", {}).get("latest_snapshot_id") != 22:
        errors.append("active: ожидался latest_snapshot_id=22")
    if active.get("database", {}).get("integrity_check") != ["ok"]:
        errors.append("active: integrity_check не подтверждён")
    if active.get("database", {}).get("foreign_key_violations") != []:
        errors.append("active: есть foreign-key нарушения")

    active_entries = active.get("entries", [])
    by_cycle = {}
    for entry in active_entries:
        cycle = entry.get("cycle")
        if cycle in by_cycle:
            errors.append(f"active: повторный legacy cycle={cycle}")
        by_cycle[cycle] = entry
        path = data_root / entry.get("legacy_path", "")
        try:
            if not path.is_file() or path.is_symlink():
                raise ValueError("файл отсутствует или является ссылкой")
            if _file_hash(path) != entry.get("legacy_sha256"):
                raise ValueError("SHA-256 не совпадает с исходным отчётом")
            if path.stat().st_size != entry.get("legacy_bytes"):
                raise ValueError("размер не совпадает с исходным отчётом")
        except Exception as exc:
            errors.append(f"active cycle={cycle}: текущий legacy: {exc}")
    if len(by_cycle) != 20:
        errors.append(f"active: ожидалось 20 уникальных cycles, найдено {len(by_cycle)}")

    for cycle in (9472, 9532):
        entry = by_cycle.get(cycle, {})
        if entry.get("matched") is not False or entry.get("errors") != [
            "SQLite snapshot отсутствует"
        ]:
            errors.append(f"active cycle={cycle}: отсутствие SQL snapshot не подтверждено")
    matched_active = [entry for entry in active_entries if entry.get("matched") is True]
    if len(matched_active) != 18:
        errors.append(f"active: ожидалось 18 совпавших, найдено {len(matched_active)}")
    if any(entry.get("snapshot_id") is None for entry in matched_active):
        errors.append("active: у совпавшего legacy отсутствует snapshot ID")

    if history.get("ok") is not True or history.get("errors") != []:
        errors.append("history: исходная backup-сверка не прошла")
    if history.get("restored_backup") is not False:
        errors.append("history: неожиданный restored_backup")
    if not history.get("backups") or any(
        backup.get("manifest_verified") is not True for backup in history["backups"]
    ):
        errors.append("history: не все backup manifest подтверждены")

    history_targets = {
        int(target["snapshot_id"]): target for target in history.get("targets", [])
    }
    snapshots = []
    legacy_coverage = []
    for snapshot_id in (1, 2):
        target = history_targets.get(snapshot_id)
        if not target or target.get("verified") is not True or not target.get("verified_in"):
            errors.append(f"history snapshot={snapshot_id}: нет verified_in")
            continue
        cycle = target["cycle"]
        active_entry = by_cycle.get(cycle)
        if active_entry is None:
            errors.append(f"history snapshot={snapshot_id}: legacy cycle={cycle} отсутствует")
            continue
        matches = [
            (backup["name"], entry)
            for backup in history["backups"]
            for entry in backup.get("snapshots", [])
            if entry.get("snapshot_id") == snapshot_id and entry.get("matched") is True
        ]
        if not matches:
            errors.append(f"history snapshot={snapshot_id}: нет matched backup entry")
            continue
        roots = {entry.get("snapshot_root_sha256") for _, entry in matches}
        state_hashes = {entry.get("sqlite_state_sha256") for _, entry in matches}
        if len(roots) != 1 or None in roots or len(state_hashes) != 1 or None in state_hashes:
            errors.append(f"history snapshot={snapshot_id}: backup хеши не согласованы")
            continue
        root = roots.pop()
        state_hash = state_hashes.pop()
        if state_hash != active_entry.get("legacy_state_sha256"):
            errors.append(f"history snapshot={snapshot_id}: state hash не совпадает с legacy")
        if any(entry.get("migration_root_sha256") != root for _, entry in matches):
            errors.append(f"history snapshot={snapshot_id}: migration root не совпадает")
        record = {
            "snapshot_id": snapshot_id,
            "cycle": cycle,
            "role": "historical_backup_legacy_source",
            "snapshot_root_sha256": root,
            "sqlite_state_sha256": state_hash,
            "verified_in": target["verified_in"],
        }
        snapshots.append(record)
        legacy_coverage.append({
            "cycle": cycle,
            "legacy_path": active_entry["legacy_path"],
            "legacy_bytes": active_entry["legacy_bytes"],
            "legacy_sha256": active_entry["legacy_sha256"],
            "proof": "verified_backup_sqlite",
            "snapshot_id": snapshot_id,
            "snapshot_root_sha256": root,
            "state_sha256": state_hash,
            "verified_in": target["verified_in"],
        })

    for entry in matched_active:
        snapshots.append({
            "snapshot_id": entry["snapshot_id"],
            "cycle": entry["cycle"],
            "role": "active_legacy_source",
            "snapshot_root_sha256": entry["snapshot_root_sha256"],
            "sqlite_state_sha256": entry["sqlite_state_sha256"],
            "verified_in": ["active"],
        })
        legacy_coverage.append({
            "cycle": entry["cycle"],
            "legacy_path": entry["legacy_path"],
            "legacy_bytes": entry["legacy_bytes"],
            "legacy_sha256": entry["legacy_sha256"],
            "proof": "active_sqlite",
            "snapshot_id": entry["snapshot_id"],
            "snapshot_root_sha256": entry["snapshot_root_sha256"],
            "state_sha256": entry["sqlite_state_sha256"],
            "verified_in": ["active"],
        })

    if consolidation.get("ok") is not True or consolidation.get("errors") != []:
        errors.append("consolidation: исходная one-to-many сверка не прошла")
    if consolidation.get("cycle") != 10553 or consolidation.get(
        "expected_snapshot_ids"
    ) != [20, 21, 22]:
        errors.append("consolidation: неожиданный cycle или snapshot IDs")
    if consolidation.get("consolidation", {}).get("one_to_many_verified") is not True:
        errors.append("consolidation: one_to_many_verified не подтверждён")
    consolidation_entries = {
        int(entry["snapshot_id"]): entry for entry in consolidation.get("snapshots", [])
    }
    if set(consolidation_entries) != {20, 21, 22}:
        errors.append("consolidation: набор snapshots отличается от 20/21/22")
    legacy_10553 = by_cycle.get(10553)
    consolidated_legacy = consolidation.get("legacy", {})
    if not legacy_10553 or legacy_10553.get("matched") is not True:
        errors.append("consolidation: активный legacy 10553 не совпал в исходном отчёте")
    if (
        consolidated_legacy.get("expected_snapshot_id") != 20
        or consolidated_legacy.get("sha256") != legacy_10553.get("legacy_sha256")
        or consolidated_legacy.get("state_sha256") != legacy_10553.get("legacy_state_sha256")
    ):
        errors.append("consolidation: legacy 10553 не согласован с active")
    original = consolidation_entries.get(20, {})
    if (
        original.get("verified") is not True
        or original.get("snapshot_root_sha256") != legacy_10553.get("snapshot_root_sha256")
        or original.get("sqlite_state_sha256") != legacy_10553.get("sqlite_state_sha256")
    ):
        errors.append("consolidation: ID 20 не согласован с active")
    for snapshot_id in (21, 22):
        entry = consolidation_entries.get(snapshot_id, {})
        if (
            entry.get("verified") is not True
            or entry.get("role") != "sql_only_additional_in_first_batch"
            or entry.get("migration_root_sha256") is not None
        ):
            errors.append(f"consolidation: ID {snapshot_id} не подтверждён как SQL-only additional")
            continue
        snapshots.append({
            "snapshot_id": snapshot_id,
            "cycle": 10553,
            "role": "active_sql_only_additional",
            "snapshot_root_sha256": entry.get("snapshot_root_sha256"),
            "sqlite_state_sha256": entry.get("sqlite_state_sha256"),
            "verified_in": ["active"],
        })

    snapshots.sort(key=lambda item: item["snapshot_id"])
    legacy_coverage.sort(key=lambda item: item["cycle"])
    snapshot_ids = [item["snapshot_id"] for item in snapshots]
    if snapshot_ids != list(range(1, 23)):
        errors.append(f"Coverage snapshots: ожидались ID 1–22, получено {snapshot_ids}")
    if len(legacy_coverage) != 20 or {item["cycle"] for item in legacy_coverage} != set(by_cycle):
        errors.append("Coverage legacy: не все 20 файлов имеют доказательство")
    roots = [item["snapshot_root_sha256"] for item in snapshots]
    state_hashes = [item["sqlite_state_sha256"] for item in snapshots]
    if len(set(roots)) != 22 or None in roots:
        errors.append("Coverage snapshots: корневые хеши не уникальны или отсутствуют")
    if len(set(state_hashes)) != 22 or None in state_hashes:
        errors.append("Coverage snapshots: state hashes не уникальны или отсутствуют")

    return {
        "manifest_schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "life_id": life_id,
        "migration_run_id": migration_id,
        "verification_method": "consolidation_of_read_only_evidence",
        "fresh_sql_decode": False,
        "input_manifests": [
            {
                "kind": kind,
                "path": str(Path(path).resolve()),
                "sha256": _file_hash(Path(path)),
                "source_fingerprint_matches_current": _source_fingerprint(report) == current_fingerprint,
            }
            for kind, path, report in (
                ("active", active_report, active),
                ("history", history_report, history),
                ("consolidation", consolidation_report, consolidation),
            )
        ],
        "legacy_coverage": legacy_coverage,
        "snapshot_coverage": snapshots,
        "summary": {
            "legacy_total": len(legacy_coverage),
            "legacy_total_bytes": sum(item["legacy_bytes"] for item in legacy_coverage),
            "legacy_covered_by_active": sum(
                item["proof"] == "active_sqlite" for item in legacy_coverage
            ),
            "legacy_covered_by_backup": sum(
                item["proof"] == "verified_backup_sqlite" for item in legacy_coverage
            ),
            "snapshot_ids_first": 1,
            "snapshot_ids_last": 22,
            "snapshot_total": len(snapshots),
            "active_snapshot_total": 20,
            "historical_snapshot_total": 2,
            "one_to_many_cycle": 10553,
            "one_to_many_snapshot_ids": [20, 21, 22],
            "checkpoint_coverage_verified": not errors,
        },
        "ok": not errors,
        "errors": errors,
        "deletion_authorized": False,
        "remaining_gates": [
            "остановить writers и автономные тики",
            "новый backup и restore в новый каталог",
            "отдельно разрешённая миграция живой схемы до v3 и adoption",
            "проверка managed legacy-writers",
            "полный regression и повторный backup/restore",
            "отдельное разрешение владельца на точный манифест удаления",
        ],
        "note": (
            "Полнота checkpoint coverage не является разрешением на удаление "
            "и не закрывает остальные gates этапа 6."
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Объединить read-only доказательства 6.5–6.7 в coverage manifest"
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--life-id")
    parser.add_argument(
        "--active-report", type=Path,
        default=ROOT / "tmp" / "stage6_checkpoint_manifest_v2.json",
    )
    parser.add_argument(
        "--history-report", type=Path,
        default=ROOT / "tmp" / "stage6_checkpoint_history_manifest.json",
    )
    parser.add_argument(
        "--consolidation-report", type=Path,
        default=ROOT / "tmp" / "stage6_cycle_10553_consolidated_manifest.json",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "tmp" / "stage6_checkpoint_coverage_manifest.json",
    )
    args = parser.parse_args(argv)
    data_root = args.data_root.resolve()
    output = args.output.resolve()
    _outside_data(output, data_root)
    if output.exists():
        raise FileExistsError(f"Манифест уже существует: {output}")
    life_id = args.life_id
    if not life_id:
        profile = json.loads((data_root / "active_profile.json").read_text(encoding="utf-8"))
        life_id = profile["life_id"]

    before = _inventory(data_root)
    report = build_coverage(
        data_root,
        life_id,
        args.active_report,
        args.history_report,
        args.consolidation_report,
        current_inventory=before,
    )
    after = _inventory(data_root)
    changed = [
        path for path in sorted(set(before["files"]) | set(after["files"]))
        if before["files"].get(path) != after["files"].get(path)
    ]
    coverage_ok = report["ok"]
    report["source_data"] = {
        "before": {key: value for key, value in before.items() if key != "files"},
        "after": {key: value for key, value in after.items() if key != "files"},
        "unchanged": before == after,
        "changed_paths": changed,
    }
    report["ok"] = coverage_ok and not changed
    report["autonomous_ticks"] = 0
    report["deleted_paths"] = []
    _write_manifest(output, report)
    print(json.dumps({
        "ok": report["ok"],
        "coverage_ok": coverage_ok,
        "manifest": str(output),
        "summary": report["summary"],
        "source_data_unchanged": report["source_data"]["unchanged"],
        "deletion_authorized": False,
        "errors": report["errors"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
