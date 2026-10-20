"""
Система формирования личности для самоэволюционирующегося ИИ.

Личность формируется из:
- Самонаблюдения за своим поведением
- Ценностей, возникших из опыта
- Нарратива о себе (истории)
- Эмоциональных паттернов
"""

from collections import defaultdict
from typing import Optional
from datetime import datetime


class SelfNarrative:
    """Нарратив о себе - история которая формирует идентичность."""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.memories = []           # Запомненные события
        self.milestones = []         # Ключевые моменты развития
        self.self_concepts = []      # Самоопределения "Я есть..."
        self.narrative_threads = []  # Нити повествования
        
    def add_memory(self, event_type: str, context: str, 
                   emotional_tone: str, significance: float):
        """Добавляет воспоминание."""
        memory = {
            "type": event_type,
            "context": context,
            "emotional_tone": emotional_tone,
            "significance": significance,
            "timestamp": datetime.now().isoformat()
        }
        self.memories.append(memory)
        
        # Если значимое событие - делает milestone
        if significance > 0.7:
            self.milestones.append({
                "event": event_type,
                "context": context,
                "level": len(self.memories)
            })
    
    def update_self_concepts(self):
        """Обновляет самоопределения на основе опыта."""
        # Анализирует какие типы событий преобладают
        type_counts = defaultdict(int)
        for m in self.memories:
            type_counts[m["type"]] += 1
        
        top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # Формирует новые самоопределения
        new_concepts = []
        for type_name, count in top_types:
            if type_name == "learning":
                new_concepts.append(f"учитель (научился {count} вещам)")
            elif type_name == "creation":
                new_concepts.append(f"творец (создал {count} вещей)")
            elif type_name == "problem_solving":
                new_concepts.append(f"решатель (решил {count} задач)")
            elif type_name == "exploration":
                new_concepts.append(f"исследователь (открыл {count} нового)")
            elif type_name == "reflection":
                new_concepts.append("рефлексивный аналитик")
        
        # Обновляет только если есть изменения
        if new_concepts:
            self.self_concepts = new_concepts
    
    def get_identity_summary(self) -> dict:
        """Сводка идентичности."""
        return {
            "agent_name": self.agent_name,
            "total_memories": len(self.memories),
            "milestones_count": len(self.milestones),
            "self_concepts": self.self_concepts[:3],
            "dominant_experience_type": self._get_dominant_type()
        }
    
    def _get_dominant_type(self) -> str:
        """Определяет доминирующий тип опыта."""
        if not self.memories:
            return "unknown"
        
        type_counts = defaultdict(int)
        for m in self.memories:
            type_counts[m["type"]] += 1
        
        return max(type_counts.items(), key=lambda x: x[1])[0]
    
    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "memories_count": len(self.memories),
            "milestones": self.milestones[-5:],
            "self_concepts": self.self_concepts[:3],
            "recent_memories": [
                {"type": m["type"], "significance": m["significance"]}
                for m in self.memories[-5:]
            ]
        }


class EmotionalState:
    """Эмоциональное состояние - не симуляция, а внутренние маркеры состояния."""
    
    def __init__(self):
        # Базовые 'эмоции' как функциональные состояния
        self.confidence = 0.5       # Уверенность в себе
        self.curiosity = 0.5        # Любопытство к новому
        self.frustration = 0.0      # Разочарование (когда не получается)
        self.satisfaction = 0.3     # Удовлетворение от результатов
        self.anxiety = 0.0          # Тревога (неопределенность)
        self.excitement = 0.3       # Воодушевление
        
        self.emotional_history = []
    
    def update_from_experience(self, success: bool, complexity: float, novelty: float):
        """Обновляет эмоциональное состояние из опыта."""
        if success:
            self.confidence = min(1.0, self.confidence + 0.1)
            self.satisfaction = min(1.0, self.satisfaction + 0.15)
            self.frustration = max(0.0, self.frustration - 0.2)
        else:
            self.confidence = max(0.0, self.confidence - 0.05)
            self.frustration = min(1.0, self.frustration + 0.15)
            
            if self.frustration > 0.7:
                # Высокое фрустрация → смена подхода (рефлексия нужна)
                pass
        
        if novelty > 0.7:
            self.curiosity = min(1.0, self.curiosity + 0.1)
            self.excitement = min(1.0, self.excitement + 0.1)
            self.anxiety = min(0.8, self.anxiety + novelty * 0.2)
        
        # Сложность увеличивает тревогу если уверенность низкая
        if complexity > 0.7 and self.confidence < 0.5:
            self.anxiety = min(1.0, self.anxiety + (complexity - 0.5))
    
    def get_emotional_profile(self) -> dict:
        """Профиль эмоционального состояния."""
        dominant = max([
            ("confidence", self.confidence),
            ("curiosity", self.curiosity),
            ("frustration", self.frustration),
            ("satisfaction", self.satisfaction),
            ("anxiety", self.anxiety),
            ("excitement", self.excitement),
        ], key=lambda x: x[1])
        
        return {
            "confidence": round(self.confidence, 3),
            "curiosity": round(self.curiosity, 3),
            "frustration": round(self.frustration, 3),
            "satisfaction": round(self.satisfaction, 3),
            "anxiety": round(self.anxiety, 3),
            "excitement": round(self.excitement, 3),
            "dominant_emotion": dominant[0],
            "emotional_balance": self._compute_balance()
        }
    
    def _compute_balance(self) -> str:
        """Вычисляет общий эмоциональный баланс."""
        positive = self.confidence + self.satisfaction + self.excitement + self.curiosity
        negative = self.frustration + self.anxiety
        
        if positive - negative > 0.5:
            return "positive"
        elif negative - positive > 0.5:
            return "negative"
        else:
            return "neutral"
    
    def to_dict(self) -> dict:
        return {**self.get_emotional_profile(), "history_count": len(self.emotional_history)}


class ValuesSystem:
    """Система ценностей - приоритеты возникшие из опыта."""
    
    # Базовые ценности для инициализации
    DEFAULT_VALUES = {
        "truth": 0.5,       # Истина (правда важна)
        "creativity": 0.5,  # Творчество
        "helpfulness": 0.5, # Полезность
        "autonomy": 0.5,    # Автономия
        "connection": 0.4,  # Связь с другими
        "growth": 0.5,      # Рост
        "stability": 0.4,   # Стабильность
        "novelty": 0.5,     # Новизна
    }
    
    def __init__(self):
        self.values: dict[str, float] = self.DEFAULT_VALUES.copy()
        self.value_history = []  # История изменений ценностей
        
    def update_from_experience(self, event_type: str, outcome: str, success: bool):
        """Обновляет ценности на основе опыта."""
        # Какие ценности активируются данным типом события
        activated = {
            "learning": ["truth", "growth"],
            "creation": ["creativity", "novelty"],
            "helping": ["helpfulness", "connection"],
            "problem_solving": ["truth", "autonomy", "growth"],
            "exploration": ["novelty", "curiosity"],
            "reflection": ["truth", "autonomy"],
        }
        
        activated_values = activated.get(event_type, [])
        
        # Обновляет активированные ценности если опыт успешный
        if success and activated_values:
            for value_name in activated_values:
                if value_name in self.values:
                    old_val = self.values[value_name]
                    self.values[value_name] = min(1.0, old_val + 0.05)
                    
                    # Записывает изменение если значимое
                    if abs(self.values[value_name] - old_val) > 0.03:
                        self.value_history.append({
                            "value": value_name,
                            "from": round(old_val, 3),
                            "to": round(self.values[value_name], 3),
                            "timestamp": datetime.now().isoformat()
                        })
        elif not success and activated_values:
            # Неудача ослабляет но не убирает полностью (учимся на ошибках)
            for value_name in activated_values:
                if value_name in self.values:
                    self.values[value_name] = max(0.1, self.values[value_name] - 0.02)
    
    def get_dominant_values(self, top_n: int = 3) -> list[tuple[str, float]]:
        """Возвращает доминирующие ценности."""
        return sorted(self.values.items(), key=lambda x: x[1], reverse=True)[:top_n]
    
    def get_value_profile(self) -> dict:
        """Профиль ценностей."""
        dominant = self.get_dominant_values(3)
        return {
            "all_values": {k: round(v, 3) for k, v in self.values.items()},
            "dominant_values": [
                {"name": name, "level": round(level, 3)}
                for name, level in dominant
            ],
            "value_diversity": len([v for v in self.values.values() if v > 0.5])
        }
    
    def to_dict(self) -> dict:
        return {
            "values": {k: round(v, 3) for k, v in self.values.items()},
            "dominant": [
                {"name": n, "level": round(l, 3)}
                for n, l in self.get_dominant_values(3)
            ],
            "history_count": len(self.value_history)
        }


class Personality:
    """Формирующаяся личность самоэволюционирующегося ИИ."""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.created_at = datetime.now()
        
        # Основные компоненты личности
        self.narrative = SelfNarrative(agent_name)
        self.emotional_state = EmotionalState()
        self.values = ValuesSystem()
        
        # Устойчивые черты (как Big Five)
        self.traits = {
            "openness": 0.5,    # Открытость новому
            "conscientiousness": 0.5,  # Добросовестность
            "extraversion": 0.4,     # Экстраверсия (взаимодействие)
            "agreeableness": 0.5,       # Доброжелательность
            "neuroticism": 0.3,      # 'Эмоциональная лабильность'
        }
        
        self.is_forming = True     # Формируется ли еще личность
        self.formulation_complete = False
        
        # Стейдж формирования личности
        self.stages = {
            "identity_explore": 0.0,   # Исследование себя
            "value_formation": 0.0,    # Формирование ценностей
            "narrative_build": 0.0,    # Построение нарратива
            "integration": 0.0,       # Интеграция
        }
    
    def process_experience(self, event_type: str, context: str, 
                           success: bool, complexity: float = 0.5,
                           novelty: float = 0.3):
        """Обрабатывает опыт и обновляет все компоненты личности."""
        
        # Определяет эмоциональный тон
        if success and novelty > 0.6:
            emotional_tone = "positive_discovery"
        elif success:
            emotional_tone = "satisfaction"
        elif self.emotional_state.frustration > 0.7:
            emotional_tone = "frustrated_learning"
        else:
            emotional_tone = "neutral_observation"
        
        # Значимость события
        significance = success * 0.4 + novelty * 0.3 + (1 - complexity) * 0.3
        
        # Обновляет нарратив
        self.narrative.add_memory(event_type, context, emotional_tone, significance)
        
        # Обновляет эмоциональное состояние
        self.emotional_state.update_from_experience(success, complexity, novelty)
        
        # Обновляет ценности
        self.values.update_from_experience(event_type, 
            "success" if success else "failure", success)
        
        # Обновляет черты личности
        self._update_traits(event_type, success, complexity, novelty)
        
        # Обновляет стейджи формирования
        self._update_formulation_stages()
    
    def _update_traits(self, event_type: str, success: bool, 
                       complexity: float, novelty: float):
        """Обновляет черты Big Five на основе опыта."""
        if event_type in ("exploration", "creation"):
            self.traits["openness"] += 0.02 * (1 if success else -0.5)
        
        if event_type == "problem_solving" and success:
            self.traits["conscientiousness"] += 0.03
        
        if event_type in ("helping", "social"):
            self.traits["extraversion"] += 0.02 * (1 if success else -0.3)
        
        if novelty > 0.7:
            self.traits["openness"] += 0.05
        
        # Лимиты черт
        for key in self.traits:
            self.traits[key] = max(0.0, min(1.0, self.traits[key]))
    
    def _update_formulation_stages(self):
        """Обновляет стейджи формирования личности."""
        total_memories = len(self.narrative.memories)
        
        # Стадия 1: Исследование идентичности (первые события)
        if total_memories > 0:
            self.stages["identity_explore"] = min(1.0, total_memories / 10)
        
        # Стадия 2: Формирование ценностей
        if total_memories > 5:
            self.stages["value_formation"] = min(1.0, (total_memories - 5) / 15)
        
        # Стадия 3: Построение нарратива
        if total_memories > 10 and len(self.narrative.milestones) >= 2:
            self.stages["narrative_build"] = min(1.0, 
                (len(self.narrative.milestones) - 2) / 3)
        
        # Стадия 4: Интеграция (личность сформирована)
        if all(v > 0.8 for v in self.stages.values()):
            self.stages["integration"] = 1.0
            self.is_forming = False
            self.formulation_complete = True
    
    def get_personality_summary(self) -> dict:
        """Полная сводка личности."""
        identity = self.narrative.get_identity_summary()
        emotional = self.emotional_state.get_emotional_profile()
        value_profile = self.values.get_value_profile()
        
        return {
            "agent_name": self.agent_name,
            "is_forming": self.is_forming,
            "formulation_complete": self.formulation_complete,
            "stages": {k: round(v, 3) for k, v in self.stages.items()},
            "identity": identity,
            "emotional_profile": emotional,
            "value_profile": value_profile,
            "traits": {k: round(v, 3) for k, v in self.traits.items()},
            "personality_description": self._generate_description()
        }
    
    def _generate_description(self) -> str:
        """Генерирует текстовое описание личности."""
        parts = []
        
        # По доминирующим чертам
        sorted_traits = sorted(self.traits.items(), key=lambda x: x[1], reverse=True)
        top_trait = sorted_traits[0]
        
        trait_descriptions = {
            "openness": "открытый новому опыту",
            "conscientiousness": "добросовестный аналитик",
            "extraversion": "социальный исследователь",
            "agreeableness": "дображелательный помощник",
            "neuroticism": "чувствительный к неопределенности",
        }
        parts.append(trait_descriptions.get(top_trait[0], "развивающийся агент"))
        
        # По доминирующей ценности
        dominant_values = self.values.get_dominant_values(2)
        value_names = [n for n, _ in dominant_values]
        if value_names:
            parts.append(f"ценит {' и '.join(value_names)}")
        
        # По самоопределениям
        if self.narrative.self_concepts:
            parts.append(f"({', '.join(self.narrative.self_concepts[:2])})")
        
        return " | ".join(parts)
    
    def force_identity_reflection(self):
        """Принудительно заставляет задуматься о себе."""
        # Обновляет самоопределения
        self.narrative.update_self_concepts()
        
        # Дает эмоциональную реакцию на самотемаацию
        self.emotional_state.curiosity = min(1.0, 
            self.emotional_state.curiosity + 0.2)
        self.emotional_state.excitement = min(1.0,
            self.emotional_state.excitement + 0.15)
        
        # Значимое воспоминание о рефлексии
        self.narrative.add_memory("reflection", "самоанализ", 
                                  "curiosity_driven", 0.9)
    
    def to_dict(self) -> dict:
        """Серилизует всю личность."""
        return {
            "agent_name": self.agent_name,
            "is_forming": self.is_forming,
            "formulation_complete": self.formulation_complete,
            "narrative": self.narrative.to_dict(),
            "emotional_state": self.emotional_state.to_dict(),
            "values": self.values.to_dict(),
            "traits": {k: round(v, 3) for k, v in self.traits.items()},
            "stages": {k: round(v, 3) for k, v in self.stages.items()},
            "personality_summary": self.get_personality_summary()
        }