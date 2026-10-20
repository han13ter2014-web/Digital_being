import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

from src.core.paths import data_path


@dataclass
class CodeModification:
    """Запись об изменении кода."""
    timestamp: datetime
    module_name: str
    function_name: str
    old_code: str
    new_code: str
    reason: str
    success: bool
    performance_impact: float  # Как изменилась эффективность (0.1 = +10%)


class SelfEvolutionAnalyzer:
    """Анализирует производительность агента и предлагает самоулучшения."""

    def __init__(self, agent):
        self.agent = agent
        self.modification_history: List[CodeModification] = []
        self.performance_metrics: Dict[str, List[float]] = {}
        self.identified_bottlenecks: List[Dict] = []
        self.evolution_file = data_path(
            "evolution", f"{agent.name}_self_modifications.json"
        )

        os.makedirs(data_path("evolution"), exist_ok=True)
        self._load_history()

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
                'description': 'Энергия тратится неэффективно. Нужна оптимизация action_costs.',
                'suggestion': 'Уменьшить базовые затраты на actions или улучшить success rate'
            })

        # 2. Анализ памяти
        if len(self.agent.mental_models.concepts) > 500:
            improvements.append({
                'category': 'memory_management',
                'severity': 'medium',
                'description': 'Слишком много концепций. Необходимо забывание.',
                'suggestion': 'Включить более агрессивное забывание слабых концепций'
            })

        # 3. Анализ целей
        pending_goals = sum(1 for g in self.agent.goals if g.get('status') == 'pending')
        if pending_goals > 5:
            improvements.append({
                'category': 'goal_management',
                'severity': 'medium',
                'description': 'Много невыполненных целей. Нужна переоценка приоритетов.',
                'suggestion': 'Рассмотреть разбиение целей на подцели или увеличение параллелизма'
            })

        # 4. Анализ успеха
        if self._calculate_goal_completion_rate() < 0.3:
            improvements.append({
                'category': 'learning_strategy',
                'severity': 'high',
                'description': 'Низкий процент завершения целей.',
                'suggestion': 'Пересмотреть стратегию гипотезирования или обратиться к пользователю чаще'
            })

        # 5. Качество концепций
        if self._calculate_concepts_quality() < 0.4:
            improvements.append({
                'category': 'concept_quality',
                'severity': 'medium',
                'description': 'Концепции имеют низкую уверенность.',
                'suggestion': 'Улучшить механизм валидации или задавать больше уточняющих вопросов'
            })

        self.identified_bottlenecks = improvements
        return improvements

    def generate_code_suggestion(self, improvement: Dict) -> Optional[Dict]:
        """Генерирует предложение по изменению кода."""
        category = improvement['category']

        if category == 'energy_efficiency':
            return {
                'module': 'src/core/agent.py',
                'change_type': 'parameter_adjustment',
                'current': 'self._action_costs = {"default": 2, "hypothesis": 3, ...}',
                'suggested': 'self._action_costs = {"default": 1, "hypothesis": 2, ...}',
                'reason': 'Снизить энергетические затраты на 30-50% для лучшей эффективности',
                'estimated_impact': 0.15  # +15% эффективность
            }

        elif category == 'goal_management':
            return {
                'module': 'src/cognition/goal_management.py',
                'change_type': 'parameter_adjustment',
                'current': 'max_active_goals = 1',
                'suggested': 'max_active_goals = 3',
                'reason': 'Включить параллельное выполнение целей',
                'estimated_impact': 0.25  # +25% эффективность
            }

        elif category == 'learning_strategy':
            return {
                'module': 'src/core/agent.py',
                'change_type': 'enable_feature',
                'feature': 'HYPOTHESIS_GENERATION_ENABLED',
                'current': False,
                'suggested': True,
                'reason': 'Активировать генерацию гипотез для лучшего обучения',
                'estimated_impact': 0.20  # +20% эффективность
            }

        return None

    def apply_self_modification(self, suggestion: Dict) -> bool:
        """Применяет самоулучшение (параметры, не код)."""
        try:
            if suggestion['change_type'] == 'parameter_adjustment':
                # Применяем изменения параметров
                self._apply_parameter_change(suggestion)
                return True

            elif suggestion['change_type'] == 'enable_feature':
                # Включаем функции
                self._enable_feature(suggestion)
                return True

            return False

        except Exception as e:
            print(f"Ошибка при применении модификации: {e}")
            return False

    def _apply_parameter_change(self, suggestion: Dict):
        """Применяет изменение параметра."""
        module = suggestion['module']

        if 'action_costs' in suggestion['current']:
            # Понижаем все затраты на 30%
            for action_type, cost in self.agent._action_costs.items():
                self.agent._action_costs[action_type] = max(1, int(cost * 0.7))

        # Логируем изменение
        self._record_modification(
            module=module,
            function='parameter_adjustment',
            old_code=suggestion['current'],
            new_code=suggestion['suggested'],
            reason=suggestion['reason'],
            success=True,
            impact=suggestion.get('estimated_impact', 0.1)
        )

    def _enable_feature(self, suggestion: Dict):
        """Включает функцию."""
        from config.simulation_config import LR_CONFIG

        feature = suggestion['feature']

        if hasattr(LR_CONFIG, feature):
            setattr(LR_CONFIG, feature, suggestion['suggested'])

            self._record_modification(
                module=suggestion['module'],
                function='feature_flag',
                old_code=f"{feature} = {suggestion['current']}",
                new_code=f"{feature} = {suggestion['suggested']}",
                reason=suggestion['reason'],
                success=True,
                impact=suggestion.get('estimated_impact', 0.1)
            )

    def _record_modification(self, module: str, function: str,
                            old_code: str, new_code: str,
                            reason: str, success: bool, impact: float):
        """Записывает модификацию."""
        modification = CodeModification(
            timestamp=datetime.now(),
            module_name=module,
            function_name=function,
            old_code=old_code,
            new_code=new_code,
            reason=reason,
            success=success,
            performance_impact=impact
        )

        self.modification_history.append(modification)
        self._save_history()

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
        """Генерирует отчет о самоанализе."""
        performance = self.analyze_performance()
        improvements = self.identify_improvements()

        return {
            'timestamp': datetime.now().isoformat(),
            'performance': performance,
            'identified_improvements': improvements,
            'modification_history': [
                {
                    'timestamp': m.timestamp.isoformat(),
                    'module': m.module_name,
                    'reason': m.reason,
                    'success': m.success,
                    'impact': m.performance_impact
                }
                for m in self.modification_history[-10:]  # Последние 10
            ],
            'recommendations': self._generate_recommendations(performance, improvements)
        }

    def _generate_recommendations(self, performance: Dict, improvements: List[Dict]) -> List[str]:
        """Генерирует рекомендации."""
        recommendations = []

        if performance['overall_score'] < 0.4:
            recommendations.append("⚠️  Общая производительность низкая. Требуется комплексное улучшение.")

        if performance['energy_efficiency'] < 0.3:
            recommendations.append("💡 Рассмотрите оптимизацию энергетических затрат.")

        if performance['goal_completion_rate'] < 0.2:
            recommendations.append("🎯 Целей завершается очень мало. Пересмотрите стратегию целей.")

        if len(improvements) > 3:
            recommendations.append("📈 Много возможностей для улучшения. Начните с высокого приоритета.")

        if not recommendations:
            recommendations.append("✅ Агент работает хорошо. Продолжайте в том же направлении.")

        return recommendations

    def _save_history(self):
        """Сохраняет историю модификаций."""
        try:
            data = {
                'modifications': [
                    {
                        'timestamp': m.timestamp.isoformat(),
                        'module': m.module_name,
                        'function': m.function_name,
                        'old_code': m.old_code,
                        'new_code': m.new_code,
                        'reason': m.reason,
                        'success': m.success,
                        'impact': m.performance_impact
                    }
                    for m in self.modification_history
                ]
            }

            with open(self.evolution_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения истории: {e}")

    def _load_history(self):
        """Загружает историю модификаций."""
        if not os.path.exists(self.evolution_file):
            return

        try:
            with open(self.evolution_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for mod_data in data.get('modifications', []):
                modification = CodeModification(
                    timestamp=datetime.fromisoformat(mod_data['timestamp']),
                    module_name=mod_data['module'],
                    function_name=mod_data['function'],
                    old_code=mod_data['old_code'],
                    new_code=mod_data['new_code'],
                    reason=mod_data['reason'],
                    success=mod_data['success'],
                    performance_impact=mod_data['impact']
                )
                self.modification_history.append(modification)
        except Exception as e:
            print(f"Ошибка загрузки истории: {e}")
