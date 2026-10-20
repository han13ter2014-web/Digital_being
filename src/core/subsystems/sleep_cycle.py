"""
SleepCycle — «сон» агента.

Аналогия с человеком: во сне мозг:
1. Консолидирует эпизодическую память в долговременную.
2. Отбрасывает шум и нерелевантное.
3. Находит скрытые паттерны между событиями.
4. «Очищает» когнитивный кэш (gc).

Вызывается периодически (раз в N циклов).
"""

from datetime import datetime
from typing import Dict, List


class SleepCycle:
    """Цикл сна — консолидация и очистка."""

    def __init__(self,
                 agent_name: str = "agent",
                 long_term_memory=None,
                 mental_models=None,
                 knowledge_subsystem=None,
                 cycle_interval: int = 100):
        self.agent_name = agent_name
        self.long_term_memory = long_term_memory
        self.mental_models = mental_models
        self.knowledge_subsystem = knowledge_subsystem
        self.cycle_interval = cycle_interval

        # Метрики сна
        self.total_sleeps = 0
        self.last_consolidated_count = 0
        self.last_patterns_found = []
        self.sleep_history: List[Dict] = []

    def attach_memory(self, ltm) -> None:
        self.long_term_memory = ltm

    def attach_mental_models(self, mm) -> None:
        self.mental_models = mm

    def attach_knowledge(self, ks) -> None:
        self.knowledge_subsystem = ks

    # ============================================================
    # Главный метод
    # ============================================================
    def sleep(self, cycle_count: int) -> Dict:
        """Один цикл сна. Вызывается каждые `cycle_interval` циклов.

        Шаги:
        1. Консолидация значимых концепций в LongTermMemory.
        2. Очистка слабых связей в mental_models.
        3. Поиск скрытых паттернов.
        4. Прунинг knowledge_base.
        """
        if cycle_count % self.cycle_interval != 0 and self.total_sleeps > 0:
            return {"slept": False, "reason": "не время"}

        consolidated = 0
        patterns = []

        # 1. Консолидация значимых концепций в LTM
        if self.long_term_memory and self.mental_models:
            for name, node in self.mental_models.concepts.items():
                # Берём только те, что имеют высокую уверенность + несколько опытов
                if node.confidence >= 0.6 and len(node.experiences) >= 2:
                    try:
                        # Формируем summary
                        summary = f"{name}: {node.definition_hypothesis[:80]}"
                        self.long_term_memory.store(
                            content=summary,
                            importance=node.confidence,
                            context=f"sleep_cycle_{cycle_count}",
                            memory_type="semantic",
                        )
                        consolidated += 1
                    except Exception:
                        pass

        # 2. Поиск паттернов: концепции, появившиеся вместе
        if self.mental_models:
            patterns = self._find_co_occurrence_patterns()

        # 3. Лёгкая очистка memory cache (через gc — будет в agent)
        # 4. Лог сна
        sleep_record = {
            "cycle": cycle_count,
            "timestamp": datetime.now().isoformat(),
            "consolidated_count": consolidated,
            "patterns_found": len(patterns),
            "patterns": patterns[:3],  # топ-3
        }
        self.sleep_history.append(sleep_record)
        self.last_consolidated_count = consolidated
        self.last_patterns_found = patterns
        self.total_sleeps += 1

        return sleep_record

    def _find_co_occurrence_patterns(self) -> List[Dict]:
        """Ищет паттерны: концепции, которые встречались в одном контексте."""
        patterns = []
        if not self.mental_models:
            return patterns

        # Группируем концепции по контекстам
        from collections import defaultdict
        context_groups: Dict[str, list] = defaultdict(list)

        for name, node in self.mental_models.concepts.items():
            for exp in node.experiences:
                ctx = exp.get("context", "")
                if ctx:
                    context_groups[ctx].append(name)

        # Контексты с 3+ концепциями = сильный паттерн
        for ctx, concepts in context_groups.items():
            if len(concepts) >= 3:
                patterns.append({
                    "context": ctx[:50],
                    "concepts": concepts[:5],
                    "strength": min(1.0, len(concepts) / 5),
                })

        return patterns[:5]

    # ============================================================
    # Утилиты
    # ============================================================
    def get_status(self) -> Dict:
        return {
            "total_sleeps": self.total_sleeps,
            "last_consolidated": self.last_consolidated_count,
            "last_patterns": len(self.last_patterns_found),
            "interval": self.cycle_interval,
        }