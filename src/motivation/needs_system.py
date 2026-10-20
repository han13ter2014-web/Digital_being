"""
Система внутренней мотивации для автономного ИИ-агента.

Цели возникают из внутренних потребностей, а не задаются внешне.
Агент развивается от базовых нужд к сложным драйвам.
"""

from collections import defaultdict
from typing import Optional
from datetime import datetime


class Need:
    """Базовая потребность - внутренний мотиватор поведения."""
    
    def __init__(self, name: str, base_level: float = 1.0, decay_rate: float = 0.01):
        self.name = name
        self.level = base_level  # Текущая острота потребности (0.0 - 1.0)
        self.base_level = base_level
        self.decay_rate = decay_rate  # Скорость насыщения
        
        self.history = []  # История изменения уровня
        self.satisfaction_events = []  # События удовлетворения
        self.satisfied_count = 0  # Сколько раз была удовлетворена
        
    def satisfy(self, amount: float = 0.3):
        """Удовлетворяет потребность (снижает её остроту)."""
        self.level = max(0.0, self.level - amount)
        self.satisfied_count += 1
        self.satisfaction_events.append({
            "timestamp": datetime.now().isoformat(),
            "amount": amount
        })
    
    def grow(self, amount: float = 0.1):
        """Потребность растет со временем (возвращается к базовому уровню)."""
        self.level = min(1.0, self.level + amount)
    
    def record_state(self):
        """Записывает текущее состояние в историю."""
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "level": self.level
        })
        # Хранит только последние 100 записей
        if len(self.history) > 100:
            self.history = self.history[-100:]
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "level": round(self.level, 3),
            "base_level": self.base_level,
            "satisfied_count": self.satisfied_count,
            "decay_rate": self.decay_rate
        }


class Drive:
    """Производный драйв - emerges из комбинации базовых потребностей."""
    
    def __init__(self, name: str, contributing_needs: dict[str, float], 
                 activation_threshold: float = 0.7):
        """
        Args:
            name: Название драйва
            contributing_needs: {need_name: weight} - какие потребности влияют
            activation_threshold: Порог активации драйва
        """
        self.name = name
        self.contributing_needs = contributing_needs
        self.activation_threshold = activation_threshold
        self.current_level = 0.0  # Текущая сила драйва (0.0 - 1.0)
        self.active_count = 0  # Сколько раз был активен
        self.created_at = datetime.now()
    
    def calculate_intensity(self, needs_state: dict[str, float]) -> float:
        """Вычисляет текущую интенсивность на основе уровней потребностей."""
        if not self.contributing_needs:
            return 0.0
        
        weighted_sum = sum(
            needs_state.get(name, 0.0) * weight
            for name, weight in self.contributing_needs.items()
        )
        
        total_weight = sum(self.contributing_needs.values())
        if total_weight > 0:
            self.current_level = min(1.0, weighted_sum / total_weight)
        else:
            self.current_level = 0.0
        
        return self.current_level
    
    def is_active(self) -> bool:
        """Активен ли драйв в данный момент."""
        return self.current_level >= self.activation_threshold
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "contributing_needs": self.contributing_needs,
            "activation_threshold": self.activation_threshold,
            "current_level": round(self.current_level, 3),
            "is_active": self.is_active(),
            "active_count": self.active_count
        }


class InternalMotivationSystem:
    """Система внутренней мотивации автономного агента."""
    
    # Базовые потребности (универсальные для любого разумного агента)
    BASIC_NEEDS_CONFIG = {
        "knowledge_acquisition": {"base": 1.0, "decay": 0.02},    # Потребность знать
        "competence": {"base": 0.8, "decay": 0.015},              # Потребность быть компетентным
        "curiosity": {"base": 0.9, "decay": 0.025},               # Любопытство к новому
        "coherence": {"base": 0.7, "decay": 0.01},                # Стремление к согласованности
        "autonomy": {"base": 0.6, "decay": 0.008},                # Стремление к независимости
        "social_connection": {"base": 0.5, "decay": 0.012},       # Потребность взаимодействия
        "novelty": {"base": 0.7, "decay": 0.02},                  # Потребность новизны
        "understanding_self": {"base": 0.6, "decay": 0.009},     # Понимание себя
    }
    
    # Производные драйвы (эмерджентные)
    DRIVES_CONFIG = [
        {
            "name": "purposeful_learning",
            "contributing_needs": {"knowledge_acquisition": 0.6, "competence": 0.4},
            "threshold": 0.6
        },
        {
            "name": "exploration_drive",
            "contributing_needs": {"curiosity": 0.5, "novelty": 0.5},
            "threshold": 0.7
        },
        {
            "name": "self_improvement",
            "contributing_needs": {"competence": 0.4, "understanding_self": 0.4, "autonomy": 0.2},
            "threshold": 0.65
        },
        {
            "name": "meaning_making",
            "contributing_needs": {"coherence": 0.5, "understanding_self": 0.3, "knowledge_acquisition": 0.2},
            "threshold": 0.75
        },
        {
            "name": "creative_synthesis",
            "contributing_needs": {"curiosity": 0.3, "novelty": 0.4, "coherence": 0.3},
            "threshold": 0.8
        },
    ]
    
    def __init__(self, agent_name: str = "agent"):
        self.agent_name = agent_name
        self.needs: dict[str, Need] = {}
        self.drives: dict[str, Drive] = {}
        
        # Инициализирует базовые потребности
        for name, config in self.BASIC_NEEDS_CONFIG.items():
            self.needs[name] = Need(name, config["base"], config["decay"])
        
        # Инициализирует производные драйвы
        for drive_config in self.DRIVES_CONFIG:
            self.drives[drive_config["name"]] = Drive(
                drive_config["name"],
                drive_config["contributing_needs"],
                drive_config["threshold"]
            )
        
        self.goal_history = []  # История сгенерированных целей
        self.last_motivated_goals = []
    
    def get_dominant_need(self) -> tuple[str, float]:
        """Возвращает самую острую потребность."""
        if not self.needs:
            return ("unknown", 0.0)
        
        dominant = max(self.needs.items(), key=lambda x: x[1].level)
        return (dominant[0], dominant[1].level)
    
    def calculate_drive_levels(self) -> dict[str, float]:
        """Вычисляет текущие уровни всех драйвов."""
        needs_state = {name: need.level for name, need in self.needs.items()}
        
        drive_levels = {}
        for drive_name, drive in self.drives.items():
            intensity = drive.calculate_intensity(needs_state)
            drive_levels[drive_name] = intensity
            
            if drive.is_active():
                drive.active_count += 1
        
        return drive_levels
    
    def generate_motivated_goals(self, agent_context: dict = None) -> list[dict]:
        """Генерирует цели на основе внутренних потребностей."""
        agent_context = agent_context or {}
        
        # Обновляет уровни драйвов
        drive_levels = self.calculate_drive_levels()
        
        # Находит активные драйвы
        active_drives = [
            (name, level) for name, level in drive_levels.items()
            if level > 0.5
        ]
        active_drives.sort(key=lambda x: x[1], reverse=True)
        
        goals = []
        
        # Получает доминантную потребность (всегда для истории)
        dominant_need_name, dominant_need_level = self.get_dominant_need()
        
        # Генерирует цели для каждого активного драйва
        for drive_name, drive_level in active_drives[:3]:  # Топ-3 драйва
            drive_goals = self._generate_drive_specific_goals(
                drive_name, drive_level, agent_context
            )
            goals.extend(drive_goals)
        
        # Если нет активных целей - использует доминантную потребность
        if not goals and dominant_need_level > 0.5:
            goals = self._generate_need_based_goals(dominant_need_name)
        
        self.last_motivated_goals = goals
        
        # Записывает цели в историю
        for goal in goals:
            goal["generated_at"] = datetime.now().isoformat()
            goal["internal_drive"] = goal.get("drive", dominant_need_name)
            self.goal_history.append(goal)
        
        return goals
    
    def _generate_drive_specific_goals(self, drive_name: str, 
                                        drive_level: float,
                                        context: dict) -> list[dict]:
        """Генерирует цели специфичные для драйва."""
        goals = []
        
        if drive_name == "purposeful_learning":
            unknown_concepts = context.get("unknown_concepts", [])
            if unknown_concepts:
                goals.append({
                    "title": f"Изучить: {unknown_concepts[0]}",
                    "type": "learning",
                    "drive": drive_name,
                    "urgency": drive_level,
                    "description": f"Агент ощущает потребность узнать о '{unknown_concepts[0]}'"
                })
            else:
                goals.append({
                    "title": "Углубить понимание известных концепций",
                    "type": "deepening",
                    "drive": drive_name,
                    "urgency": drive_level * 0.7
                })
        
        elif drive_name == "exploration_drive":
            novel_areas = context.get("novel_areas", [])
            if novel_areas:
                goals.append({
                    "title": f"Исследовать новую область: {novel_areas[0]}",
                    "type": "exploration",
                    "drive": drive_name,
                    "urgency": drive_level,
                    "description": f"Любопытство тянет к '{novel_areas[0]}'"
                })
            else:
                goals.append({
                    "title": "Исследовать неизвестные связи между концепциями",
                    "type": "exploration",
                    "drive": drive_name,
                    "urgency": drive_level * 0.8
                })
        
        elif drive_name == "self_improvement":
            weak_areas = context.get("weak_areas", ["reasoning"])
            goals.append({
                "title": f"Улучшить способность: {weak_areas[0]}",
                "type": "improvement",
                "drive": drive_name,
                "urgency": drive_level * 0.9
            })
        
        elif drive_name == "meaning_making":
            goals.append({
                "title": "Найти общие паттерны в полученном опыте",
                "type": "synthesis",
                "drive": drive_name,
                "urgency": drive_level * 0.85
            })
        
        elif drive_name == "creative_synthesis":
            goals.append({
                "title": "Создать новую комбинацию известных концепций",
                "type": "creative",
                "drive": drive_name,
                "urgency": drive_level * 0.95
            })
        
        return goals
    
    def _generate_need_based_goals(self, need_name: str) -> list[dict]:
        """Генерирует цели напрямую из потребности."""
        goal_mappings = {
            "knowledge_acquisition": {
                "title": "Получить новые знания",
                "type": "learning"
            },
            "competence": {
                "title": "Улучшить эффективность действий",
                "type": "improvement"
            },
            "curiosity": {
                "title": "Исследовать неизвестное",
                "type": "exploration"
            },
            "coherence": {
                "title": "Устранить противоречия в знаниях",
                "type": "integration"
            },
            "autonomy": {
                "title": "Развить способность к самостоятельности",
                "type": "growth"
            },
            "social_connection": {
                "title": "Установить взаимодействие с другим агентом",
                "type": "social"
            },
            "novelty": {
                "title": "Найти новый уникальный опыт",
                "type": "exploration"
            },
            "understanding_self": {
                "title": "Проанализировать собственное поведение и паттерны",
                "type": "reflection"
            },
        }
        
        mapping = goal_mappings.get(need_name, {
            "title": f"Удовлетворить потребность: {need_name}",
            "type": "general"
        })
        
        return [{
            **mapping,
            "drive": need_name,
            "urgency": self.needs[need_name].level
        }]
    
    def satisfy_need(self, need_name: str, amount: float = 0.3):
        """Удовлетворяет конкретную потребность."""
        if need_name in self.needs:
            self.needs[need_name].satisfy(amount)
            
            # Когда базовая потребность удовлетворена, растут другие
            if self.needs[need_name].level < 0.2:
                # Рост смежных потребностей
                if need_name == "knowledge_acquisition":
                    self.needs["understanding_self"].grow(0.15)
                    self.needs["coherence"].grow(0.1)
                elif need_name == "competence":
                    self.needs["autonomy"].grow(0.1)
                elif need_name == "curiosity":
                    self.needs["novelty"].grow(0.15)
    
    def time_progression(self):
        """Обрабатывает временной прогресс - потребности растут."""
        for need in self.needs.values():
            need.grow(need.decay_rate)
            need.record_state()
    
    def get_motivation_profile(self) -> dict:
        """Возвращает полный профиль мотивации агента."""
        needs_profile = {name: need.level for name, need in self.needs.items()}
        drives_profile = self.calculate_drive_levels()
        dominant_need, dominant_level = self.get_dominant_need()
        
        return {
            "needs": needs_profile,
            "drives": drives_profile,
            "dominant_need": dominant_need,
            "dominant_need_intensity": round(dominant_level, 3),
            "active_drives": [
                name for name, level in drives_profile.items()
                if level > 0.5
            ],
            "satisfaction_summary": {
                name: need.satisfied_count 
                for name, need in self.needs.items()
            }
        }
    
    def get_status(self) -> dict:
        """Возвращает статус системы мотивации."""
        return {
            "agent_name": self.agent_name,
            "needs": {name: n.to_dict() for name, n in self.needs.items()},
            "drives": {name: d.to_dict() for name, d in self.drives.items()},
            "motivation_profile": self.get_motivation_profile()
        }
    
    def to_dict(self) -> dict:
        """Серилизует всю систему."""
        return {
            "agent_name": self.agent_name,
            "needs": {name: n.to_dict() for name, n in self.needs.items()},
            "drives": {name: d.to_dict() for name, d in self.drives.items()},
            "goal_history_count": len(self.goal_history),
            "last_goals": self.last_motivated_goals[-5:]
        }