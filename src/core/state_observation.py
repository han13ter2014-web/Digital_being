"""Лонгитюдные sanitized-наблюдения и их локальный ZIP-экспорт.

Модуль только читает уже собранные DTO и записи ``metric_samples``. Он не
вызывает действия, не меняет эмоции/цели и не ставит диагнозы. Сырые причины,
тексты диалогов, темы работ, пути и идентификаторы устройств в whitelist не
входят.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4
import zipfile

from src.core.emotional_state import EMOTIONS

JOURNAL_SCHEMA_VERSION = 1
EXPORT_SCHEMA_VERSION = 1
OBSERVATION_INTERVAL_CYCLES = 30
OBSERVATION_NAME = "wellbeing.observation"
EPISODE_NAME = "wellbeing.episode"
GAP_NAME = "wellbeing.gap"
METRIC_NAMES = (OBSERVATION_NAME, EPISODE_NAME, GAP_NAME)
_CODE_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _integer(value, default=0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _code(value, default="unknown") -> str:
    if not isinstance(value, str):
        return default
    return value if _CODE_RE.fullmatch(value) else default


def _numbers(source: dict, fields) -> dict:
    result = {}
    for field in fields:
        value = _number(source.get(field))
        if value is not None:
            result[field] = value
    return result


def _action(entry) -> dict | None:
    if not isinstance(entry, dict):
        return None
    action = _code(entry.get("action"), "")
    if not action:
        return None
    result = {"action": action}
    status = _code(entry.get("status"), "")
    if status:
        result["status"] = status
    if entry.get("cycle") is not None:
        result["cycle"] = _integer(entry.get("cycle"))
    return result


def observation_from_snapshot(
    snapshot: dict, *, observed_at: str | None = None
) -> dict:
    """Применить frozen whitelist к UI snapshot, не сериализуя его целиком."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    life = snapshot.get("life") if isinstance(snapshot.get("life"), dict) else {}
    body_source = snapshot.get("body") if isinstance(snapshot.get("body"), dict) else {}
    emotions_source = (
        snapshot.get("emotions") if isinstance(snapshot.get("emotions"), dict) else {}
    )
    motivation_source = (
        snapshot.get("motivation")
        if isinstance(snapshot.get("motivation"), dict)
        else {}
    )
    hardware_source = (
        snapshot.get("hardware") if isinstance(snapshot.get("hardware"), dict) else {}
    )
    hormonal_source = (
        snapshot.get("hormonal_projection")
        if isinstance(snapshot.get("hormonal_projection"), dict)
        else {}
    )
    intentions = (
        snapshot.get("intentions")
        if isinstance(snapshot.get("intentions"), dict)
        else {}
    )
    now = snapshot.get("now") if isinstance(snapshot.get("now"), dict) else {}
    activities = (
        snapshot.get("activities")
        if isinstance(snapshot.get("activities"), dict)
        else {}
    )
    goals_source = (
        snapshot.get("goals") if isinstance(snapshot.get("goals"), dict) else {}
    )

    body = _numbers(
        {**body_source, "energy": life.get("energy")},
        (
            "energy",
            "fatigue",
            "atp",
            "atp_ratio",
            "glucose",
            "mitochondrial_health",
        ),
    )
    if isinstance(body_source.get("needs_rest"), bool):
        body["needs_rest"] = body_source["needs_rest"]
    fatigue_level = _code(body_source.get("fatigue_level"), "")
    if fatigue_level:
        body["fatigue_level"] = fatigue_level

    raw_levels = emotions_source.get("levels")
    raw_levels = raw_levels if isinstance(raw_levels, dict) else {}
    levels = {
        name: value
        for name in EMOTIONS
        if (value := _number(raw_levels.get(name))) is not None
    }
    mixture_source = emotions_source.get("mixture")
    mixture_source = mixture_source if isinstance(mixture_source, dict) else {}
    emotions = {
        "levels": levels,
        "mixture": _numbers(mixture_source, ("total_intensity", "valence", "arousal")),
    }
    dominant = emotions_source.get("dominant")
    if isinstance(dominant, dict) and dominant.get("emotion") in EMOTIONS:
        emotions["dominant"] = dominant["emotion"]

    needs = {}
    raw_needs = motivation_source.get("needs")
    for name, entry in (raw_needs if isinstance(raw_needs, dict) else {}).items():
        code = _code(name, "")
        if not code or not isinstance(entry, dict):
            continue
        item = _numbers(
            entry,
            (
                "base_level",
                "current_level",
                "deficit",
                "urgency",
                "threshold",
                "priority",
            ),
        )
        if isinstance(entry.get("pressing"), bool):
            item["pressing"] = entry["pressing"]
        if item:
            needs[code] = item
    drives = {}
    raw_drives = motivation_source.get("drives")
    for name, entry in (raw_drives if isinstance(raw_drives, dict) else {}).items():
        code = _code(name, "")
        if not code or not isinstance(entry, dict):
            continue
        item = _numbers(entry, ("current_level", "threshold"))
        if isinstance(entry.get("active"), bool):
            item["active"] = entry["active"]
        if item:
            drives[code] = item
    motivation = {"needs": needs, "drives": drives}
    motivation.update(
        _numbers(motivation_source, ("goals_generated", "last_generated_cycle"))
    )

    activity_counts = {}
    for name, entry in activities.items():
        code = _code(name, "")
        if code and isinstance(entry, dict):
            count = _number(entry.get("count"))
            if count is not None:
                activity_counts[code] = count
    behavior = {
        "current_activity": _action(now.get("activity")),
        "last_finished_activity": _action(intentions.get("last_finished")),
        "activity_counts": activity_counts,
    }
    hardware = {
        "initialized": hardware_source.get("initialized") is True,
        "mode": _code(hardware_source.get("mode")),
    }
    hardware.update(_numbers(hardware_source, ("episode_count",)))
    recent_events = hardware_source.get("recent_events")
    if isinstance(recent_events, list):
        hardware["recent_event_count"] = len(recent_events)

    hormonal = {
        "initialized": hormonal_source.get("initialized") is True,
        "mode": _code(hormonal_source.get("mode")),
        "time_model": _code(hormonal_source.get("time_model")),
        "levels": _numbers(
            hormonal_source.get("levels")
            if isinstance(hormonal_source.get("levels"), dict)
            else {},
            ("dopamine", "serotonin", "oxytocin", "cortisol", "prolactin"),
        ),
    }
    profiles = {}
    raw_profiles = hormonal_source.get("profile")
    for name, entry in (raw_profiles if isinstance(raw_profiles, dict) else {}).items():
        code = _code(name, "")
        if code and isinstance(entry, dict):
            profiles[code] = _numbers(
                entry,
                (
                    "baseline",
                    "sensitivity",
                    "half_life_scale",
                    "confidence",
                    "sample_count",
                ),
            )
    hormonal["profile"] = profiles

    sources = {
        "body": body_source or life,
        "emotions": emotions_source,
        "motivation": motivation_source,
        "hardware": hardware_source,
        "hormonal_projection": hormonal_source,
        "goals": goals_source,
    }
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "observed_at": observed_at or utc_now(),
        "cycle": _integer(life.get("cycle")),
        "time_mode": _code(life.get("speed_mode")),
        "body": body,
        "emotions": emotions,
        "motivation": motivation,
        "behavior": behavior,
        "hardware": hardware,
        "hormonal_projection": hormonal,
        "goals": _numbers(goals_source, ("total", "completed")),
        "data_quality": {
            "missing_sections": sorted(
                name for name, source in sources.items() if not source
            )
        },
    }


def emotion_episode_records(
    emotional_state, *, observed_at: str | None = None
) -> list[dict]:
    """Sanitize эпизоды; ordinal отличает повторы внутри одного цикла."""
    episodes = getattr(emotional_state, "episodes", None)
    if not isinstance(episodes, list):
        return []
    timestamp = observed_at or utc_now()
    occurrences = Counter()
    records = []
    for entry in episodes:
        if not isinstance(entry, dict) or entry.get("emotion") not in EMOTIONS:
            continue
        cycle = _integer(entry.get("cycle"), -1)
        intensity = _number(entry.get("intensity"))
        if cycle < 0 or intensity is None:
            continue
        event = _code(entry.get("event"), "other")
        identity = (cycle, event, entry["emotion"])
        occurrences[identity] += 1
        ordinal = occurrences[identity]
        records.append(
            {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "record_id": (f"episode:{cycle}:{event}:{entry['emotion']}:{ordinal}"),
                "observed_at": timestamp,
                "cycle": cycle,
                "event": event,
                "emotion": entry["emotion"],
                "intensity": intensity,
                "action": None,
                "outcome": None,
                "completeness": "partial",
            }
        )
    return records


def metric_record(record: dict, *, name: str, record_id: str) -> dict:
    """Обернуть sanitized payload для ``LifeDatabase.append_metric_samples``."""
    return {
        "ts": str(record["observed_at"]),
        "cycle": _integer(record.get("cycle")),
        "name": name,
        "value": record,
        "metadata": {"schema_version": JOURNAL_SCHEMA_VERSION, "record_id": record_id},
    }


def _jsonl(records: list[dict]) -> bytes:
    return "".join(canonical_json(record) + "\n" for record in records).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_export_rows(
    database, *, start_cycle=None, end_cycle=None
) -> tuple[dict, int]:
    grouped = {OBSERVATION_NAME: [], EPISODE_NAME: [], GAP_NAME: []}
    invalid = 0
    rows = database.read_metric_samples(
        names=METRIC_NAMES, start_cycle=start_cycle, end_cycle=end_cycle
    )
    for row in rows:
        try:
            value = json.loads(row["value_json"])
            metadata = json.loads(row["metadata_json"])
            if (
                row["name"] not in grouped
                or not isinstance(value, dict)
                or not isinstance(metadata, dict)
                or value.get("schema_version") != JOURNAL_SCHEMA_VERSION
            ):
                raise ValueError("invalid metric payload")
            value = dict(value)
            value.setdefault("record_id", metadata.get("record_id"))
            grouped[row["name"]].append(value)
        except (TypeError, ValueError, json.JSONDecodeError, KeyError):
            invalid += 1
    return grouped, invalid


def _code_version() -> str:
    try:
        return importlib.metadata.version("digital-being")
    except importlib.metadata.PackageNotFoundError:
        return "0.2.0"


def _line_chart(
    title: str, series: list[tuple[str, list[tuple[int, float]], str]]
) -> str:
    width, height, pad = 920, 250, 34
    all_values = [value for _, points, _ in series for _, value in points]
    if not all_values:
        return f"<section><h2>{html.escape(title)}</h2><p>Нет данных.</p></section>"
    low, high = min(all_values), max(all_values)
    if math.isclose(low, high):
        low, high = low - 0.5, high + 0.5
    max_cycle = max(
        (cycle for _, points, _ in series for cycle, _ in points), default=1
    )
    min_cycle = min(
        (cycle for _, points, _ in series for cycle, _ in points), default=0
    )
    span = max(1, max_cycle - min_cycle)

    def point(cycle, value):
        x = pad + (cycle - min_cycle) / span * (width - 2 * pad)
        y = height - pad - (value - low) / (high - low) * (height - 2 * pad)
        return f"{x:.2f},{y:.2f}"

    shapes = []
    legend = []
    for index, (name, points, color) in enumerate(series):
        if points:
            coords = " ".join(point(cycle, value) for cycle, value in points)
            shapes.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{coords}"/>'
            )
        legend.append(f'<span style="color:{color}">●</span> {html.escape(name)}')
    return (
        f"<section><h2>{html.escape(title)}</h2>"
        f'<p class="muted">Диапазон: {low:.3f}…{high:.3f}; циклы {min_cycle}…{max_cycle}.</p>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
        f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#8490a0"/>'
        + "".join(shapes)
        + "</svg><p>"
        + " · ".join(legend)
        + "</p></section>"
    )


def render_report(
    manifest: dict, observations: list[dict], episodes: list[dict]
) -> bytes:
    """Автономный HTML: inline CSS/SVG, без JS, сети и внешних ресурсов."""
    energy = [
        (int(item["cycle"]), item["body"]["energy"])
        for item in observations
        if _number((item.get("body") or {}).get("energy")) is not None
    ]
    emotion_series = []
    for name, color in (
        ("joy", "#14875d"),
        ("sadness", "#6e56a3"),
        ("nostalgia", "#b06f13"),
        ("satisfaction", "#167c91"),
    ):
        points = []
        for item in observations:
            value = _number(
                ((item.get("emotions") or {}).get("levels") or {}).get(name)
            )
            if value is not None:
                points.append((int(item["cycle"]), value))
        emotion_series.append((name, points, color))
    episode_rows = []
    for item in episodes[-100:]:
        episode_rows.append(
            "<tr>"
            f"<td>{_integer(item.get('cycle'))}</td>"
            f"<td>{html.escape(_code(item.get('event')))}</td>"
            f"<td>{html.escape(_code(item.get('emotion')))}</td>"
            f"<td>{_number(item.get('intensity')) or 0:.3f}</td>"
            f"<td>{html.escape(str(item.get('completeness') or 'partial'))}</td>"
            "</tr>"
        )
    if not episode_rows:
        episode_rows.append('<tr><td colspan="5">Записей нет.</td></tr>')
    limitations = (
        "".join(
            f"<li>{html.escape(str(item))}</li>"
            for item in manifest["completeness"]["limitations"]
        )
        or "<li>Дополнительные ограничения не обнаружены; sampling всё равно не является полной биографией.</li>"
    )
    document = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Журнал состояния цифровой сущности</title>
<style>body{{max-width:1100px;margin:0 auto;padding:28px;background:#f5f7fa;color:#17202b;font:16px/1.55 system-ui,sans-serif}}section{{margin:18px 0;padding:20px;background:white;border:1px solid #d6dde6;border-radius:14px}}h1{{font-size:28px}}h2{{font-size:20px}}svg{{width:100%;height:auto}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #e3e8ee}}.warning{{background:#fff7df;border-color:#d7a932}}.muted{{color:#5c6875}}code{{overflow-wrap:anywhere}}@media(max-width:600px){{body{{padding:10px}}section{{padding:12px}}table{{font-size:12px}}}}</style></head><body>
<h1>Журнал состояния цифровой сущности</h1>
<section><p><strong>Life ID:</strong> <code>{html.escape(manifest['life_id'])}</code></p>
<p>Наблюдений: {len(observations)}; эпизодов: {len(episodes)}; период циклов: {manifest['period']['first_cycle']}…{manifest['period']['last_cycle']}.</p>
<p>Readiness: <strong>{html.escape(manifest['readiness'])}</strong>. Это наблюдение модели, не медицинское заключение.</p></section>
<section class="warning"><h2>Границы интерпретации</h2><p>Грусть, ностальгия, усталость и другие состояния не становятся диагнозом по одному значению или графику. Сигнал — только повод исследовать причины. Тело и гормональная проекция являются модельными величинами.</p><ul>{limitations}</ul></section>
{_line_chart('Энергия', [('energy', energy, '#167c91')])}
{_line_chart('Отдельные эмоции', emotion_series)}
<section><h2>Эмоциональные эпизоды</h2><p class="muted">Показаны последние не более 100 записей. Полный sanitized-набор находится в episodes.jsonl. Пустые action/outcome не заполняются догадками.</p><table><thead><tr><th>Цикл</th><th>Событие</th><th>Эмоция</th><th>Сила</th><th>Полнота</th></tr></thead><tbody>{''.join(episode_rows)}</tbody></table></section>
<section><h2>Машинные данные</h2><p>observations.jsonl, episodes.jsonl и interventions.jsonl сопровождаются SHA-256 в manifest.json. Источник interventions сейчас недоступен; пустой файл не означает отсутствие вмешательств.</p></section>
</body></html>"""
    return document.encode("utf-8")


def export_state_observations(
    database,
    destination,
    *,
    start_cycle=None,
    end_cycle=None,
    fresh_snapshot: bool,
    writer_status: dict | None = None,
) -> dict:
    """Создать ZIP атомарно из согласованного read-only среза SQLite."""
    grouped, invalid = _read_export_rows(
        database, start_cycle=start_cycle, end_cycle=end_cycle
    )
    observations = grouped[OBSERVATION_NAME]
    episodes = grouped[EPISODE_NAME]
    gaps = grouped[GAP_NAME]
    limitations = []
    if not fresh_snapshot:
        limitations.append("fresh_snapshot_unavailable")
    if gaps:
        limitations.append("recorded_gaps")
    if invalid:
        limitations.append("invalid_records_excluded")
    dropped = _integer((writer_status or {}).get("dropped_events"))
    if dropped:
        limitations.append("writer_dropped_events")
    if not observations:
        limitations.append("no_observations_in_period")
    cycles = [_integer(item.get("cycle")) for item in observations]
    timestamps = [str(item.get("observed_at")) for item in observations]
    latest = observations[-1] if observations else {}
    manifest = {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "journal_schema_version": JOURNAL_SCHEMA_VERSION,
        "export_id": uuid4().hex,
        "generated_at": utc_now(),
        "life_id": database.life_id,
        "code": {"package_version": _code_version()},
        "configuration": {
            "storage_schema_version": database.SCHEMA_VERSION,
            "observation_interval_cycles": OBSERVATION_INTERVAL_CYCLES,
            "emotional_palette": "emotional_state.v1",
            "time_mode": latest.get("time_mode", "unknown"),
        },
        "filter": {"start_cycle": start_cycle, "end_cycle": end_cycle},
        "period": {
            "first_cycle": min(cycles) if cycles else None,
            "last_cycle": max(cycles) if cycles else None,
            "first_observed_at": min(timestamps) if timestamps else None,
            "last_observed_at": max(timestamps) if timestamps else None,
        },
        "units": {
            "cycle": "core_tick",
            "energy": "model_units",
            "emotion": "normalized_0_to_1",
            "intensity": "normalized_0_to_1",
            "timestamp": "UTC_ISO_8601",
        },
        "fresh_snapshot": bool(fresh_snapshot),
        "readiness": "available" if observations else "insufficient_data",
        "counts": {
            "observations": len(observations),
            "episodes": len(episodes),
            "gaps": len(gaps),
            "invalid_records_excluded": invalid,
            "writer_dropped_events": dropped,
        },
        "interventions": {"status": "unavailable", "count": 0},
        "privacy": {
            "profile": "sanitized",
            "raw_dialogues": False,
            "creative_texts": False,
            "sqlite_copied": False,
        },
        "completeness": {
            "status": "partial" if limitations else "observed_retained_history",
            "limitations": limitations,
            "sampling": "point_samples_not_full_biography",
        },
    }
    payloads = {
        "observations.jsonl": _jsonl(observations),
        "episodes.jsonl": _jsonl(episodes),
        "interventions.jsonl": b"",
    }
    payloads["report.html"] = render_report(manifest, observations, episodes)
    manifest["files"] = {
        name: {"sha256": _sha256(payload), "bytes": len(payload)}
        for name, payload in payloads.items()
    }
    payloads["manifest.json"] = canonical_json(manifest).encode("utf-8") + b"\n"

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".state-observation-", suffix=".tmp", dir=str(target.parent)
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name in (
                "manifest.json",
                "observations.jsonl",
                "episodes.jsonl",
                "interventions.jsonl",
                "report.html",
            ):
                archive.writestr(name, payloads[name])
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest
