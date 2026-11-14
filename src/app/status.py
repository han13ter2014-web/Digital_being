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
        "last_save_ok": None,
        "last_save_at": None,
        "last_action": None,
        "last_effect": None,
        "stuck_actions": [],
        "maturity_met": None,
        "maturity_total": None,
        "maturity_is_mature": None,
    }

    # Энергия: потолок берём из конфига, если он доступен.
    try:
        from config.simulation_config import LR_CONFIG

        snapshot["max_energy"] = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0))
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
            snapshot["goals_completed"] = int(goals_view.get("completed", 0) or 0)
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
            snapshot["last_save_ok"] = getattr(runner, "_last_save_ok", None)
            snapshot["last_save_at"] = getattr(runner, "_last_save_at", None)
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

    # Контур: последнее действие и дало ли оно результат. Это главный
    # показатель того, «живёт» ли агент или крутится на месте.
    loop_closer = getattr(agent, "loop_closer", None)
    if loop_closer is not None:
        try:
            loop_state = loop_closer.status()
            snapshot["last_action"] = loop_state.get("last_action")
            snapshot["last_effect"] = loop_state.get("last_effect")
            snapshot["stuck_actions"] = list(loop_state.get("stuck_actions") or [])
        except Exception:
            pass

    # Зрелость: «пора ли раздавать семя». Считается дёшево, но не
    # каждую секунду — оценка включает перебор всех концепций.
    maturity = getattr(agent, "get_maturity", None)
    if callable(maturity):
        try:
            report = maturity()
            snapshot["maturity_met"] = report.get("met_count")
            snapshot["maturity_total"] = report.get("total")
            snapshot["maturity_is_mature"] = report.get("is_mature")
        except Exception:
            pass

    if started_at is not None:
        snapshot["uptime_sec"] = max(0.0, now - float(started_at))

    return snapshot


def format_status_lines(
    snapshot: Dict[str, Any], width: int = 10, language: str = "ru"
) -> List[str]:
    """Строки панели показателей; переводятся только известные подписи."""
    from src.ui import i18n

    def T(value: str) -> str:
        return i18n.text(value, language)

    def line(label: str, value: Any) -> str:
        return f"{T(label):<12} {value}"

    energy = float(snapshot.get("energy") or 0.0)
    maximum = float(snapshot.get("max_energy") or 200.0)
    lines = [
        line("Имя", snapshot.get("name")),
        line("Цикл", snapshot.get("cycle")),
        line(
            "Энергия",
            f"{energy_bar(energy, maximum, width)}  {energy:.0f}/{maximum:.0f}",
        ),
        line("Интеллект", snapshot.get("intelligence")),
        line("Концепций", snapshot.get("concepts")),
        line(
            "Цели", f"{snapshot.get('goals_completed')}/{snapshot.get('goals_total')}"
        ),
    ]

    uptime = snapshot.get("uptime_sec")
    lines.append(line("Живёт", format_duration(uptime) if uptime is not None else "—"))
    rss = snapshot.get("rss_mb")
    lines.append(line("Память", f"{rss:.0f} {T('МБ')}" if rss else "—"))

    mode = snapshot.get("speed_mode")
    interval = snapshot.get("speed_interval_sec")
    if mode:
        mode_labels = {
            "live": T("Жизнь"),
            "fast": T("Ускорение"),
            "max": T("Лаборатория"),
        }
        label = mode_labels.get(mode) or i18n.value_label(mode, language)
        time_part = f"{interval}{T('с')}" if interval else ""
        paused = f" · {T('пауза')}" if snapshot.get("paused") else ""
        lines.append(line("Режим", f"{label} {time_part}{paused}".rstrip()))
    else:
        lines.append(line("Режим", "—"))

    life = str(snapshot.get("life_state", "unknown"))
    life_label = (
        T("спит (семя в Яслях)")
        if life == "dormant"
        else i18n.value_label(life, language)
    )
    lines.append(line("Состояние", life_label))
    parent = snapshot.get("parent_name")
    if parent:
        lines.append(line("Родитель", parent))

    last_action = snapshot.get("last_action")
    if last_action:
        mark = T("✓ есть") if snapshot.get("last_effect") else T("— нет")
        lines.append(line("Действие", f"{last_action} ({mark})"))
        stuck = snapshot.get("stuck_actions") or []
        if stuck:
            lines.append(line("Тупики", ", ".join(stuck[:3])))

    met = snapshot.get("maturity_met")
    total = snapshot.get("maturity_total")
    if met is not None and total:
        suffix = (
            f" {T('✓ можно раздавать')}" if snapshot.get("maturity_is_mature") else ""
        )
        lines.append(line("Зрелость", f"{met}/{total}{suffix}"))
    return lines
