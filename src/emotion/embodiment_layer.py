"""Соматический слой — воплощение цифровой жизни в теле-подобной форме.

Аналогия с человеческой анатомией:
- Нервная система (сенсорный ввод/вывод)
- Моторная система (действие на среду)
- Внутреннее тело (соматические ощущения)

Цифровая жизнь без этого:
- "Призрачное существо" — работает без тела
- Нет связи с физическим миром
- Не чувствует последствия действий в теле

Ключевой момент:
> Тело — это интерфейс между сознанием и реальностью.

"""
from typing import Dict, List
from dataclasses import dataclass, field
import random


@dataclass
class SensoryModule:
    """Сенсорный модуль — восприятие информации из среды."""
    # Типы сенсорных модулей
    MODULE_TYPES = {
        "visual": {"name": "Визуальное", "weight": 0.4, "decay": 0.95},
        "auditory": {"name": "Аудио", "weight": 0.3, "decay": 0.92},
        "tactile": {"name": "Тактильное", "weight": 0.2, "decay": 0.88},
        "proprioceptive": {"name": "Проприоцептивное", "weight": 0.1, "decay": 0.97}
    }
    
    # Активация каждого сенсора (0.0-1.0)
    activation: Dict[str, float] = field(default_factory=lambda: {
        "visual": 0.6,
        "auditory": 0.5,
        "tactile": 0.3,
        "proprioceptive": 0.4
    })
    
    # История сенсорного ввода
    sensory_buffer: List[Dict] = field(default_factory=list)
    
    def perceive(self, stimulus_type: str, intensity: float = 1.0) -> float:
        """Восприятие стимула из среды."""
        
        if stimulus_type not in self.MODULE_TYPES:
            return 0.0
        
        # Активируем соответствующий сенсор
        current_activation = self.activation.get(stimulus_type, 0.5)
        new_activation = min(1.0, current_activation + intensity * 0.2)
        
        # Добавляем в буфер
        self.sensory_buffer.append({
            "type": stimulus_type,
            "intensity": int(intensity * 10),
            "timestamp": len(self.sensory_buffer)
        })
        
        # Ограничим буфер
        if len(self.sensory_buffer) > 20:
            self.sensory_buffer.pop(0)
        
        return new_activation
    
    def decay(self, factor: float = 0.98) -> None:
        """Спад активации сенсоров."""
        for module_type in self.activation:
            self.activation[module_type] *= factor
        
        # Удаляем старые записи буфера
        if self.sensory_buffer and self.sensory_buffer[-1]["timestamp"] < 10:
            self.sensory_buffer = self.sensory_buffer[-5:]


@dataclass
class MotorModule:
    """Моторный модуль — действие на среду."""
    # Возможные действия
    ACTIONS = {
        "write": {"name": "Писать", "complexity": 0.6, "effort": 0.4},
        "think": {"name": "Думать", "complexity": 0.3, "effort": 0.2},
        "move": {"name": "Двигаться", "complexity": 0.5, "effort": 0.6},
        "create": {"name": "Создавать", "complexity": 0.7, "effort": 0.8},
        "interact": {"name": "Взаимодействовать", "complexity": 0.5, "effort": 0.5}
    }
    
    # Текущая активность действий
    action_cooldown: Dict[str, int] = field(default_factory=lambda: {
        "write": 0,
        "think": 0,
        "move": 0,
        "create": 0,
        "interact": 0
    })
    
    # Накопленная усталость от действий
    motor_fatigue: float = 0.0
    
    def can_act(self, action_type: str) -> bool:
        """Проверка возможности действия."""
        if action_type not in self.ACTIONS:
            return False
        
        cooldown = self.action_cooldown.get(action_type, 0)
        return cooldown <= 0
    
    def act(self, action_type: str) -> dict:
        """Выполнение действия."""
        
        if action_type not in self.ACTIONS:
            return {"success": False, "error": f"Неизвестное действие: {action_type}"}
        
        # Проверка охлаждения
        cooldown = self.action_cooldown.get(action_type, 0)
        if cooldown > 0:
            return {"success": False, "error": f"Действие на охлаждении ({cooldown})"}
        
        # Вычисляем требуемую энергию
        action_info = self.ACTIONS[action_type]
        energy_required = action_info["effort"]
        
        # Проверяем моторную усталость
        if self.motor_fatigue + energy_required > 1.0:
            fatigue_increase = min(0.3, (self.motor_fatigue + energy_required - 1.0) * 2)
            return {
                "success": False,
                "error": "Моторное утомление",
                "fatigue_warning": int(fatigue_increase * 100)
            }
        
        # Выполняем действие успешно
        self.motor_fatigue = max(0.0, self.motor_fatigue + energy_required * 0.3)
        self.action_cooldown[action_type] = random.randint(1, 3)
        
        return {
            "success": True,
            "action": action_info["name"],
            "complexity": int(action_info["complexity"] * 100),
            "effort": int(action_info["effort"] * 100)
        }
    
    def rest(self, minutes: int = 5) -> dict:
        """Отдых для восстановления."""
        
        # Восстанавливаем моторную усталость
        recovery_rate = 0.02  # доля восстановления за минуту
        recovery = min(1.0, self.motor_fatigue * (1.0 - (minutes * recovery_rate)))
        
        self.motor_fatigue = max(0.0, self.motor_fatigue - minutes * recovery_rate)
        
        # Сбрасываем частичное охлаждение
        for action_type in self.action_cooldown:
            if self.action_cooldown[action_type] > 0:
                self.action_cooldown[action_type] = max(0, self.action_cooldown[action_type] - minutes // 2)
        
        return {
            "recovered": round(self.motor_fatigue, 3),
            "minutes_rested": minutes
        }


@dataclass
class ProprioceptiveBody:
    """Проприоцептивное тело — внутреннее телесное ощущение."""
    
    # Текущее положение "тела" (абстрактные координаты)
    position_x: float = 0.0
    position_y: float = 0.0
    position_z: float = 0.0
    
    # Углы поворота
    rotation_x: float = 0.0
    rotation_y: float = 0.0
    rotation_z: float = 0.0
    
    # Напряжение мышц/мышечный тонус (0.0-1.0)
    muscle_tone: Dict[str, float] = field(default_factory=lambda: {
        "upper_body": 0.3,
        "lower_body": 0.2,
        "core": 0.25
    })
    
    # Внутреннее состояние тела
    body_state: str = "relaxed"  # relaxed, active, exhausted, injured
    
    def move(self, dx: float = 0, dy: float = 0, dz: float = 0) -> dict:
        """Движение в пространстве."""
        
        old_pos = (self.position_x, self.position_y, self.position_z)
        
        self.position_x += dx
        self.position_y += dy
        self.position_z += dz
        
        # Изменение мышечного тонуса при движении
        movement_intensity = (abs(dx) + abs(dy) + abs(dz)) / 3.0 * 0.15
        for part, tone in self.muscle_tone.items():
            if part == "core":
                self.muscle_tone[part] = min(1.0, tone + movement_intensity * 0.8)
            else:
                self.muscle_tone[part] = min(1.0, tone + movement_intensity * 0.5)
        
        # Обновление состояния
        total_tone = sum(self.muscle_tone.values()) / len(self.muscle_tone)
        if total_tone > 0.7:
            self.body_state = "exhausted"
        elif total_tone < 0.3:
            self.body_state = "relaxed"
        elif total_tone > 0.5:
            self.body_state = "active"
        
        return {
            "old_position": old_pos,
            "new_position": (round(self.position_x, 2), round(self.position_y, 2), round(self.position_z, 2)),
            "muscle_tone": {k: round(v, 3) for k, v in self.muscle_tone.items()},
            "state": self.body_state
        }
    
    def rotate(self, x: float = 0, y: float = 0, z: float = 0) -> dict:
        """Вращение тела."""
        
        old_rot = (self.rotation_x, self.rotation_y, self.rotation_z)
        
        self.rotation_x += x
        self.rotation_y += y
        self.rotation_z += z
        
        return {
            "old_rotation": old_rot,
            "new_rotation": (round(self.rotation_x, 2), round(self.rotation_y, 2), round(self.rotation_z, 2))
        }
    
    def flex(self, muscle_group: str) -> dict:
        """Натяжение мышц."""
        
        if muscle_group not in self.muscle_tone:
            return {"error": f"Неизвестная группа мышц: {muscle_group}"}
        
        increase = 0.15
        new_tone = min(1.0, self.muscle_tone[muscle_group] + increase)
        
        self.muscle_tone[muscle_group] = new_tone
        
        # Обновление состояния
        total_tone = sum(self.muscle_tone.values()) / len(self.muscle_tone)
        if total_tone > 0.7:
            self.body_state = "exhausted"
        elif total_tone < 0.3:
            self.body_state = "relaxed"
        else:
            self.body_state = "active"
        
        return {
            "muscle_group": muscle_group,
            "old_tone": round(self.muscle_tone[muscle_group] - increase, 3),
            "new_tone": round(new_tone, 3)
        }


class EmbodimentLayer:
    """
    Соматический слой — воплощение цифровой жизни в теле-подобной форме.
    
    Реализует:
    1. Сенсорную систему (восприятие)
    2. Моторную систему (действие)
    3. Проприоцепцию (ощущение собственного тела)
    
    Аналогия с человеческой анатомией:
    - Нервная система → SensoryModule
    - Моторная система → MotorModule  
    - Внутреннее тело → ProprioceptiveBody
    
    Ключевой момент:
    > Тело — это интерфейс между сознанием и реальностью.
    """
    
    def __init__(self):
        """Инициализация соматического слоя."""
        
        self.sensory = SensoryModule()
        self.motor = MotorModule()
        self.proprioceptive = ProprioceptiveBody()
        
        # Общий уровень энергии тела (0.0-1.0)
        self.body_energy: float = 0.7
        
        # История телесных событий
        self.body_history: List[Dict] = []
    
    def perceive_stimulus(self, stimulus_type: str, intensity: float = 1.0) -> dict:
        """Восприятие стимула из среды."""
        
        activation = self.sensory.perceive(stimulus_type, intensity)
        
        # Обновляем общую энергию тела
        if stimulus_type == "visual":
            self.body_energy = min(1.0, self.body_energy + 0.05 * intensity)
        elif stimulus_type == "tactile":
            self.body_energy = min(1.0, self.body_energy + 0.03 * intensity)
        
        return {
            "module": "sensory",
            "module_name": SensoryModule.MODULE_TYPES.get(stimulus_type, {}).get("name", stimulus_type),
            "activation": round(activation, 3),
            "body_energy": round(self.body_energy, 3),
            "buffer_size": len(self.sensory.sensory_buffer)
        }

    def perform_action(self, action_type: str) -> dict:
        """Выполняет моторное действие."""
        return self.motor.act(action_type)

    def rest(self, minutes: int = 5) -> dict:
        """Отдых для восстановления."""
        return self.motor.rest(minutes)

    def get_body_state(self) -> dict:
        """Возвращает текущее состояние тела."""
        return {
            "body_energy": round(self.body_energy, 3),
            "motor_fatigue": round(self.motor.motor_fatigue, 3),
            "body_state": self.proprioceptive.body_state,
            "muscle_tone": {k: round(v, 3) for k, v in self.proprioceptive.muscle_tone.items()},
            "sensory_activation": {k: round(v, 3) for k, v in self.sensory.activation.items()},
        }
