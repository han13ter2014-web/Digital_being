"""
Внутренний симулятор для автономного обучения через мысленные эксперименты.

Агент может:
- Моделировать последствия действий БЕЗ их реального выполнения
- Находить похожий опыт в памяти для аналогий
- Прогнозировать результаты разных стратегий
- 'Практиковаться' мысленно перед реальными действиями
"""

from collections import defaultdict
from typing import Optional
from datetime import datetime


class SimulationMemory:
    """Память реальных и смоделированных событий для симуляции."""
    
    def __init__(self):
        self.real_events = []      # Реальные события с исходами
        self.simulated_events = [] # Мысленные эксперименты
        self.causal_rules = {}     # Причинно-следственные связи: {действие -> [результаты]}
    
    def store_real_event(self, action: str, context: str, outcome: str, 
                         success: bool, confidence: float = 0.5):
        """Сохраняет реальный опыт."""
        event = {
            "type": "real",
            "action": action,
            "context": context,
            "outcome": outcome,
            "success": success,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat()
        }
        self.real_events.append(event)
        
        # Обновляет причинно-следственные правила
        if action not in self.causal_rules:
            self.causal_rules[action] = []
        self.causal_rules[action].append({
            "outcome": outcome,
            "success": success,
            "context": context
        })
    
    def store_simulation(self, action: str, context: str, predicted_outcome: str,
                         actual_outcome: str = None, success: bool = None):
        """Сохраняет мысленный эксперимент."""
        event = {
            "type": "simulation",
            "action": action,
            "context": context,
            "predicted_outcome": predicted_outcome,
            "actual_outcome": actual_outcome,
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
        self.simulated_events.append(event)


class MentalSimulation:
    """Результат одного мысленного эксперимента."""
    
    def __init__(self):
        self.action = ""
        self.context = ""
        self.predicted_outcome = ""
        self.confidence = 0.0
        self.alternative_strategies = []
        self.risks = []
        self.benefits = []
    
    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "context": self.context,
            "predicted_outcome": self.predicted_outcome,
            "confidence": round(self.confidence, 3),
            "alternative_strategies": self.alternative_strategies[:3],
            "risks": self.risks[:3],
            "benefits": self.benefits[:3]
        }


class InternalSimulator:
    """Внутренний симулятор для автономного обучения."""
    
    def __init__(self, agent_name: str = "agent"):
        self.agent_name = agent_name
        self.memory = SimulationMemory()
        
        # Параметры симуляции
        self.max_simulations = 10      # Максимум симуляций на одно решение
        self.min_experience_for_sim = 3  # Минимум опыта для симуляции
        
        # История точности предсказаний
        self.prediction_accuracy_history = []
        
        # Контекст для аналогий
        self.context_index = {}  # {ключевые_слова -> события}
    
    def _index_context(self, event: dict):
        """Индексирует событие по ключевым словам для быстрого поиска."""
        words = event.get("context", "").split() + event.get("action", "").split()
        
        for word in words:
            if len(word) > 3:  # Только значимые слова
                if word not in self.context_index:
                    self.context_index[word] = []
                self.context_index[word].append(event)
    
    def find_similar_experience(self, action: str, context: str, 
                                  max_results: int = 5) -> list[dict]:
        """Находит похожий опыт в памяти для данного действия/контекста."""
        # Ищет по ключевым словам из контекста и действия
        query_words = set(context.split() + action.split())
        
        scores = defaultdict(list)
        
        for word in query_words:
            if len(word) < 4:
                continue
            
            if word in self.context_index:
                for event in self.context_index[word]:
                    scores[event["action"]].append(event)
        
        # Сортирует по количеству совпадений
        ranked_actions = sorted(scores.items(), key=lambda x: len(x[1]), reverse=True)
        
        results = []
        for action, events in ranked_actions[:max_results]:
            # Берет лучшие события для этого действия
            best_events = sorted(events, 
                key=lambda e: (1 if e.get("success") else 0), 
                reverse=True)[:2]
            
            for event in best_events:
                if event not in results:
                    results.append(event)
        
        return results[:max_results]
    
    def simulate_outcome(self, planned_action: str, current_state: dict, 
                          context: str = "") -> MentalSimulation:
        """Предсказывает результат действия БЕЗ его выполнения."""
        simulation = MentalSimulation()
        simulation.action = planned_action
        simulation.context = context
        
        # Находит похожий опыт
        similar_experiences = self.find_similar_experience(planned_action, context)
        
        if len(similar_experiences) < self.min_experience_for_sim:
            # Недостаточно опыта для симуляции
            simulation.confidence = 0.1
            simulation.predicted_outcome = "неопределенно (мало опыта для " + planned_action + ")"
            simulation.alternative_strategies = ["собрать больше опыта для " + planned_action]
            return simulation
        
        # Анализирует похожие события
        successful = [e for e in similar_experiences if e.get("success", False)]
        failed = [e for e in similar_experiences if not e.get("success", True)]
        
        # Прогнозирует результат
        if successful and not failed:
            simulation.confidence = 0.85
            outcomes = [e["outcome"] for e in successful]
            simulation.predicted_outcome = "успешно: " + outcomes[0][:60]
            simulation.benefits = ["результат: " + o[:40] for o in outcomes]
        
        elif failed and not successful:
            simulation.confidence = 0.8
            simulation.predicted_outcome = "неудача: " + failed[0]['outcome'][:60] + "..."
            simulation.risks = ["риск: " + e['outcome'][:40] for e in failed]
        
        elif successful and failed:
            # Смешанный результат - среднее
            success_rate = len(successful) / (len(successful) + len(failed))
            
            if success_rate > 0.7:
                simulation.confidence = 0.6
                simulation.predicted_outcome = "вероятно успешно: " + successful[0]['outcome'][:50] + "..."
                simulation.benefits = ["возможный успех: " + e['outcome'][:40] for e in successful]
                simulation.risks = ["риск провала: " + e['outcome'][:40] for e in failed]
            else:
                simulation.confidence = 0.5
                simulation.predicted_outcome = "неопределенно (успех_" + str(round(success_rate * 100)) + "%)"
                simulation.risks = ["риск: " + e['outcome'][:40] for e in failed]
                simulation.benefits = ["выгода: " + e['outcome'][:40] for e in successful]
        
        else:
            simulation.confidence = 0.3
            simulation.predicted_outcome = "неизвестно"
        
        # Предлагает альтернативные стратегии
        alternative_outcomes = set()
        for event in similar_experiences:
            alt = self._extract_strategy_hint(event)
            if alt:
                alternative_outcomes.add(alt)
        
        simulation.alternative_strategies = list(alternative_outcomes)[:3]
        
        return simulation
    
    def _extract_strategy_hint(self, event: dict) -> str:
        """Извлекает подсказку стратегии из события."""
        ctx = event.get("context", "unknown")[:30]
        if event.get("success"):
            return "попробовать как: '" + ctx + "..." 
        else:
            return "избежать как: '" + ctx + "'."
    
    def run_mental_experiment(self, action: str, context: str, 
                               iterations: int = 5) -> dict:
        """Запускает мысленный эксперимент с вариациями."""
        results = {"success_count": 0, "total": iterations, "predictions": []}
        
        for i in range(iterations):
            # Немного варьирует контекст
            variant_context = f"{context}_эксперимент_{i}"
            
            simulation = self.simulate_outcome(action, {}, variant_context)
            results["predictions"].append(simulation.to_dict())
            
            if simulation.confidence > 0.6 and "успешно" in simulation.predicted_outcome:
                results["success_count"] += 1
        
        predicted_success_rate = results["success_count"] / results["total"]
        
        return {
            "action": action,
            "simulated_success_rate": round(predicted_success_rate, 3),
            "confidence": sum(p["confidence"] for p in results["predictions"]) / len(results["predictions"]),
            "best_prediction": max(results["predictions"], key=lambda p: p["confidence"]) if results["predictions"] else None,
            "recommendation": "выполнить" if predicted_success_rate > 0.6 else 
                             "осторожно" if predicted_success_rate > 0.3 else "избегать",
            "iterations": iterations
        }
    
    def compare_strategies(self, actions: list[str], context: str) -> list[dict]:
        """Сравнивает несколько стратегий и ранжирует по предсказанному успеху."""
        comparisons = []
        
        for action in actions:
            result = self.run_mental_experiment(action, context, iterations=3)
            comparisons.append(result)
        
        # Сортирует по simulated_success_rate * confidence
        comparisons.sort(
            key=lambda r: r["simulated_success_rate"] * r["confidence"], 
            reverse=True
        )
        
        return comparisons
    
    def learn_from_outcome(self, action: str, context: str, actual_outcome: str, 
                           success: bool):
        """Учится на реальном исходе действия."""
        # Сохраняет реальный опыт
        self.memory.store_real_event(action, context, actual_outcome, success)
        
        # Проверяет предыдущие симуляции этого действия
        similar_simulations = [
            s for s in self.memory.simulated_events 
            if s["action"] == action
        ]
        
        # Если были симуляции - корректирует точность
        if similar_simulations:
            for sim in similar_simulations:
                was_correct = (sim.get("predicted_outcome", "") and 
                             ("успешно" in actual_outcome) == (success))
                
                self.prediction_accuracy_history.append({
                    "action": action,
                    "was_correct": was_correct,
                    "timestamp": datetime.now().isoformat()
                })
        
        # Индексирует для будущего поиска
        event = {
            "action": action,
            "context": context,
            "outcome": actual_outcome,
            "success": success
        }
        self._index_context(event)
    
    def get_simulation_readiness(self) -> dict:
        """Оценивает готовность симулятора делать предсказания."""
        total_experience = len(self.memory.real_events)
        
        return {
            "total_real_events": total_experience,
            "unique_actions": len(set(e["action"] for e in self.memory.real_events)),
            "causal_rules_count": len(self.memory.causal_rules),
            "prediction_accuracy": self._get_avg_prediction_accuracy(),
            "ready_for_simulation": total_experience >= self.min_experience_for_sim
        }
    
    def _get_avg_prediction_accuracy(self) -> float:
        """Средняя точность предсказаний."""
        if not self.prediction_accuracy_history:
            return 0.0
        
        correct = sum(1 for p in self.prediction_accuracy_history if p["was_correct"])
        return correct / len(self.prediction_accuracy_history)
    
    def get_status(self) -> dict:
        """Статус системы симуляции."""
        readiness = self.get_simulation_readiness()
        
        # Топ причинно-следственных правил
        top_rules = {}
        for action, outcomes in self.memory.causal_rules.items():
            success_rate = sum(1 for o in outcomes if o["success"]) / len(outcomes)
            top_rules[action] = {
                "attempts": len(outcomes),
                "success_rate": round(success_rate, 3)
            }
        
        return {
            "simulation_readiness": readiness,
            "top_causal_rules": dict(sorted(top_rules.items(), 
                            key=lambda x: x[1]["attempts"], reverse=True)[:5]),
            "simulations_stored": len(self.memory.simulated_events),
            "prediction_history_count": len(self.prediction_accuracy_history)
        }
    
    def to_dict(self) -> dict:
        """Серилизует систему."""
        return {
            "agent_name": self.agent_name,
            "memory_summary": {
                "real_events": len(self.memory.real_events),
                "simulated_events": len(self.memory.simulated_events),
                "causal_rules_count": len(self.memory.causal_rules)
            },
            "prediction_accuracy": self._get_avg_prediction_accuracy(),
            "status": self.get_status()
        }