"""Снимок состояния агента для окна.

Окно живёт в отдельном потоке Tk, а агент — в потоке asyncio. Читать
внутренние словари агента прямо из потока окна нельзя: словарь может
измениться во время перебора (``dictionary changed size during
iteration``). Поэтому снимок собирается в потоке агента и передаётся
в окно как обычный словарь.

Функция чистая: не меняет агента, не пишет на диск, не ждёт сеть.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from src.core.paths import data_path


def energy_bar(energy: float, maximum: float, width: int = 10) -> str:
    """Полоска энергии из блоков. Максимум — заполненная полоса."""
    if maximum <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, float(energy) / float(maximum)))
    filled = int(round(ratio * width))
    return "▓" * filled + "░" * (width - filled)


def format_duration(seconds: float) -> str:
    """Длительность в виде «4ч 12м» / «12м 30с» / «45с»."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}ч {minutes:02d}м"
    if minutes:
        return f"{minutes}м {secs:02d}с"
    return f"{secs}с"


def memory_rss_mb() -> Optional[float]:
    """RSS процесса в МБ, если psutil доступен. Иначе None.

    Зависимость необязательная: окно должно работать и без psutil.
    """
    try:
        import psutil  # type: ignore
    except ImportError:
        return None
    try:
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def build_status_snapshot(
    agent: Any,
    runner: Optional[Any] = None,
    *,
    started_at: Optional[float] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Собирает плоский снимок для панели показателей.

    Args:
        agent: ``DigitalBeing`` (или совместимый объект).
        runner: ``AgentRunner`` (необязательно). Даёт режим скорости.
        started_at: момент запуска (для «живёт»).
        now: текущее время (для тестов).

    Returns:
        Плоский словарь. Отсутствующие данные — ``None`` или 0, но
        ключи всегда есть: окну не нужно проверять наличие.
    """
    now = time.time() if now is None else float(now)

    snapshot: Dict[str, Any] = {
        "name": getattr(agent, "name", "?"),
        "cycle": int(getattr(agent, "cycle_count", 0) or 0),
        "intelligence": getattr(agent, "intelligence", 0),
        "energy": float(getattr(agent, "energy", 0.0) or 0.0),
        "max_energy": 200.0,
        "concepts": 0,
        "goals_total": 0,
        "goals_completed": 0,
        "goals_active": "",
        "uptime_sec": None,
        "rss_mb": memory_rss_mb(),
        "speed_mode": None,
        "speed_interval_sec": None,
        "paused": None,
        "life_state": "unknown",
        "seed_folder": None,
        "parent_name": None,
        "pending_life_request": None,
    }

    # Энергия: потолок берём из конфига, если он доступен.
    try:
        from config.simulation_config import LR_CONFIG

        snapshot["max_energy"] = float(
            getattr(LR_CONFIG, "ENERGY_MAX", 200.0)
        )
    except Exception:
        pass

    # Концепции
    mental_models = getattr(agent, "mental_models", None)
    concepts = getattr(mental_models, "concepts", None)
    if isinstance(concepts, dict):
        snapshot["concepts"] = len(concepts)

    # Цели
    try:
        goals_view = agent.get_goals_status()
        if isinstance(goals_view, dict):
            snapshot["goals_total"] = int(goals_view.get("total", 0) or 0)
            snapshot["goals_completed"] = int(
                goals_view.get("completed", 0) or 0
            )
            snapshot["goals_active"] = str(goals_view.get("active", "") or "")
    except Exception:
        pass

    # Скорость
    if runner is not None:
        try:
            speed = runner.get_speed_status()
            snapshot["speed_mode"] = speed.get("mode")
            snapshot["speed_interval_sec"] = speed.get("interval_sec")
            snapshot["paused"] = speed.get("paused")
        except Exception:
            pass

    # Жизнь: состояние, семя, родитель
    guard = getattr(agent, "life_guard", None)
    if guard is not None:
        try:
            details = guard.state_details()
            snapshot["life_state"] = str(details.get("state", "unknown"))
            snapshot["seed_folder"] = details.get("seed_folder")
            pending = guard.pending_requests()
            if pending:
                request = pending[0]
                snapshot["pending_life_request"] = {
                    "request_id": request.request_id,
                    "kind": request.kind,
                    "reason": request.reason,
                    "seconds_until_confirmable": round(
                        request.seconds_until_confirmable(guard.clock()), 1
                    ),
                }
        except Exception:
            pass

    snapshot["parent_name"] = getattr(agent, "parent_name", None)

    if started_at is not None:
        snapshot["uptime_sec"] = max(0.0, now - float(started_at))

    return snapshot


def format_status_lines(snapshot: Dict[str, Any], width: int = 10) -> List[str]:
    """Строки для панели показателей. Чистая функция — удобно тестировать."""
    energy = float(snapshot.get("energy") or 0.0)
    maximum = float(snapshot.get("max_energy") or 200.0)
    lines = [
        f"Имя          {snapshot.get('name')}",
        f"Цикл         {snapshot.get('cycle')}",
        f"Энергия      {energy_bar(energy, maximum, width)}  "
        f"{energy:.0f}/{maximum:.0f}",
        f"Интеллект    {snapshot.get('intelligence')}",
        f"Концепций    {snapshot.get('concepts')}",
        f"Цели         {snapshot.get('goals_completed')}/"
        f"{snapshot.get('goals_total')}",
    ]

    uptime = snapshot.get("uptime_sec")
    lines.append(
        f"Живёт        {format_duration(uptime) if uptime is not None else '—'}"
    )

    rss = snapshot.get("rss_mb")
    lines.append(f"Память       {rss:.0f} МБ" if rss else "Память       —")

    mode = snapshot.get("speed_mode")
    interval = snapshot.get("speed_interval_sec")
    if mode:
        label = {
            "live": "Жизнь",
            "fast": "Ускорение",
            "max": "Лаборатория",
            "step": "Шаг",
        }.get(str(mode), str(mode))
        time_part = f"{interval}с" if interval else ""
        paused = " · пауза" if snapshot.get("paused") else ""
        lines.append(f"Режим        {label} {time_part}{paused}".rstrip())
    else:
        lines.append("Режим        —")

    life = str(snapshot.get("life_state", "unknown"))
    life_label = {
        "alive": "жив",
        "dormant": "спит (семя в Яслях)",
        "terminated": "ушёл",
    }.get(life, life)
    lines.append(f"Состояние    {life_label}")

    parent = snapshot.get("parent_name")
    if parent:
        lines.append(f"Родитель     {parent}")

    return lines