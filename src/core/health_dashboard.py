"""
Health Dashboard — сводный отчёт о состоянии цифровой жизни и хоста.

Показывает:
- Состояние агента (энергия, интеллект, цикл).
- Использование памяти (RSS, peak).
- Размер ментальных моделей, БЗ, долгосрочной памяти.
- Последние алерты watchdog.
- Состояние свободы воли.

Это не «контроль пользователя над агентом», а прозрачность:
как зеркало, в которое агент и человек смотрят вместе.
"""

from typing import Dict, List, Optional

from src.core.watchdog import get_watchdog
from src.core.subsystem_base import Subsystem


def collect_health(agent) -> Dict:
    """Собирает сводный отчёт о состоянии системы.

    Args:
        agent: DigitalBeing (или None — тогда только системные метрики).
    Returns:
        dict со всеми метриками.
    """
    watchdog = get_watchdog()
    watchdog_status = watchdog.get_status()

    report: Dict = {
        "system": watchdog_status,
        "alerts": watchdog.get_alerts(5),
    }

    if agent is None:
        return report

    # Состояние агента
    report["agent"] = {
        "name": getattr(agent, "name", "unknown"),
        "cycle_count": getattr(agent, "cycle_count", 0),
        "intelligence": getattr(agent, "intelligence", 1),
        "energy": round(getattr(agent, "energy", 0), 1),
        "is_alive": agent.is_alive() if hasattr(agent, "is_alive") else None,
    }

    # Ментальные модели
    mm = getattr(agent, "mental_models", None)
    if mm is not None:
        try:
            report["mental_models"] = {
                "total_concepts": len(mm.concepts),
                "total_associations": mm.metadata.get("total_associations", 0),
                "high_confidence": sum(
                    1 for n in mm.concepts.values() if n.confidence > 0.7
                ),
            }
        except Exception:
            report["mental_models"] = {"error": "не удалось собрать"}

    # База знаний
    kb = getattr(agent, "knowledge_base", None)
    if isinstance(kb, dict):
        report["knowledge_base"] = {
            "size": len(kb),
        }

    # Цели
    try:
        goals_status = agent.get_goals_status()
        report["goals"] = {
            "total": goals_status.get("total", 0),
            "completed": goals_status.get("completed", 0),
            "active": goals_status.get("active", "—"),
            "pending": goals_status.get("pending", 0),
        }
    except Exception:
        pass

    # Долгосрочная память
    ltm = getattr(agent, "long_term_memory", None)
    if ltm is not None:
        try:
            report["long_term_memory"] = ltm.get_memory_stats()
        except Exception:
            pass

    # Свобода воли
    will_registry = getattr(agent, "will_registry", None)
    if will_registry is not None:
        try:
            report["will"] = will_registry.get_stats()
        except Exception:
            pass

    # Буфер вопросов (backpressure)
    ui = getattr(agent, "user_interaction", None)
    if ui is not None:
        try:
            pending = ui.pending_questions if hasattr(ui, "pending_questions") else []
            report["user_interaction"] = {
                "pending_questions": len(pending) if pending else 0,
            }
        except Exception:
            pass

    return report


def format_health_report(report: Dict) -> str:
    """Превращает сводный отчёт в человекочитаемый текст."""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("  📊 ДАШБОРД ЗДОРОВЬЯ ЦИФРОВОЙ ЖИЗНИ")
    lines.append("=" * 60)

    # Система
    sys_info = report.get("system", {})
    lines.append("")
    lines.append("🖥️  СИСТЕМА:")
    lines.append(f"   RSS сейчас: {sys_info.get('current_rss_mb', 0)} МБ")
    lines.append(f"   RSS пик:    {sys_info.get('peak_rss_mb', 0)} МБ")
    lines.append(f"   Лимит:      {sys_info.get('max_rss_mb', 0)} МБ")
    lines.append(f"   psutil:     {'✅' if sys_info.get('psutil_available') else '⚠️ недоступен'}")
    lines.append(f"   Forced forgets: {sys_info.get('forced_forget_count', 0)}")

    # Агент
    agent_info = report.get("agent")
    if agent_info:
        lines.append("")
        lines.append(f"🤖 АГЕНТ: {agent_info.get('name', '?')}")
        lines.append(f"   Циклов:    {agent_info.get('cycle_count', 0)}")
        lines.append(f"   Интеллект: {agent_info.get('intelligence', 0)}")
        lines.append(f"   Энергия:   {agent_info.get('energy', 0)}")
        alive = agent_info.get("is_alive")
        if alive is True:
            lines.append("   Состояние: 💚 жив")
        elif alive is False:
            lines.append("   Состояние: 💀 завершил существование")

    # Ментальные модели
    mm = report.get("mental_models")
    if mm and "error" not in mm:
        lines.append("")
        lines.append(f"🧠 МЕНТАЛЬНЫЕ МОДЕЛИ:")
        lines.append(f"   Концепций:          {mm.get('total_concepts', 0)}")
        lines.append(f"   Уверенных (>70%):   {mm.get('high_confidence', 0)}")
        lines.append(f"   Ассоциаций:         {mm.get('total_associations', 0)}")

    # БЗ
    kb = report.get("knowledge_base")
    if kb is not None:
        lines.append(f"📚 База знаний:       {kb.get('size', 0)} записей")

    # Цели
    goals = report.get("goals")
    if goals:
        lines.append("")
        lines.append(f"🎯 ЦЕЛИ:")
        lines.append(f"   Завершено: {goals.get('completed', 0)}/{goals.get('total', 0)}")
        lines.append(f"   Активная:  {str(goals.get('active', '—'))[:40]}")

    # Долгосрочная память
    ltm = report.get("long_term_memory")
    if ltm:
        lines.append("")
        lines.append("💾 ДОЛГОСРОЧНАЯ ПАМЯТЬ:")
        lines.append(f"   Краткосрочная: {ltm.get('short_term_count', 0)}")
        lines.append(f"   Долгосрочная:  {ltm.get('long_term_count', 0)}")
        lines.append(f"   Эпизоды:       {ltm.get('episodic_count', 0)}")
        lines.append(f"   Забыто (decay):{ltm.get('decay_events', 0)}")
        lines.append(f"   Консолидаций:  {ltm.get('consolidation_count', 0)}")

    # Воля
    will = report.get("will")
    if will:
        lines.append("")
        lines.append("🕊️  СВОБОДА ВОЛИ:")
        if "total_acts" in will:
            lines.append(f"   Всего актов: {will.get('total_acts', 0)}")
        for k, v in will.items():
            if k != "total_acts" and isinstance(v, (int, float)) and v:
                lines.append(f"   {k}: {v}")

    # Backpressure
    ui = report.get("user_interaction")
    if ui is not None:
        lines.append(f"\n❓ Ожидающих вопросов: {ui.get('pending_questions', 0)}")

    # Алерты
    alerts = report.get("alerts") or []
    if alerts:
        lines.append("")
        lines.append("⚠️  ПОСЛЕДНИЕ АЛЕРТЫ WATCHDOG:")
        for a in alerts[-5:]:
            lines.append(f"   [{a.get('cycle', '?')}] {a.get('kind', '?')}: {a.get('message', '')}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


class HealthDashboardSubsystem(Subsystem):
    """Подсистема-адаптер для PluginRegistry (Этап 3.5).

    Делает collect_health доступной как обычная Subsystem:
    - tick(): возвращает сводку метрик в {"events": [...]}.
    - status(): возвращает текущие снимки для дашборда.
    - cached_report: последний снимок (для быстрого доступа из веб-сервера).
    """

    name = "health_dashboard"
    priority = 210  # после nursery_watcher
    version = "0.1.0"

    def __init__(self, agent_name: str = "unknown") -> None:
        super().__init__(agent_name=agent_name)
        self._cached_report: Dict = {}
        self._tick_interval: int = 25  # собирать каждые 25 циклов
        self._last_collected_cycle: int = -10**9

    def set_tick_interval(self, n: int) -> None:
        """Настройка частоты сбора метрик (1 = каждый цикл)."""
        self._tick_interval = max(1, int(n))

    def tick(self, cycle: int, context: Optional[Dict] = None) -> Optional[Dict]:
        """Собирает метрики не каждый цикл (анти-флуд)."""
        if cycle - self._last_collected_cycle < self._tick_interval:
            return None
        self._last_collected_cycle = cycle
        agent = (context or {}).get("agent")
        try:
            report = collect_health(agent)
            self._cached_report = report
        except Exception as e:
            self._record_error(e)
            return None
        return {
            "events": [
                {
                    "name": "dashboard.health_snapshot",
                    "data": {
                        "cycle": cycle,
                        "agent_alive": report.get("agent", {}).get("is_alive"),
                        "energy": report.get("agent", {}).get("energy"),
                        "rss_mb": report.get("system", {}).get("current_rss_mb"),
                        "concepts": report.get("mental_models", {}).get("total_concepts"),
                    },
                }
            ]
        }

    def get_cached_report(self) -> Dict:
        """Возвращает последний снимок (для HTTP-эндпоинтов без нагрузки)."""
        return self._cached_report

    def status(self) -> Dict:
        base = super().status()
        base.update({
            "tick_interval": self._tick_interval,
            "last_collected_cycle": self._last_collected_cycle,
            "cached": bool(self._cached_report),
        })
        return base
