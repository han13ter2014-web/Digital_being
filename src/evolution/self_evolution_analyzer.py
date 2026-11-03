"""SelfEvolutionAnalyzer — глаз самоэволюции: наблюдает, не вмешивается.

«Эволюция-1» (2026-11-03): из анализатора убрано молчаливое
самоприменение (``apply_self_modification`` и вся машинерия записи
модификаций). Канон EVOLUTION.md: эволюция — диалог, а не
одностороннее действие. Существо может *заметить* узкое место и
*предложить* изменение человеку (через ArchitectureProposal и
`src/evolution/self_coding.py`), но не может менять себя само.

Живой контур вызывает:
    analyze_performance()  — метрики состояния;
    identify_improvements() — список узких мест (сигналы);
    generate_self_report() — человеко-читаемый отчёт.
"""

from typing import Dict, List


class SelfEvolutionAnalyzer:
    """Анализирует состояние агента и находит узкие места.

    Только наблюдение: методы не меняют ни агента, ни конфиги.
    """

    def __init__(self, agent):
        self.agent = agent
        self.identified_bottlenecks: List[Dict] = []

    def analyze_performance(self) -> Dict:
        """Анализирует текущую производительность агента."""
        analysis = {
            'intelligence': self.agent.intelligence,
            'energy_efficiency': self._calculate_energy_efficiency(),
            'goal_completion_rate': self._calculate_goal_completion_rate(),
            'learning_speed': self._calculate_learning_speed(),
            'memory_efficiency': self._calculate_memory_efficiency(),
            'concepts_quality': self._calculate_concepts_quality(),
            'overall_score': 0.0
        }

        # Вычисляем общий скор
        scores = [v for k, v in analysis.items() if k != 'overall_score' and isinstance(v, (int, float))]
        analysis['overall_score'] = sum(scores) / len(scores) if scores else 0.0

        return analysis

    def identify_improvements(self) -> List[Dict]:
        """Идентифицирует возможные улучшения."""
        improvements = []

        # 1. Анализ энергии
        if self._calculate_energy_efficiency() < 0.5:
            improvements.append({
                'category': 'energy_efficiency',
                'severity': 'high',
                'description': 'Энергия тратится неэффективно.',
                'suggestion': 'Раньше уходить на отдых, чтобы меньше действий проваливалось'
            })

        # 2. Анализ памяти
        if len(self.agent.mental_models.concepts) > 500:
            improvements.append({
                'category': 'memory_management',
                'severity': 'medium',
                'description': 'Слишком много концепций. Необходимо забывание.',
                'suggestion': 'Чаще отпускать слабые концепции'
            })

        # 3. Анализ целей
        pending_goals = sum(1 for g in self.agent.goals if g.get('status') == 'pending')
        if pending_goals > 5:
            improvements.append({
                'category': 'goal_management',
                'severity': 'medium',
                'description': 'Много невыполненных целей. Нужна переоценка приоритетов.',
                'suggestion': 'Рассмотреть разбиение целей на подцели'
            })

        # 4. Анализ успеха
        if self._calculate_goal_completion_rate() < 0.3:
            improvements.append({
                'category': 'learning_strategy',
                'severity': 'high',
                'description': 'Низкий процент завершения целей.',
                'suggestion': 'Пересмотреть стратегию или обратиться к пользователю чаще'
            })

        # 5. Качество концепций
        if self._calculate_concepts_quality() < 0.4:
            improvements.append({
                'category': 'concept_quality',
                'severity': 'medium',
                'description': 'Концепции имеют низкую уверенность.',
                'suggestion': 'Держать в памяти более уверенные концепции'
            })

        self.identified_bottlenecks = improvements
        return improvements

    def _calculate_energy_efficiency(self) -> float:
        """Вычисляет эффективность использования энергии."""
        if self.agent.cycle_count == 0:
            return 0.5

        total_energy_spent = 100 * self.agent.cycle_count - self.agent.energy
        goals_completed = self.agent.completed_goals
        concepts_learned = len(self.agent.mental_models.concepts)

        if total_energy_spent == 0:
            return 0.5

        efficiency = (goals_completed * 10 + concepts_learned) / total_energy_spent
        return min(1.0, max(0.0, efficiency / 2))  # Нормализуем

    def _calculate_goal_completion_rate(self) -> float:
        """Вычисляет процент завершения целей."""
        total_goals = len(self.agent.goals)
        if total_goals == 0:
            return 0.5

        completed = len([g for g in self.agent.goals if g.get('status') == 'completed'])
        return completed / total_goals

    def _calculate_learning_speed(self) -> float:
        """Вычисляет скорость обучения."""
        if self.agent.cycle_count == 0:
            return 0.5

        concepts_per_cycle = len(self.agent.mental_models.concepts) / self.agent.cycle_count
        return min(1.0, concepts_per_cycle * 100)

    def _calculate_memory_efficiency(self) -> float:
        """Вычисляет эффективность памяти."""
        total_concepts = len(self.agent.mental_models.concepts)
        high_confidence = sum(1 for n in self.agent.mental_models.concepts.values() if n.confidence > 0.7)

        if total_concepts == 0:
            return 0.5

        efficiency = high_confidence / total_concepts
        return efficiency

    def _calculate_concepts_quality(self) -> float:
        """Вычисляет среднее качество концепций."""
        if not self.agent.mental_models.concepts:
            return 0.5

        avg_confidence = sum(n.confidence for n in self.agent.mental_models.concepts.values()) / len(
            self.agent.mental_models.concepts)
        return avg_confidence

    def generate_self_report(self) -> Dict:
        """Генерирует отчёт о самоанализе (только наблюдение)."""
        performance = self.analyze_performance()
        improvements = self.identify_improvements()

        return {
            'performance': performance,
            'identified_improvements': improvements,
            'recommendations': self._generate_recommendations(performance, improvements)
        }

    def _generate_recommendations(self, performance: Dict, improvements: List[Dict]) -> List[str]:
        """Генерирует рекомендации."""
        recommendations = []

        if performance['overall_score'] < 0.4:
            recommendations.append("Общая производительность низкая. Требуется комплексное улучшение.")

        if performance['energy_efficiency'] < 0.3:
            recommendations.append("Стоит оптимизировать энергетические затраты.")

        if performance['goal_completion_rate'] < 0.2:
            recommendations.append("Целей завершается очень мало. Стоит пересмотреть стратегию целей.")

        if len(improvements) > 3:
            recommendations.append("Много возможностей для улучшения. Начать с высокого приоритета.")

        if not recommendations:
            recommendations.append("Агент работает хорошо. Продолжать в том же направлении.")

        return recommendations
