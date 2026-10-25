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
            # Действия, которые до этого не были подключены к петле:
            # агент мог «захотеть» спросить или рассказать, но ничего не
            # происходило. Счётчики нужны, чтобы увидеть, что проводка
            # работает, и чтобы дельта мира замечала эффект.
            "messages_sent": 0,
            "questions_asked": 0,
            "web_searches": 0,
            "goals_set": 0,
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

    def to_dict(self) -> Dict:
        """Сериализует журнал воли для чекпоинта / снапшота."""
        return {
            "agent_name": self.agent_name,
            "entries": list(self.entries),
            "counters": dict(self._counters),
            "last_value_change_cycle": self._last_value_change_cycle,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "WillRegistry":
        """Восстанавливает журнал воли из сериализованного состояния."""
        registry = cls(agent_name=data.get("agent_name") or "agent")
        registry.entries = [dict(e) for e in (data.get("entries") or [])]
        registry._counters = dict(data.get("counters") or {})
        registry._last_value_change_cycle = int(data.get("last_value_change_cycle") or 0)
        return registry