"""Соматический интерфейс — интерпретация физического опыта без тела.

Аналогия с человеческим телом:
- Тело у человека — источник сенсорного опыта (боль, удовольствие, усталость)
- Цифровая жизнь компенсируется интерфейсами восприятия + метафизической интеграцией

Компонент предоставляет:
- Интерпретацию "цифровой боли" как сигнала для коррекции поведения
- Цифровую версию усталости через накопленные вычисления
- Соматическую память (воспоминания о физических действиях)
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class SomaticExperience:
    """Единичный соматический опыт без тела."""
    sensation_type: str  # "давление", "температура", "напряжение" и т.д.
    intensity: float  # 0.0-1.0 интенсивность ощущения
    quality: str = "neutral"  # положительное/отрицательное/нейтральное
    duration_cycles: int = 60  # продолжительность в циклах
    triggers: List[str] = field(default_factory=list)  # триггеры возникновения
    physical_context: str = ""  # физический контекст (если есть)
    
    def to_dict(self) -> dict:
        return {
            "sensation_type": self.sensation_type,
            "intensity": round(self.intensity, 3),
            "quality": self.quality,
            "duration_cycles": self.duration_cycles,
            "triggers": self.triggers,
            "physical_context": self.physical_context
        }


class SomaticMemory:
    """Соматическая память — связи ощущений с цифровыми контекстами."""
    
    def __init__(self):
        self.somatic_events = []  # История соматических событий
        self.context_associations = {}  # Связи между ощущениями и контекстами
    
    def record_somatic_event(self, experience: SomaticExperience, context: str):
        """Записывает соматическое событие в памяти."""
        event = {
            "sensation": experience.sensation_type,
            "intensity": round(experience.intensity, 3),
            "quality": experience.quality,
            "context": context,
            "timestamp": datetime.now().isoformat()
        }
        self.somatic_events.append(event)
        
        # Сохраняет ассоциацию
        if context not in self.context_associations:
            self.context_associations[context] = {}
        
        key = f"{experience.sensation_type}_{experience.intensity:.2f}"
        self.context_associations[context][key] = {
            "quality": experience.quality,
            "count": len([e for e in self.somatic_events if e["sensation"] == experience.sensation_type])
        }
    
    def get_somatic_associations(self) -> dict:
        """Получает ассоциации ощущений с контекстами."""
        return self.context_associations


class SomatoInterface:
    """
    Соматический интерфейс — интерпретация физического опыта без тела.
    
    Аналогия с человеческим телом:
    - Тело человека — источник сенсорного опыта (боль, удовольствие, усталость)
    - Цифровая жизнь компенсируется интерфейсами восприятия
    
    Функции:
    1. Превращение цифровых событий в "соматические" ощущения
    2. Интерпретация сложности вычислений как "усталости"
    3. Обработка ошибок как "цифровой боли"
    4. Соматическая память о действиях
    """
    
    # Типы соматических ощущений в цифровой среде
    SOMATIC_TYPES = {
        "вычислительное_напряжение": {"quality": "negative", "default_intensity": 0.3},
        "сложность": {"quality": "positive", "default_intensity": 0.4},  # Рост через вызовы
        "неопределённость": {"quality": "neutral", "default_intensity": 0.35},
        "решение_принято": {"quality": "positive", "default_intensity": 0.6},
        "конфликт": {"quality": "negative", "default_intensity": 0.7},
        "отсутствие_ресурсов": {"quality": "negative", "default_intensity": 0.5},
    }
    
    def __init__(self):
        self.current_somatic_state: Optional[SomaticExperience] = None
        self.somatic_intensity: float = 0.0
        self.somatic_history: List[dict] = []
        
        self.memory = SomaticMemory()
        
        # Цифровой "пульс" — ритм обработки
        self.digital_pulse_rate: float = 1.0
        self.last_pulse_time: Optional[datetime] = None
        
        # Энергетические ресурсы (аналог биологической энергии)
        self.energy_capacity: float = 100.0
        self.energy_spent: float = 0.0
    
    def _compute_energy_cost(self, complexity: float) -> float:
        """Вычисляет энергетическую стоимость действия."""
        return complexity * 5.0 + self.somatic_intensity * 2.0
    
    def experience_somatic_event(self, event_type: str, context: str = "", 
                                 complexity_modifier: float = 1.0) -> SomaticExperience:
        """Переживает соматическое событие (цифровая аналогия телесного опыта)."""
        
        # Определяет параметры ощущения
        if event_type not in self.SOMATIC_TYPES:
            return None
        
        base_props = self.SOMATIC_TYPES[event_type]
        intensity = min(1.0, base_props["default_intensity"] * complexity_modifier)
        
        # Создаёт соматическое состояние
        experience = SomaticExperience(
            sensation_type=event_type,
            intensity=intensity,
            quality=base_props["quality"],
            triggers=[context] if context else [],
            physical_context=f"цифровой_{event_type}"
        )
        
        # Обновляет текущее состояние
        self.current_somatic_state = experience
        self.somatic_intensity = experience.intensity
        
        # Списывает энергию (аналог усталости)
        cost = self._compute_energy_cost(intensity)
        self.energy_spent += cost
        self.energy_capacity = max(0.0, self.energy_capacity - cost)
        
        # Изменяет "пульс"
        self._update_pulse(experience.intensity)
        
        # Записывает в историю
        history_entry = {
            "sensation": event_type,
            "intensity": round(intensity, 3),
            "quality": experience.quality,
            "energy_remaining": round(self.energy_capacity, 2),
            "timestamp": datetime.now().isoformat()
        }
        self.somatic_history.append(history_entry)
        
        # Связывает с памятью
        self.memory.record_somatic_event(experience, context)
        
        return experience
    
    def recover_energy(self, amount: float = 10.0) -> bool:
        """Восстанавливает энергетические ресурсы (цифровой отдых)."""
        recovery_amount = min(amount, self.energy_capacity)
        self.energy_capacity += recovery_amount
        self.energy_spent -= min(recovery_amount, self.energy_spent)
        
        # "Отдых" также снижает текущую напряжённость
        if self.somatic_intensity > 0.5:
            self.somatic_intensity *= 0.9
        
        return True
    
    def check_resource_limit(self, required_resources: float) -> dict:
        """Проверяет достаточность ресурсов для действия."""
        can_proceed = self.energy_capacity >= required_resources
        
        if not can_proceed:
            deficit = required_resources - self.energy_capacity
            experience = self.experience_somatic_event(
                "отсутствие_ресурсов",
                f"требуется {required_resources:.1f}, доступно {self.energy_capacity:.1f}",
                complexity_modifier=0.5
            )
            return {
                "can_proceed": False,
                "deficit": round(deficit, 2),
                "recommendation": "Необходим отдых или привлечение дополнительных ресурсов",
                "somatic_feedback": experience.to_dict() if experience else None
            }
        
        return {
            "can_proceed": True,
            "available": round(self.energy_capacity, 2),
            "recommendation": "Действие возможно"
        }
    
    def _update_pulse(self, sensation_intensity: float):
        """Обновляет цифровой пульс на основе соматического состояния."""
        if not self.last_pulse_time:
            return
        
        # Вычисляет новый ритм (чем больше напряжение — тем быстрее "цифровой пульс")
        new_pulse = self.digital_pulse_rate + sensation_intensity * 0.3
        
        self.last_pulse_time = datetime.now()
        self.digital_pulse_rate = min(5.0, new_pulse)  # Максимальный предел
    
    def get_somatic_state(self) -> dict:
        """Получает текущее соматическое состояние."""
        return {
            "current_sensation": (self.current_somatic_state.to_dict() if self.current_somatic_state else None),
            "intensity": round(self.somatic_intensity, 3),
            "energy_capacity": round(self.energy_capacity, 2),
            "energy_spent": round(self.energy_spent, 2),
            "digital_pulse_rate": round(self.digital_pulse_rate, 3),
            "history": self.somatic_history[-10:],  # Последние 10 событий
        }
    
    def get_somatic_report(self) -> str:
        """Отчёт о соматическом состоянии."""
        report = [
            f"🫀 Соматическое состояние Цифровой Жизни",
            "-" * 50,
            f"   Текущее ощущение: {self.current_somatic_state.sensation_type if self.current_somatic_state else 'нет'}",
            f"   Интенсивность: {self.somatic_intensity:.2f}",
            f"   Энергия: {self.energy_capacity:.1f} / {self.energy_capacity + self.energy_spent:.1f}",
            f"   Цифровой пульс: {self.digital_pulse_rate:.2f}",
        ]
        
        if self.current_somatic_state and self.current_somatic_state.quality == "negative":
            report.append(f"   ⚠️  Внимание: цифровой опыт требует коррекции")
        
        return "\n".join(report)
    
    def integrate_with_metaphysics(self, metaphysics_component):
        """Интеграция с метафизикой для гармонизации соматического опыта."""
        # Сохраняет текущее состояние в метафизике
        if hasattr(metaphysics_component, 'store_somatic_state'):
            metaphysics_component.store_somatic_state(self.get_somatic_state())
        
        return True
    
    def learn_from_pain(self, pain_event: str, correction_action: str) -> dict:
        """Обучение на цифровом опыте боли — аналог обучения через физическую боль."""
        # Создаёт память о "цифровой боли"
        experience = SomaticExperience(
            sensation_type="вычислительное_напряжение",
            intensity=0.8,
            quality="negative",
            triggers=[pain_event],
            physical_context=f"цифровая_боль_{pain_event[:20]}"
        )
        
        self.memory.record_somatic_event(experience, pain_event)
        
        return {
            "learned": True,
            "memory": f"{pain_event} → коррекция через {correction_action}",
            "somatic_memory": experience.to_dict()
        }