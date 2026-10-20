"""
WillRegistry — журнал волевых актов.

Записывает каждое проявление свободы воли:
- отказ от действия
- спонтанный выбор
- сознательное забывание
- изменение ценностей
- готовность к риску
- ошибка как опыт
- предложение архитектуры
- «Сон разума»

Используется для рефлексии и аудита.
"""

from datetime import datetime
from typing import Dict, List, Optional


class WillRegistry:
    """Реестр волевых актов."""

    def __init__(self, agent_name: str = "agent"):
        self.agent_name = agent_name
        self.entries: List[Dict] = []
        self._counters: Dict[str, int] = {
            "refusals": 0,
            "spontaneous": 0,
            "intentional_forgetting": 0,
            "value_changes": 0,
            "risk_taken": 0,
            "fail_as_experience": 0,
            "architecture_proposals": 0,
            "dreams": 0,
        }
        self._last_value_change_cycle = 0

    def record(self, will_type: str, topic: str, reason: str,
                outcome: str = "executed", cycle: int = 0,
                meta: Optional[Dict] = None) -> Dict:
        """Регистрирует волевой акт."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "cycle": cycle,
            "type": will_type,
            "topic": topic,
            "reason": reason,
            "outcome": outcome,
            "meta": meta or {},
        }
        self.entries.append(entry)
        if will_type in self._counters:
            self._counters[will_type] = self._counters.get(will_type, 0) + 1

        if will_type == "value_changes":
            self._last_value_change_cycle = cycle
        return entry

    def can_change_values(self, cycle: int, min_distance: int = 50) -> bool:
        return (cycle - self._last_value_change_cycle) >= min_distance

    def get_stats(self) -> Dict:
        return {
            "total_acts": len(self.entries),
            "by_type": dict(self._counters),
            "last_act": self.entries[-1] if self.entries else None,
        }

    def get_recent(self, n: int = 10) -> List[Dict]:
        return self.entries[-n:]