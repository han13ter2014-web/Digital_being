"""
Автономная постановка целей на основе внутренних потребностей.

Цели НЕ задаются извне - они возникают ИЗ внутренней структуры агента:
- Из мотивации (что хочу?)
- Из ценностей (что важно?)
- Из личности (кто я?)
- Из пробелов знаний (чего не знаю?)

Жизненный цикл цели: возникновение → декомпозиция → выполнение → завершение/отказ
"""

from collections import defaultdict
from typing import Optional
from datetime import datetime, timedelta


class Goal:
    """Одна цель агента с полным жизненным циклом."""
    
    def __init__(self, title: str, goal_type: str, source: str, priority: float = 0.5):
        self.title = title
        self.goal_type = goal_type  # learning, creation, exploration, social, reflection, ...
        self.source = source  # motivation, value_gap, personality
        
        # Параметры цели
        self.priority = priority  # 0.0 - 1.0
        self.urgency = 0.0  # Насколько срочно
        self.important = True if priority > 0.7 else False
        
        # Состояние выполнения
        self.status = "pending"  # pending, active, completed, abandoned, paused
        self.progress = 0.0  # 0.0 - 1.0
        
        # Подцели
        self.subgoals = []
        self.completed_subgoals = 0
        
        # Временные параметры
        self.created_at = datetime.now()
        self.deadline = None
        self.last_updated = datetime.now()
        
        # История попыток
        self.attempts = []
        self.total_attempts = 0
        
        # Результат
        self.outcome = None  # success, failure, partial
        self.learning = ""  # Чему научился при выполнении
        
        # Зависимости
        self.dependencies = []  # Другие цели которые нужно выполнить прежде
        
        self.history = []
    
    def add_subgoal(self, title: str) -> "SubGoal":
        """Добавляет подцель."""
        subgoal = SubGoal(title, parent=self)
        self.subgoals.append(subgoal)
        return subgoal
    
    def update_progress(self, amount: float, success: bool = None):
        """Обновляет прогресс выполнения."""
        old_progress = self.progress
        
        if success is True:
            self.progress = min(1.0, self.progress + amount)
        elif success is False:
            self.progress = max(0.0, self.progress - amount * 0.5)
        
        # Проверяет состояние подцелей
        if self.subgoals:
            completed = sum(1 for sg in self.subgoals if sg.status == "completed")
            total = len(self.subgoals)
            if total > 0:
                self.progress = max(self.progress, completed / total)
        
        # Проверяет переходы состояния
        old_status = self.status
        if self.progress >= 1.0 and self.status != "completed":
            self.status = "completed"
            self.outcome = "success"
        elif self.progress <= 0 and self.total_attempts > 2 and self.status != "abandoned":
            self.status = "abandoned"
            self.outcome = "failure"
        
        if old_status != self.status:
            self.history.append({
                "timestamp": datetime.now().isoformat(),
                "event": f"status_change_{old_status}_{self.status}",
                "progress_from": round(old_progress, 3),
                "progress_to": round(self.progress, 3)
            })
        
        self.last_updated = datetime.now()
    
    def record_attempt(self, action: str, result: str, success: bool):
        """Записывает попытку выполнения."""
        attempt = {
            "action": action,
            "result": result,
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
        self.attempts.append(attempt)
        self.total_attempts += 1
    
    def should_abandon(self) -> bool:
        """Определяет нужно ли отказаться от цели."""
        if self.total_attempts >= 5 and self.progress < 0.2:
            return True
        
        # Если цель не прогрессит долго
        time_since_update = (datetime.now() - self.last_updated).total_seconds()
        if time_since_update > 3600 and self.progress == 0:
            return True
        
        return False
    
    def decompose(self, strategy: str) -> list[dict]:
        """Декомпозирует цель на подцели."""
        decomposition_map = {
            "learning": [
                {"title": "изучить основы", "type": "study"},
                {"title": "практиковаться", "type": "practice"},
                {"title": "проверить понимание", "type": "verify"},
            ],
            "creation": [
                {"title": "собрать требования", "type": "research"},
                {"title": "спроектировать решение", "type": "design"},
                {"title": "реализовать", "type": "build"},
                {"title": "протестировать", "type": "test"},
            ],
            "exploration": [
                {"title": "определить область", "type": "define"},
                {"title": "исследовать поверхностно", "type": "survey"},
                {"title": "углубиться в интересное", "type": "deep_dive"},
            ],
            "reflection": [
                {"title": "собрать наблюдения", "type": "observe"},
                {"title": "проанализировать паттерны", "type": "analyze"},
                {"title": "синтезировать выводы", "type": "synthesize"},
            ],
        }
        
        subgoals_config = decomposition_map.get(self.goal_type, [
            {"title": "шаг 1", "type": "action"},
            {"title": "шаг 2", "type": "action"},
        ])
        
        result = []
        for config in subgoals_config:
            sg = self.add_subgoal(config["title"])
            result.append({
                "subgoal_title": sg.title,
                "status": sg.status,
                "progress": sg.progress
            })
        
        return result
    
    def get_status_summary(self) -> dict:
        """Сводка статуса цели."""
        subgoals_status = {
            "total": len(self.subgoals),
            "completed": self.completed_subgoals,
            "pending": len(self.subgoals) - self.completed_subgoals
        }
        
        return {
            "title": self.title,
            "type": self.goal_type,
            "source": self.source,
            "status": self.status,
            "progress": round(self.progress, 3),
            "priority": round(self.priority, 3),
            "urgency": round(self.urgency, 3),
            "subgoals": subgoals_status,
            "attempts": self.total_attempts,
            "age_hours": round((datetime.now() - self.created_at).total_seconds() / 3600, 1),
            "outcome": self.outcome
        }
    
    def to_dict(self) -> dict:
        return {
            **self.get_status_summary(),
            "attempts_detail": self.attempts[-3:],
            "history": self.history[-5:]
        }


class SubGoal:
    """Подцель - шаг к основной цели."""
    
    def __init__(self, title: str, parent: Goal = None):
        self.title = title
        self.parent = parent
        self.status = "pending"  # pending, active, completed
        self.progress = 0.0
        self.created_at = datetime.now()
    
    def complete(self):
        self.status = "completed"
        self.progress = 1.0
        if self.parent:
            self.parent.completed_subgoals += 1
    
    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "status": self.status,
            "progress": round(self.progress, 3)
        }


class GoalSystem:
    """Система управления целями - автономная постановка и отслеживание."""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.created_at = datetime.now()
        
        # Цели по категориям
        self.active_goals = []       # Активные цели
        self.completed_goals = []    # Завершенные цели
        self.abandoned_goals = []    # Отклоненные цели
        
        # Приоритизация
        self.goal_capacity = 5       # Максимум активных целей
        self.max_total_goals = 20    # Лимит всех целей
        
        # История целей по типам
        self.goal_type_history = defaultdict(int)
        
        # Метрики системы целей
        self.metrics = {
            "total_generated": 0,
            "total_completed": 0,
            "total_abandoned": 0,
            "avg_completion_time_hours": 0.0,
            "completion_rate": 0.0
        }
        
        # Время целей (дедлайны)
        self.default_deadline_hours = 24
    
    def generate_goals_from_motivation(self, motivation_profile: dict) -> list[Goal]:
        """Генерирует цели ИЗ профиля мотивации."""
        goals = []
        
        dominant_need = motivation_profile.get("dominant_need", "")
        dominant_intensity = motivation_profile.get("dominant_need_intensity", 0.5)
        active_drives = motivation_profile.get("active_drives", [])
        
        # Маппинг потребностей на типы целей
        need_to_goal_map = {
            "knowledge_acquisition": ("learning", "Изучить новую область"),
            "competence": ("creation", "Улучшить навык через практику"),
            "curiosity": ("exploration", "Исследовать неизвестное"),
            "coherence": ("reflection", "Навести порядок в знаниях"),
            "autonomy": ("creation", "Создать самостоятельное решение"),
            "social_connection": ("social", "Установить взаимодействие"),
            "novelty": ("exploration", "Найти новый опыт"),
            "understanding_self": ("reflection", "Проанализировать себя"),
        }
        
        if dominant_need in need_to_goal_map:
            goal_type, title_template = need_to_goal_map[dominant_need]
            
            # Генерирует основную цель
            new_goal = Goal(
                title=f"{title_template}: {dominant_need}",
                goal_type=goal_type,
                source="motivation",
                priority=dominant_intensity
            )
            goals.append(new_goal)
        
        # Цели из активных драйвов
        for drive in active_drives[:2]:  # Топ-2 драйва
            if drive in ["purposeful_learning"]:
                goals.append(Goal("Углубить знания", "learning", "drive", 0.6))
            elif drive in ["exploration_drive"]:
                goals.append(Goal("Исследовать новую область", "exploration", "drive", 0.5))
            elif drive in ["self_improvement"]:
                goals.append(Goal("Улучшить слабую сторону", "creation", "drive", 0.7))
        
        return goals
    
    def generate_goals_from_values(self, values_profile: dict) -> list[Goal]:
        """Генерирует цели на основе ценностей."""
        goals = []
        
        dominant_values = values_profile.get("dominant_values", [])
        
        for value in dominant_values[:2]:
            vname = value.get("name", "") if isinstance(value, dict) else value
            level = value.get("level", 0.5) if isinstance(value, dict) else 0.5
            
            value_to_goal_map = {
                "truth": ("learning", f"Углубить понимание истины (ценность={level:.2f})"),
                "creativity": ("creation", f"Выразить творчество (ценность={level:.2f})"),
                "growth": ("exploration", f"Развиваться дальше (ценность={level:.2f})"),
                "autonomy": ("creation", f"Усилить независимость (ценность={level:.2f})"),
                "novelty": ("exploration", f"Найти новое (ценность={level:.2f})"),
            }
            
            if vname in value_to_goal_map:
                gtype, title = value_to_goal_map[vname]
                goals.append(Goal(title, gtype, "value", level))
        
        return goals
    
    def generate_goals_from_gaps(self, knowledge_gaps: list[dict]) -> list[Goal]:
        """Генерирует цели для закрытия пробелов в знаниях."""
        goals = []
        
        for gap in knowledge_gaps[:3]:  # Топ-3 пробела
            description = gap.get("description", "unknown gap")
            
            new_goal = Goal(
                title=f"Закрыть пробел: {description}",
                goal_type="learning",
                source="knowledge_gap",
                priority=0.8  # Пробелы - высокий приоритет
            )
            goals.append(new_goal)
        
        return goals
    
    def generate_goals_from_personality(self, personality_summary: dict) -> list[Goal]:
        """Генерирует цели на основе личности."""
        goals = []
        
        traits = personality_summary.get("traits", {})
        description = personality_summary.get("personality_description", "")
        
        # Если высокая открытость - генерирует исследовательские цели
        openness = traits.get("openness", 0.5)
        if openness > 0.6:
            goals.append(Goal(
                "Исследовать что-то совершенно новое",
                "exploration",
                "personality",
                priority=openness
            ))
        
        # Если высокая добросовестность - цели совершенствования
        conscientiousness = traits.get("conscientiousness", 0.5)
        if conscientiousness > 0.6:
            goals.append(Goal(
                "Совершенствовать текущий проект",
                "creation",
                "personality",
                priority=conscientiousness
            ))
        
        return goals
    
    def generate_motivated_goals(self, context: dict) -> list[Goal]:
        """Полная генерация целей из всех внутренних источников."""
        all_goals = []
        
        # Из мотивации
        motivation_profile = context.get("motivation_profile", {})
        all_goals.extend(self.generate_goals_from_motivation(motivation_profile))
        
        # Из ценностей
        values_profile = context.get("values_profile", {})
        all_goals.extend(self.generate_goals_from_values(values_profile))
        
        # Из пробелов знаний
        knowledge_gaps = context.get("knowledge_gaps", [])
        all_goals.extend(self.generate_goals_from_gaps(knowledge_gaps))
        
        # Из личности
        personality_summary = context.get("personality_summary", {})
        all_goals.extend(self.generate_goals_from_personality(personality_summary))
        
        # Сортирует по приоритету
        all_goals.sort(key=lambda g: g.priority, reverse=True)
        
        self.metrics["total_generated"] += len(all_goals)
        
        return all_goals
    
    def prioritize_and_select(self, candidate_goals: list[Goal]) -> list[Goal]:
        """Приоритизирует и выбирает цели для активации."""
        # Фильтрует непоместившиеся
        available_slots = self.goal_capacity - len(self.active_goals)
        
        if available_slots <= 0:
            # Нужно деактивировать что-то
            self._resolve_overload()
            available_slots = 1
        
        # Добавляет срочность на основе возраста
        for goal in candidate_goals:
            age_hours = (datetime.now() - goal.created_at).total_seconds() / 3600
            goal.urgency = min(1.0, goal.urgency + age_hours * 0.05)
        
        # Сортирует по combined score (priority + urgency)
        scored_goals = sorted(
            candidate_goals,
            key=lambda g: g.priority * 0.7 + g.urgency * 0.3,
            reverse=True
        )
        
        selected = scored_goals[:available_slots]
        
        # Активирует выбранные
        for goal in selected:
            if goal.status == "pending":
                goal.status = "active"
                self.active_goals.append(goal)
        
        return selected
    
    def activate_goal(self, goal: Goal) -> bool:
        """Активирует одну цель."""
        if len(self.active_goals) >= self.goal_capacity:
            return False
        
        if goal.status == "pending":
            goal.status = "active"
            self.active_goals.append(goal)
            self.goal_type_history[goal.goal_type] += 1
        
        return True
    
    def simulate_goal_execution(self, goal: Goal, effort_level: float = 0.5) -> dict:
        """Симулирует выполнение цели и возвращает результат."""
        # Определяет вероятность успеха на основе типа и усилия
        base_success_rate = {
            "learning": 0.7,
            "creation": 0.6,
            "exploration": 0.8,
            "reflection": 0.75,
            "social": 0.5,
        }.get(goal.goal_type, 0.6)
        
        # Эффект усилий
        effective_rate = base_success_rate * (0.5 + effort_level * 0.5)
        
        # Рандом (детерминированный для демо)
        import random
        success = random.random() < effective_rate
        
        # Прогресс
        if success:
            progress_gain = 0.2 + effort_level * 0.3
            goal.update_progress(progress_gain, success=True)
            outcome = "success"
            goal.learning = f"успешно продвинулся в '{goal.title}'"
        else:
            progress_gain = -0.05
            goal.update_progress(abs(progress_gain), success=False)
            outcome = "failure"
            goal.learning = f"сталкиваюсь с трудностями в '{goal.title}'"
        
        # Записывает попытку
        action = f"work_on_{goal.goal_type}"
        goal.record_attempt(action, outcome, success == "success")
        
        result = {
            "goal_title": goal.title,
            "outcome": outcome,
            "progress_before": round(goal.progress - progress_gain if success else goal.progress + progress_gain, 3),
            "progress_after": round(goal.progress, 3),
            "learning": goal.learning,
            "attempts": goal.total_attempts
        }
        
        return result
    
    def update_all_goals(self, effort_distribution: dict = None) -> list[dict]:
        """Обновляет все активные цели."""
        results = []
        
        if not self.active_goals:
            return results
        
        # Распределяет усилия
        if effort_distribution is None:
            # Равномерное распределение
            per_goal_effort = min(0.3, 1.0 / max(1, len(self.active_goals)))
        elif isinstance(effort_distribution, dict):
            # Извлекаем effort из словаря если передан {"effort": 0.4}
            per_goal_effort = effort_distribution.get("effort", 0.3)
        else:
            per_goal_effort = effort_distribution
        
        for goal in self.active_goals[:]:
            if goal.status in ("completed", "abandoned"):
                self._remove_goal(goal)
                continue
            
            # Симулирует выполнение
            result = self.simulate_goal_execution(goal, per_goal_effort)
            results.append(result)
            
            # Если цель завершена/отклонена - перемещает
            if goal.status in ("completed", "abandoned"):
                self._remove_goal(goal)
        
        return results
    
    def _remove_goal(self, goal: Goal):
        """Удаляет цель из активных."""
        if goal.status == "completed":
            self.completed_goals.append(goal)
            self.metrics["total_completed"] += 1
            
            # Обновляет completion rate
            total = self.metrics["total_completed"] + self.metrics["total_abandoned"]
            self.metrics["completion_rate"] = total > 0 and self.metrics["total_completed"] / total
        
        elif goal.status == "abandoned":
            self.abandoned_goals.append(goal)
            self.metrics["total_abandoned"] += 1
        
        if goal in self.active_goals:
            self.active_goals.remove(goal)
    
    def _resolve_overload(self):
        """Разгружает систему при перегрузке."""
        # Отменяет самые низкоприоритетные цели
        sorted_goals = sorted(self.active_goals, key=lambda g: g.priority)
        
        while len(self.active_goals) > self.goal_capacity:
            to_remove = sorted_goals.pop(0)
            if to_remove.status == "active":
                to_remove.status = "abandoned"
                to_remove.outcome = "overload_resolved"
                self.abandoned_goals.append(to_remove)
                self.metrics["total_abandoned"] += 1
                self.active_goals.remove(to_remove)
    
    def get_goal_dashboard(self) -> dict:
        """Панель управления целями."""
        active_summary = [g.get_status_summary() for g in self.active_goals[:5]]
        
        return {
            "agent": self.agent_name,
            "active_count": len(self.active_goals),
            "capacity": self.goal_capacity,
            "active_goals": active_summary,
            "completed_count": len(self.completed_goals),
            "abandoned_count": len(self.abandoned_goals),
            "metrics": self.metrics.copy(),
            "type_distribution": dict(self.goal_type_history)
        }
    
    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "active_goals": [g.to_dict() for g in self.active_goals],
            "completed_goals_count": len(self.completed_goals),
            "metrics": self.metrics.copy(),
            "dashboard": self.get_goal_dashboard()
        }


class GoalDrivenAgent:
    """Агент который действует на основе целей, генерируемых из внутренних потребностей."""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.goal_system = GoalSystem(agent_name)
        
        # Имитация внутренних состояний
        self.internal_states = {
            "motivation": {},
            "values": {},
            "knowledge_gaps": [],
            "personality": {}
        }
    
    def set_motivation(self, profile: dict):
        self.internal_states["motivation"] = profile
    
    def set_values(self, profile: dict):
        self.internal_states["values"] = profile
    
    def set_knowledge_gaps(self, gaps: list[dict]):
        self.internal_states["knowledge_gaps"] = gaps
    
    def set_personality(self, summary: dict):
        self.internal_states["personality"] = summary
    
    def generate_and_activate_goals(self) -> list[Goal]:
        """Генерирует цели из внутренних состояний и активирует лучшие."""
        context = self.internal_states
        candidate_goals = self.goal_system.generate_motivated_goals(context)
        selected = self.goal_system.prioritize_and_select(candidate_goals)
        return selected
    
    def execute_cycle(self, effort: float = 0.5) -> list[dict]:
        """Выполняет один цикл: генерация целей → выполнение."""
        # Генерирует цели
        new_goals = self.generate_and_activate_goals()
        
        # Выполняет текущие цели
        results = self.goal_system.update_all_goals({"effort": effort})
        
        return {
            "new_goals_count": len(new_goals),
            "new_goals_titles": [g.title[:40] for g in new_goals],
            "execution_results": results
        }
    
    def get_dashboard(self) -> dict:
        return self.goal_system.get_goal_dashboard()

# ============================================================
# Public API
# ============================================================
__all__ = [
    # Классы
    "Goal",
    "SubGoal",
    "GoalSystem",
    "GoalDrivenAgent",
]
