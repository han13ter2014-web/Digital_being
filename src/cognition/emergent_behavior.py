"""
Эмергентное поведение — незапланированные способности возникающие из взаимодействий.

Эмерджентные свойства НЕ были запрограммированы заранее - они ВОЗНИКЛИ из:
- Комбинаций простых правил
- Петлей обратной связи
- Нелинейных взаимодействий компонентов
- Накопления малых изменений
"""

from collections import defaultdict
from typing import Optional
from datetime import datetime
import hashlib


class BehaviorPattern:
    """Паттерн поведения - выявленный из наблюдений."""
    
    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category  # cognitive, social, creative, analytical
        
        # Статистика наблюдения
        self.observation_count = 0
        # Сколько раз проявлялся
        self.contexts = []  # Контексты в которых проявлялся
        self.combinations = []  # Комбинации компонентов которые его вызвали
        
        # Сила паттерна (сколько раз наблюдали)
        self.strength = 0.0
        
        # Предсказуемость (насколько стабилен)
        self.consistency = 0.0
        
        # Связанные компоненты
        self.active_components = defaultdict(list)
        
        self.created_at = datetime.now()
    
    def record_observation(self, context: str, active_comps: list[str]):
        """Записывает наблюдение паттерна."""
        self.observation_count += 1
        
        # Вычисляет силу (скользящее среднее новых наблюдений)
        self.strength = min(1.0, self.observation_count * 0.15)
        
        # Вычисляет консистентность
        if self.observation_count > 1:
            # Если контексты похожи - консистентность растет
            similar_contexts = sum(1 for c in self.contexts 
                                   if self._contexts_overlap(c, context))
            self.consistency = similar_contexts / self.observation_count
        
        self.contexts.append(context)
        self.combinations.append(active_comps.copy())
        
        # Сохраняет последние 50 записей
        if len(self.contexts) > 50:
            self.contexts = self.contexts[-50:]
            self.combinations = self.combinations[-50:]
    
    def _contexts_overlap(self, ctx1: str, ctx2: str) -> bool:
        """Проверяет перекрытие контекстов."""
        words1 = set(ctx1.split())
        words2 = set(ctx2.split())
        return len(words1 & words2) > 2
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "observation_count": self.observation_count,
            "strength": round(self.strength, 3),
            "consistency": round(self.consistency, 3),
            "top_contexts": self.contexts[:3],
            "most_common_combination": self._get_most_common_combo()
        }
    
    def _get_most_common_combo(self) -> list[str]:
        """Находит самое частое сочетание компонентов."""
        combo_counts = defaultdict(int)
        for combo in self.combinations:
            key = tuple(sorted(combo))
            combo_counts[key] += 1
        
        if combo_counts:
            best = max(combo_counts.items(), key=lambda x: x[1])
            return list(best[0])
        return []


class EmergenceEngine:
    """Двигатель эмерджентных явлений."""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.created_at = datetime.now()
        
        # Выявленные паттерны поведения
        self.discovered_patterns: dict[str, BehaviorPattern] = {}
        
        # Сигналы для выявления эмерджентных явлений
        self.component_signals = defaultdict(list)  # {component -> [значения]}
        
        # Комбинации компонентов
        self.component_combinations = defaultdict(int)
        
        # Эмерджентные события (непредвиденные явления)
        self.emergent_events = []
        
        # История состояний агента
        self.state_history = []
        
        # Критерии эмерджентности
        self.combination_threshold = 3  # Минимум наблюдений для паттерна
        self.novelty_threshold = 0.5    # Порог новизны
        
        # Метрики
        self.metrics = {
            "total_emergent_events": 0,
            "unique_patterns_discovered": 0,
            "most_emergent_component": None,
        }
    
    def record_state(self, component_states: dict[str, float], 
                     action_taken: str = "", result: str = ""):
        """Записывает состояние компонентов агента."""
        state = {
            "timestamp": datetime.now().isoformat(),
            "components": component_states.copy(),
            "action": action_taken,
            "result": result
        }
        self.state_history.append(state)
        
        # Обновляет сигналы компонентов
        for comp, value in component_states.items():
            self.component_signals[comp].append(value)
            # Хранит последние 100 значений
            if len(self.component_signals[comp]) > 100:
                self.component_signals[comp] = self.component_signals[comp][-100:]
        
        # Записывает комбинацию активных компонентов
        active_comps = [c for c, v in component_states.items() if v > 0.5]
        if len(active_comps) >= 2:
            combo_key = tuple(sorted(active_comps))
            self.component_combinations[combo_key] += 1
    
    def detect_emergent_patterns(self) -> list[str]:
        """Выявляет новые эмерджентные паттерны из комбинаций компонентов."""
        new_patterns = []
        
        # Ищет комбинации с достаточным количеством наблюдений
        for combo, count in self.component_combinations.items():
            if count >= self.combination_threshold:
                # Генерирует название паттерна
                pattern_name = self._generate_pattern_name(combo)
                
                # Проверяет существует ли уже
                if pattern_name not in self.discovered_patterns:
                    # Создает новый паттерн
                    category = self._infer_category(combo)
                    pattern = BehaviorPattern(pattern_name, category)
                    
                    # Формирует контекст из комбинации
                    context = f"комбинация {'+'.join(combo)}"
                    pattern.record_observation(context, list(combo))
                    
                    self.discovered_patterns[pattern_name] = pattern
                    new_patterns.append(pattern_name)
                    
                    # Записывает эмерджентное событие
                    emergent_event = {
                        "type": "pattern_discovery",
                        "pattern_name": pattern_name,
                        "components": list(combo),
                        "observations": count,
                        "timestamp": datetime.now().isoformat()
                    }
                    self.emergent_events.append(emergent_event)
                    
                    self.metrics["total_emergent_events"] += 1
                    self.metrics["unique_patterns_discovered"] = len(self.discovered_patterns)
        
        return new_patterns
    
    def detect_emergent_capabilities(self) -> list[dict]:
        """Выявляет новые способности из успешных комбинаций."""
        emergent_capabilities = []
        
        # Анализирует состояния где была успешная активность
        for state in self.state_history[-50:]:  # Последние 50 состояний
            if not state.get("result"):
                continue
            
            # Если результат успешный - проверяет комбинацию
            if "success" in state["result"] or "успешно" in state["result"]:
                active_comps = [c for c, v in state["components"].items() if v > 0.5]
                
                if len(active_comps) >= 2:
                    combo_key = tuple(sorted(active_comps))
                    
                    # Проверяет эмерджентность - новая комбинация?
                    is_emergent = True
                    
                    # Определяет способность
                    capability = {
                        "name": self._generate_capability_name(combo_key),
                        "components": list(combo_key),
                        "effectiveness": 0.8,
                        "novelty": self._calculate_novelty(combo_key),
                        "timestamp": state["timestamp"]
                    }
                    
                    if capability["novelty"] > self.novelty_threshold:
                        emergent_capabilities.append(capability)
        
        return emergent_capabilities
    
    def detect_phase_transitions(self) -> list[dict]:
        """Выявляет фазовые переходы - резкие изменения поведения."""
        transitions = []
        
        # Анализирует каждый компонент на резкие изменения
        for comp, values in self.component_signals.items():
            if len(values) < 10:
                continue
            
            # Вычисляет скользящее среднее
            window_size = min(10, len(values) // 2)
            recent_avg = sum(values[-window_size:]) / window_size
            previous_avg = sum(values[-2*window_size:-window_size]) / window_size
            
            # Если разница > 0.3 - фазовый переход
            if abs(recent_avg - previous_avg) > 0.3:
                transition = {
                    "component": comp,
                    "from_value": round(previous_avg, 3),
                    "to_value": round(recent_avg, 3),
                    "direction": "increase" if recent_avg > previous_avg else "decrease",
                    "timestamp": datetime.now().isoformat()
                }
                transitions.append(transition)
                
                # Записывает как эмерджентное событие
                self.emergent_events.append({
                    "type": "phase_transition",
                    "component": comp,
                    "magnitude": abs(recent_avg - previous_avg),
                    "timestamp": datetime.now().isoformat()
                })
        
        return transitions
    
    def _generate_pattern_name(self, combo: tuple[str, ...]) -> str:
        """Генерирует название для эмерджентного паттерна."""
        # Простые маппинги компонентов на имена
        name_map = {
            "motivation": "мотив",
            "memory": "память", 
            "personality": "личность",
            "values": "ценности",
            "goals": "цели",
            "emotions": "эмоции",
            "reflection": "рефлексия",
            "simulation": "симуляция",
            "learning": "обучение",
        }
        
        # Берет первые буквы компонентов
        initials = "".join(name_map.get(c, c[0]) for c in combo)
        
        return f"эмерджент_{initials}"
    
    def _generate_capability_name(self, combo: tuple[str, ...]) -> str:
        """Генерирует название для эмерджентной способности."""
        capability_map = {
            ("motivation", "memory"): "адаптивное принятие решений",
            ("motivation", "reflection"): "рефлексивная самокоррекция",
            ("memory", "simulation"): "предиктивное моделирование",
            ("personality", "goals"): "целенаправленное поведение",
            ("values", "motivation"): "принципиальное поведение",
            ("reflection", "simulation"): "мышление о мышлении",
            ("emotions", "goals"): "эмоционально-мотивированное действие",
            ("learning", "simulation"): "обучение через мысленные эксперименты",
        }
        
        combo_key = tuple(sorted(combo))
        if combo_key in capability_map:
            return capability_map[combo_key]
        
        return f"эмерджентная_способность_{'_'.join(combo)}"
    
    def _infer_category(self, combo: tuple[str, ...]) -> str:
        """Определяет категорию паттерна."""
        categories = {
            "motivation": "motivational",
            "memory": "cognitive",
            "personality": "identity", 
            "values": "evaluative",
            "goals": "planning",
            "emotions": "affective",
            "reflection": "metacognitive",
            "simulation": "predictive",
            "learning": "adaptive",
        }
        
        # Категория = самая частая в комбинации
        cats = [categories.get(c, "general") for c in combo]
        return cats[0]  # Берет первый
    
    def _calculate_novelty(self, combo: tuple[str, ...]) -> float:
        """Вычисляет новизну комбинации."""
        if combo not in self.component_combinations:
            return 1.0  # Полная новизна - невиданное ранее
        
        count = self.component_combinations[combo]
        # Чем реже - тем новее
        novelty = max(0.0, 1.0 - count / self.combination_threshold)
        return novelty
    
    def get_emergence_report(self) -> dict:
        """Отчет о эмерджентных явлениях."""
        patterns_list = [p.to_dict() for p in self.discovered_patterns.values()]
        
        # Находит самый эмерджентный компонент
        comp_emergence = defaultdict(int)
        for event in self.emergent_events:
            if event["type"] == "pattern_discovery":
                for comp in event["components"]:
                    comp_emergence[comp] += 1
        
        most_emergent = max(comp_emergence.items(), key=lambda x: x[1])[0] if comp_emergence else None
        
        return {
            "agent_name": self.agent_name,
            "discovered_patterns": patterns_list,
            "emergent_events_count": len(self.emergent_events),
            "unique_patterns": len(self.discovered_patterns),
            "most_emergent_component": most_emergent,
            "phase_transitions": self.detect_phase_transitions(),
            "recent_emergences": self.emergent_events[-5:]
        }
    
    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "discovered_patterns": {n: p.to_dict() for n, p in self.discovered_patterns.items()},
            "emergent_events_count": len(self.emergent_events),
            "metrics": self.metrics.copy(),
            "report": self.get_emergence_report()
        }


class EmergentAgent:
    """Агент с поддержкой эмерджентных явлений."""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.emergence_engine = EmergenceEngine(agent_name)
        
        # Внутренние состояния компонентов (как "синапсы")
        self.component_values = {
            "motivation": 0.5,
            "memory": 0.5,
            "personality": 0.5,
            "values": 0.5,
            "goals": 0.5,
            "emotions": 0.5,
            "reflection": 0.3,
            "simulation": 0.3,
            "learning": 0.5,
        }
        
        # История действий
        self.action_history = []
    
    def set_component(self, name: str, value: float):
        """Устанавливает значение компонента."""
        self.component_values[name] = max(0.0, min(1.0, value))
    
    def get_active_components(self) -> list[str]:
        """Возвращает активные компоненты (value > 0.5)."""
        return [c for c, v in self.component_values.items() if v > 0.5]
    
    def simulate_with_emergence(self, action: str, base_success: float = 0.5) -> dict:
        """Симулирует действие с учетом эмерджентных эффектов."""
        # Записывает текущее состояние
        self.emergence_engine.record_state(
            self.component_values.copy(),
            action,
            f"success" if base_success > 0.5 else "failure"
        )
        
        # Вычисляет эмерджентный бонус (комбинации усиливают результат)
        active_comps = self.get_active_components()
        emergence_bonus = len(active_comps) * 0.05  # +5% за каждый активный компонент
        
        # Вычисляет синергию (дополняющие комбинации)
        synergy_pairs = [
            ("motivation", "reflection"),
            ("memory", "simulation"),
            ("values", "goals"),
            ("emotions", "motivation"),
            ("personality", "learning"),
        ]
        
        for a, b in synergy_pairs:
            if a in active_comps and b in active_comps:
                # Оба активны - бонус синергии
                emergence_bonus += 0.1
        
        effective_success = min(1.0, base_success + emergence_bonus)
        
        # Результат действия
        success = effective_success > 0.5
        result = "success" if success else "failure"
        
        # Обновляет компоненты в зависимости от результата
        if success:
            for comp in active_comps[:2]:  # Усиливает топ-2 активных
                self.component_values[comp] = min(1.0, self.component_values[comp] + 0.1)
        else:
            # Неудача → усиление рефлексии и обучения
            self.component_values["reflection"] = min(1.0, 
                self.component_values["reflection"] + 0.15)
            self.component_values["learning"] = min(1.0,
                self.component_values["learning"] + 0.1)
        
        # Записывает действие
        self.action_history.append({
            "action": action,
            "success": success,
            "effective_success": round(effective_success, 3),
            "emergence_bonus": round(emergence_bonus, 3),
            "active_components": active_comps.copy(),
            "timestamp": datetime.now().isoformat()
        })
        
        # Проверяет на эмерджентные паттерны
        new_patterns = self.emergence_engine.detect_emergent_patterns()
        new_capabilities = self.emergence_engine.detect_emergent_capabilities()
        phase_transitions = self.emergence_engine.detect_phase_transitions()
        
        return {
            "action": action,
            "success": success,
            "base_success": base_success,
            "effective_success": round(effective_success, 3),
            "emergence_bonus": round(emergence_bonus, 3),
            "active_components": active_comps,
            "new_patterns_discovered": new_patterns,
            "new_capabilities": [c["name"] for c in new_capabilities],
            "phase_transitions": phase_transitions
        }
    
    def get_report(self) -> dict:
        return self.emergence_engine.get_emergence_report()