"""
ReflectionPipeline — обёртка над ReflectionEngine.

Инкапсулирует:
- Сбор метрик цикла
- Запуск рефлексии (паттерны, инсайты, рекомендации)
- Сохранение отчётов в data/logs/reflection_report.json
"""

from typing import Dict, Optional


class ReflectionPipeline:
    """Конвейер рефлексии — обёртка над ReflectionEngine."""

    def __init__(self, agent_name: str = "agent"):
        from src.cognition.reflection_engine import ReflectionEngine
        self.engine = ReflectionEngine()
        self.agent_name = agent_name

    def record_cycle(self, agent) -> None:
        """Записывает метрики текущего цикла."""
        agent_state = {
            "cycle_count": agent.cycle_count,
            "intelligence": agent.intelligence,
            "energy": agent.energy,
            "success_streak": agent.success_streak,
            "completed_goals": agent.completed_goals,
            "knowledge_base": (
                agent.knowledge_subsystem.knowledge_base
                if hasattr(agent, "knowledge_subsystem")
                else getattr(agent, "knowledge_base", {})
            ),
        }
        self.engine.record_cycle(agent_state)

    def reflect(self) -> Dict:
        """Возвращает текущие паттерны и инсайты."""
        return self.engine.reflect()

    def get_metrics(self) -> Dict:
        """Возвращает метрики эффективности."""
        return dict(self.engine.effectiveness_metrics)

    def generate_report(self, agent) -> Dict:
        """Генерирует и сохраняет полный отчёт."""
        agent_state = {
            "cycle_count": agent.cycle_count,
            "intelligence": agent.intelligence,
            "energy": agent.energy,
            "success_streak": agent.success_streak,
            "completed_goals": agent.completed_goals,
            "knowledge_base": (
                agent.knowledge_subsystem.knowledge_base
                if hasattr(agent, "knowledge_subsystem")
                else getattr(agent, "knowledge_base", {})
            ),
        }
        report = self.engine.generate_report(agent_state)
        self.engine.save_reflection_report(report)
        return report