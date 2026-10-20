"""Модуль рефлексии и самоанализа агента"""
import json
from datetime import datetime
from collections import defaultdict


class ReflectionEngine:
    """Анализирует собственную производительность и адаптирует поведение"""

    def __init__(self):
        self.performance_history = []
        self.learning_patterns = defaultdict(list)
        self.effectiveness_metrics = {
            'success_rate': 0,
            'learning_speed': 0,
            'goal_completion_rate': 0,
            'knowledge_growth_rate': 0
        }
        self.insights = []
        self.strategy_adjustments = []

    def record_cycle(self, agent_state):
        """Записывает метрики цикла для анализа"""
        cycle_data = {
            'cycle': agent_state.get('cycle_count', 0),
            'intelligence': agent_state.get('intelligence', 1),
            'energy': agent_state.get('energy', 100),
            'success_streak': agent_state.get('success_streak', 0),
            'completed_goals': agent_state.get('completed_goals', 0),
            'knowledge_size': len(agent_state.get('knowledge_base', {})),
            'timestamp': datetime.now().isoformat()
        }
        self.performance_history.append(cycle_data)
        return cycle_data

    def analyze_performance(self, window_size=10):
        """Анализирует производительность за последние N циклов"""
        if len(self.performance_history) < window_size:
            return None

        recent = self.performance_history[-window_size:]

        # Вычисляем метрики
        avg_intel_growth = (recent[-1]['intelligence'] - recent[0]['intelligence']) / window_size
        avg_energy = sum(c['energy'] for c in recent) / len(recent)
        knowledge_growth = recent[-1]['knowledge_size'] - recent[0]['knowledge_size']
        goal_progress = recent[-1]['completed_goals'] - recent[0]['completed_goals']

        metrics = {
            'avg_intelligence_growth': avg_intel_growth,
            'avg_energy': avg_energy,
            'knowledge_growth': knowledge_growth,
            'goal_progress': goal_progress,
            'efficiency': (goal_progress + knowledge_growth) / (window_size or 1)
        }

        self.effectiveness_metrics.update({
            'success_rate': min(100, (goal_progress / window_size) * 100) if window_size > 0 else 0,
            'learning_speed': knowledge_growth / window_size if window_size > 0 else 0,
            'goal_completion_rate': goal_progress / window_size if window_size > 0 else 0,
            'knowledge_growth_rate': knowledge_growth / window_size if window_size > 0 else 0
        })

        return metrics

    def identify_patterns(self):
        """Выявляет закономерности в поведении и обучении"""
        if len(self.performance_history) < 5:
            return []

        patterns = []

        # Паттерн 1: Стабильный рост
        recent = self.performance_history[-5:]
        intel_trend = [c['intelligence'] for c in recent]
        if intel_trend == sorted(intel_trend):
            patterns.append({
                'type': 'stable_growth',
                'description': 'Интеллект растёт стабильно',
                'confidence': 0.9
            })

        # Паттерн 2: Плато (застой)
        if all(x == intel_trend[0] for x in intel_trend):
            patterns.append({
                'type': 'plateau',
                'description': 'Обучение застопорилось. Нужен новый подход.',
                'confidence': 0.8
            })

        # Паттерн 3: Истощение энергии
        energy_trend = [c['energy'] for c in recent]
        if energy_trend == sorted(energy_trend, reverse=True):
            patterns.append({
                'type': 'energy_depletion',
                'description': 'Энергия уменьшается. Нужно оптимизировать действия.',
                'confidence': 0.85
            })

        # Паттерн 4: Ускорение обучения
        knowledge_growth = [c['knowledge_size'] for c in recent]
        if knowledge_growth[-1] - knowledge_growth[0] > 5:
            patterns.append({
                'type': 'accelerated_learning',
                'description': 'Ускорено накопление знаний',
                'confidence': 0.8
            })

        self.learning_patterns['recent'] = patterns
        return patterns

    def generate_insights(self):
        """Генерирует выводы из анализа производительности"""
        metrics = self.analyze_performance()
        if not metrics:
            return []

        insights = []

        if metrics['avg_intelligence_growth'] > 0.5:
            insights.append("✨ Быстрое развитие интеллекта. Продолжать текущую стратегию.")

        if metrics['goal_progress'] == 0:
            insights.append("⚠️ Цели не достигаются. Пересмотреть подход к обучению.")

        if metrics['efficiency'] > 1:
            insights.append("🚀 Высокая эффективность обучения. Уровень оптимален.")
        elif metrics['efficiency'] < 0.3:
            insights.append("🔧 Низкая эффективность. Требуется оптимизация стратегии.")

        if self.effectiveness_metrics['success_rate'] > 70:
            insights.append("🎯 Высокий процент успешных действий.")

        if self.effectiveness_metrics['learning_speed'] > 2:
            insights.append("📚 Интенсивное накопление знаний.")

        self.insights = insights
        return insights

    def suggest_strategy_adjustments(self, current_intelligence):
        """Рекомендует изменения в стратегии на основе анализа"""
        adjustments = []

        if self.effectiveness_metrics['success_rate'] < 50:
            adjustments.append({
                'priority': 'high',
                'recommendation': 'Снизить сложность текущих задач',
                'reason': 'Низкий процент успешных действий'
            })

        if self.effectiveness_metrics['knowledge_growth_rate'] < 1:
            adjustments.append({
                'priority': 'medium',
                'recommendation': 'Расширить источники знаний',
                'reason': 'Медленное накопление информации'
            })

        if current_intelligence > 5:
            adjustments.append({
                'priority': 'medium',
                'recommendation': 'Ставить более сложные цели',
                'reason': 'Высокий уровень интеллекта'
            })

        patterns = self.identify_patterns()
        if any(p['type'] == 'plateau' for p in patterns):
            adjustments.append({
                'priority': 'high',
                'recommendation': 'Пересмотреть подход к изучению',
                'reason': 'Обнаружено плато в развитии'
            })

        self.strategy_adjustments = adjustments
        return adjustments

    def generate_report(self, agent_state):
        """Создаёт полный отчёт о самоанализе"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'cycle': agent_state.get('cycle_count', 0),
            'current_metrics': {
                'intelligence': agent_state.get('intelligence', 1),
                'energy': agent_state.get('energy', 100),
                'completed_goals': agent_state.get('completed_goals', 0),
                'knowledge_base_size': len(agent_state.get('knowledge_base', {}))
            },
            'effectiveness': self.effectiveness_metrics,
            'recent_patterns': self.identify_patterns(),
            'insights': self.generate_insights(),
            'strategy_recommendations': self.suggest_strategy_adjustments(agent_state.get('intelligence', 1))
        }
        return report

    def save_reflection_report(self, report, filename='data/logs/reflection_report.json'):
        """Сохраняет отчёт о самоанализе"""
        try:
            reports = []
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    reports = json.load(f)
            except:
                reports = []

            reports.append(report)

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(reports, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Ошибка при сохранении отчёта: {e}")

    def reflect(self):
        """Основной метод рефлексии - вызывает все процессы анализа"""
        return {
            'patterns': self.identify_patterns(),
            'insights': self.generate_insights(),
            'metrics': self.analyze_performance()
        }


# ============================================================
# Public API
# ============================================================
__all__ = [
    # Классы
    "ReflectionEngine",
]
