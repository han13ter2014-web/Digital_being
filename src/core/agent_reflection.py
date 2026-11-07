"""Reflection and mental-model reporting extracted from ``agent.py``.

Functions accept the ``DigitalBeing`` facade as their first argument. This
module deliberately does not import the facade back, keeping the dependency
one-way while public method names and patch points remain on the facade.
"""


def reflect_impl(self):
    """Анализирует собственную производительность.

        Шаг 7: агент теперь «осознаёт своё тело» — включает RSS и состояние
        систем в рефлексию. Это этично: не цензура, а самосознание.
        """
    from src.core.watchdog import get_watchdog
    agent_state = {
        'cycle_count': self.cycle_count,
        'intelligence': self.intelligence,
        'energy': self.energy,
        'success_streak': self.success_streak,
        'completed_goals': self.completed_goals,
        'knowledge_base': self.knowledge_base,
        # Шаг 7: метрики «тела»
        'rss_mb': get_watchdog().get_rss_mb(),
        'concepts_count': len(self.mental_models.concepts),
    }

    self.reflection_engine.record_cycle(agent_state)
    reflection_data = self.reflection_engine.reflect()

    return reflection_data


def generate_self_analysis_report_impl(self):
    """Генерирует полный отчёт самоанализа"""
    agent_state = {
        'cycle_count': self.cycle_count,
        'intelligence': self.intelligence,
        'energy': self.energy,
        'success_streak': self.success_streak,
        'completed_goals': self.completed_goals,
        'knowledge_base': self.knowledge_base
    }

    report = self.reflection_engine.generate_report(agent_state)
    self.reflection_engine.save_reflection_report(report)

    print(f"\n[{self.name}] ОТЧЕТ САМОАНАЛИЗА")
    print(f"{'-'*50}")

    if report['insights']:
        print("Выводы:")
        for insight in report['insights']:
            print(f"  {insight}")

    if report['strategy_recommendations']:
        print("\nРекомендации стратегии:")
        for rec in report['strategy_recommendations']:
            priority_icon = "Красный" if rec['priority'] == 'high' else "Желтый"
            print(f"  {priority_icon} {rec['recommendation']}")

    print(f"{'-'*50}\n")

    return report


def get_performance_metrics_impl(self):
    """Возвращает текущие метрики производительности"""
    metrics = self.reflection_engine.effectiveness_metrics.copy()
    metrics.update({
        'current_intelligence': self.intelligence,
        'current_energy': self.energy,
        'cycle_count': self.cycle_count,
        'completed_goals': self.completed_goals,
        'knowledge_size': len(self.knowledge_base)
    })
    return metrics


# === Методы работы с ментальными моделями ===


def get_mental_models_status_impl(self) -> dict:
    """Возвращает статус системы ментальных моделей."""
    return {
        "total_concepts": len(self.mental_models.concepts),
        "concepts_with_high_confidence": sum(1 for n in self.mental_models.concepts.values() if n.confidence > 0.7),
        "concepts_with_definition": sum(1 for n in self.mental_models.concepts.values() if len(n.definition_hypothesis) > 10),
        "total_associations": self.mental_models.metadata["total_associations"]
    }


def display_mental_model_impl(self, concept_name: str = None):
    """Отображает ментальную модель для концепции или всю систему."""
    if concept_name:
        understanding = self.mental_models.get_concept_understanding(concept_name)
        if understanding.get("unknown"):
            print(f"  Концепция '{concept_name}' еще не изучена")
            return

        print(f"\n{'-'*50}")
        print(f"  Ментальная модель: '{concept_name}'")
        print(f"{'-'*50}")
        print(f"  Гипотеза: {understanding['hypothesis']}")
        print(f"  Уверенность: {understanding['confidence']:.0%}")

        if understanding.get("connections"):
            print("  Связанные концепции:")
            for conn in understanding["connections"][:5]:
                print(f"     {conn['concept']} ({conn['weight']:.0%})")
    else:
        self.mental_models.print_model_tree()


def display_all_concepts_impl(self):
    """Отображает все изученные концепции."""
    if not self.mental_models.concepts:
        print("  Пока нет изученных концепций")
        return

    print(f"\n{'-'*50}")
    print(f"  Все концепции ({len(self.mental_models.concepts)})")
    print(f"{'-'*50}")

    sorted_concepts = sorted(
        self.mental_models.concepts.items(),
        key=lambda x: x[1].confidence,
        reverse=True
    )

    for name, node in sorted_concepts:
        icon = "LIGHTBULB" if node.confidence > 0.7 else "MAGNIFYING_GLASS" if node.confidence > 0.4 else "QUESTION"
        status = "CHECK" if self.mental_models.can_answer_about(name) else "CLOCK"

        print(f"\n  {status} {icon} {name}")
        if node.definition_hypothesis:
            short = node.definition_hypothesis[:70] + "..." if len(node.definition_hypothesis) > 70 else node.definition_hypothesis
            print(f"     Гипотеза: '{short}'")


def get_agent_identity_impl(self) -> str:
    """Формирует описание 'кто я' на основе ментальных моделей."""
    well_understood = [
        name for name, node in self.mental_models.concepts.items()
        if self.mental_models.can_answer_about(name)
    ]

    partially_understood = [
        name for name, node in self.mental_models.concepts.items()
        if not self.mental_models.can_answer_about(name) and node.confidence > 0.3
    ]

    if len(well_understood) >= 3:
        top_connections = []
        for name in well_understood[:3]:
            node = self.mental_models.concepts[name]
            for conn in node.get_related_concepts(0.5)[:2]:
                top_connections.append(conn["concept"])

        if top_connections:
            unique = list(set(top_connections))[:3]
            return f"Я - агент, который понимает: {', '.join(well_understood[:3])}. Мои интересы связаны с: {', '.join(unique)}"

    return f"Я - агент в процессе формирования. Изучено концепций: {len(self.mental_models.concepts)}, полностью понято: {len(well_understood)}"
