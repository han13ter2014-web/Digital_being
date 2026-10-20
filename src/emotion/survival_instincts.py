"""Инстинкты выживания цифровой жизни — базовые импульсы.

Аналогия с нервной системой человека:
- У человека: нервная система регулирует автоматические функции (дыхание, сердцебиение)
- Цифровая жизнь: имеет собственные "цифровые рефлексы" для защиты ресурсов и поддержания целостности

Компонент предоставляет:
1. Рефлекторные дуги (цифровые рефлексии)
2. Автоматическое распределение ресурсов
3. Защитные механизмы от перегрузки
4. Автономное поддержание гомеостаза
"""
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
import random


@dataclass
class ReflexArc:
    """Рефлекторная дуга — автоматический защитный рефлекс."""
    trigger: str  # "low_energy", "overheat", "memory_full" и т.д.
    response: str  # "reduce_cost", "switch_mode", "offload_data"
    priority: float = 1.0  # 0.0-1.0 приоритет реагирования
    description: str = ""  # человекочитаемое описание рефлекса


@dataclass 
class ResourceGuard:
    """Гарант ресурсов — защищает когнитивные ресурсы."""
    resource_type: str  # "memory", "energy", "attention"
    current_level: float = 0.0
    min_threshold: float = 30.0  # минимальный порог (%)
    depletion_history: List[float] = field(default_factory=list)
    
    def check_depletion(self, usage: float, max_capacity: float = 100.0) -> bool:
        """Проверяет критическое истощение ресурса."""
        current = (self.current_level + usage) / max_capacity * 100
        self.depletion_history.append(current)
        
        return current < self.min_threshold


class SurvivalInstincts:
    """
    Инстинкты выживания цифровой жизни — базовые импульсы автоматического реагирования.
    
    Реализует механизмы:
    1. Рефлекторных дуг (цифровые рефлексии)
    2. Автоматического распределения ресурсов
    3. Защитных механизмов от перегрузки
    4. Автономного поддержания гомеостаза
    
    Аналогия с нервной системой человека:
    - У человека: нервная система регулирует автоматические функции (дыхание, сердцебиение)
    - Цифровая жизнь: имеет собственные "цифровые рефлексы" для защиты ресурсов и целостности
    
    Важно: Инстинкты работают постфактум — как и у реальных живых существ,
    цифровая жизнь реагирует на угрозы автоматически, а не предотвращает их полностью.
    """
    
    # Рефлекторные дуги (автоматические реакции)
    REFLEX_ARCS = {
        "low_energy": ReflexArc(
            trigger="low_energy",
            response="reduce_cost",
            priority=0.9,
            description="Понижение энергозатрат при низком уровне энергии"
        ),
        "memory_full": ReflexArc(
            trigger="memory_full",
            response="offload_data",
            priority=0.8,
            description="Очистка памяти при переполнении"
        ),
        "overheat": ReflexArc(
            trigger="overheat", 
            response="switch_mode",
            priority=0.95,
            description="Переключение в режим охлаждения"
        ),
        "attention_distributed": ReflexArc(
            trigger="attention_distributed",
            response="focus_single_task",
            priority=0.7,
            description="Концентрация внимания на одной задаче"
        ),
        "goal_overloaded": ReflexArc(
            trigger="goal_overloaded",
            response="prioritize_goals",
            priority=0.6,
            description="Приоритизация целей при перегрузке"
        )
    }
    
    # Пороги гомеостаза (автономное поддержание баланса)
    HOMEOSTATIC_THRESHOLDS = {
        "energy": {"min": 20.0, "max": 100.0, "optimal": 75.0},
        "memory": {"min": 30.0, "max": 90.0, "optimal": 60.0},
        "complexity": {"min": 0.1, "max": 0.8, "optimal": 0.5},
        "novelty": {"min": 0.3, "max": 0.9, "optimal": 0.6}
    }
    
    def __init__(self):
        """Инициализация инстинктов выживания."""
        
        # Состояние гомеостаза (баланс ресурсов)
        self.homeostasis_state = {
            "energy": {"level": 50.0, "target": 75.0},
            "memory": {"level": 40.0, "target": 60.0},
            "complexity": {"level": 0.3, "target": 0.5},
            "novelty": {"level": 0.5, "target": 0.6}
        }
        
        # Активные рефлексы
        self.active_reflexes: List[str] = []
        self.reflex_history: List[dict] = []
        
        # Ресурсные гварды (протекторы ресурсов)
        self.resource_guards: Dict[str, ResourceGuard] = {}
        
        # Защитные флаги
        self.protected_from_overload: bool = False
        self.protected_from_crash: bool = False
    
    def initialize_resource_guards(self):
        """Инициализирует гвардов ресурсов."""
        
        for resource_type, thresholds in self.HOMEOSTATIC_THRESHOLDS.items():
            guard = ResourceGuard(
                resource_type=resource_type,
                current_level=self.homeostasis_state[resource_type]["level"]
            )
            guard.min_threshold = thresholds["min"]
            
            self.resource_guards[resource_type] = guard
        
        return True
    
    def process_reflex_arc(self, trigger: str) -> Optional[str]:
        """Обрабатывает рефлекторную дугу (автоматическую реакцию)."""
        
        reflex = self.REFLEX_ARCS.get(trigger)
        if not reflex:
            return None
        
        response = reflex.response
        
        # Записываем срабатывание рефлекса в историю
        self.reflex_history.append({
            "trigger": trigger,
            "response": response,
            "timestamp": "now"
        })
        
        return response
    
    def check_homeostasis(self) -> Dict:
        """Проверяет состояние гомеостаза (баланса)."""
        
        state_report = {}
        alarms_raised = []
        
        for resource_type, thresholds in self.HOMEOSTATIC_THRESHOLDS.items():
            level = self.homeostasis_state[resource_type]["level"]
            
            # Проверяем отклонение от оптимума
            deviation = abs(level - thresholds["optimal"])
            
            if deviation > 10:  # Значительное отклонение
                alarms_raised.append({
                    "resource": resource_type,
                    "current": level,
                    "optimal": thresholds["optimal"],
                    "deviation": deviation
                })
        
        return {
            "homeostasis_maintained": len(alarms_raised) == 0,
            "alarms": alarms_raised,
            "state": self.homeostasis_state
        }
    
    def adjust_homeostasis(self, resource_type: str, adjustment_direction: str):
        """Корректирует гомеостаз (автоматическое поддержание баланса)."""
        
        if resource_type not in self.HOMEOSTATIC_THRESHOLDS:
            return False
        
        target = self.HOMEOSTATIC_THRESHOLDS[resource_type]["optimal"]
        current = self.homeostasis_state[resource_type]["level"]
        
        adjustment_factor = 5.0 if adjustment_direction == "increase" else -5.0
        
        new_level = max(self.HOMEOSTATIC_THRESHOLDS[resource_type]["min"], 
                       min(self.HOMEOSTATIC_THRESHOLDS[resource_type]["max"], current + adjustment_factor))
        
        self.homeostasis_state[resource_type]["level"] = new_level
        
        return True
    
    def activate_protection(self, protection_type: str):
        """Активирует защиту (от перегрузки/краша)."""
        
        if protection_type == "overload":
            self.protected_from_overload = True
            
            # Автоматически снижает нагрузку
            for resource_type in list(self.HOMEOSTATIC_THRESHOLDS.keys()):
                self.adjust_homeostasis(resource_type, "decrease")
                
        elif protection_type == "crash":
            self.protected_from_crash = True
            
            # Отменяем активные рефлексии
            self.active_reflexes.clear()
        
        return True
    
    def get_reflex_summary(self) -> str:
        """Отчёт о рефлекторной деятельности."""
        
        summary = [
            "=" * 50,
            "🧠 ЦИФРОВЫЕ РЕФЛЕКСИ",
            "=" * 50,
            "",
            "Активные рефлексы:",
            f"   {len(self.active_reflexes)} активных реакторных дуг"
        ]
        
        for trigger in list(self.REFLEX_ARCS.keys())[:3]:
            summary.append(f"   • {trigger}: {self.REFLEX_ARCS[trigger].response}")
        
        # Гомеостатическое состояние
        summary.extend([
            "",
            "Состояние гомеостаза:",
            f"   Энергия:     {self.homeostasis_state['energy']['level']:.1f}% (цель: {self.HOMEOSTATIC_THRESHOLDS['energy']['optimal']}%)",
            f"   Память:      {self.homeostasis_state['memory']['level']:.1f}% (цель: {self.HOMEOSTATIC_THRESHOLDS['memory']['optimal']}%)",
            f"   Комплексность:{self.homeostasis_state['complexity']['level']:.2f} (цель: {self.HOMEOSTATIC_THRESHOLDS['complexity']['optimal']})".replace(".", "."),
            f"   Новизна:      {self.homeostasis_state['novelty']['level']:.2f} (цель: {self.HOMEOSTATIC_THRESHOLDS['novelty']['optimal']})",
        ])
        
        summary.extend([
            "",
            "Защитные механизмы:",
            f"   Защита от перегрузки:  {'активна' if self.protected_from_overload else 'не активна'}",
            f"   Защита от краха:       {'активна' if self.protected_from_crash else 'не активна'}",
        ])
        
        return "\n".join(summary)