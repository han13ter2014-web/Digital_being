import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
# Здесь будут импорты из других модулей после рефакторинга (например, from src.motivation.profiles import MotivationProfile)

class Goal:
    """Абстрактный класс для представления одной цели."""
    def __init__(self, title: str, goal_type: str, source: str, priority: float = 0.5):
        self.title = title
        self.goal_type = goal_type # learning, competence, self_improvement и т.д.
        self.source = source      # motivation, values, knowledge_gaps
        self.priority = priority  # Приоритет (0.0 - 1.0)
        self.status = "pending"  # pending, active, completed, abandoned
        self.subgoals: List[Dict] = []
        self.progress = 0.0       # Прогресс в процентах (0.0 - 100.0)
        self.cycle_count = 0     # С какого цикла эта цель была активирована
    
    def __repr__(self):
        return f"Goal('{self.title}', статус={self.status}, прогресс={self.progress:.1f}%)"

class SubGoal:
    """Подцель, декомпозиция основной цели."""
    def __init__(self, title: str, parent_goal_id: int):
        self.title = title
        self.parent_goal_id = parent_goal_id
        self.status = "pending" # pending, completed

class GoalSystem:
    """Центральный менеджер, отвечающий за генерацию, приоритизацию и обновление целей."""
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.goals: List[Goal] = []
        self.active_goal: Optional[Goal] = None

    # --- Методы, извлеченные из старого GoalSystem ---

    def set_motivation(self, motivation_profile: Dict):
        """Устанавливает профиль мотивации для генерации целей."""
        print(f"[GoalManager] Мотивация установлена (Основная потребность: {motivation_profile.get('dominant_need')}).")
        # В идеале здесь должна быть логика, которая вызывает generation из MotivationProfile

    def set_values(self, values_profile: Dict):
        """Устанавливает профиль ценностей."""
        print(f"[GoalManager] Ценности установлены. Доминируют: {', '.join([v['name'] for v in values_profile.get('dominant_values', [])])}")

    def set_knowledge_gaps(self, knowledge_gaps: List[Dict]):
        """Устанавливает список пробелов в знаниях."""
        print(f"[GoalManager] Обнаружено {len(knowledge_gaps)} областей для изучения.")
    
    # --- Генерация (Вызывается при старте цикла) ---

    def generate_and_activate_goals(self, context: Dict = None) -> List[Goal]:
        """Генерирует и активирует цели на основе всех внутренних профилей."""
        print("[GoalManager] Запуск генерации целей из всех источников...")
        newly_generated_goals: List[Goal] = []

        # 1. Генерация от мотивации (Приоритет №1)
        if context and 'motivation' in context:
            mot_goals = self._generate_goals_from_source("motivation", context['motivation'])
            self.goals.extend(mot_goals)
            newly_generated_goals.extend(mot_goals)

        # 2. Генерация от ценностей, пробелов и личности (порядок важен!)
        if context and 'values' in context:
            val_goals = self._generate_goals_from_source("values", context['values'])
            self.goals.extend(val_goals)
            newly_generated_goals.extend(val_goals)

        # ... (Здесь были бы вызовы для личности и пробелов знаний, которые будут добавлены позже)
        
        # Приоритизация и активация
        prioritized = self.prioritize_and_select(newly_generated_goals + [g for g in self.goals if g not in newly_generated_goals])
        return prioritized

    def prioritize_and_select(self, candidate_goals: List[Goal]) -> List[Goal]:
        """Выбирает и устанавливает одну или несколько активных целей."""
        print("[GoalManager] Выборка приоритетных целей...")
        # Здесь должна быть сложная логика выбора по взвешенной формуле.
        if candidate_goals:
            # Временно выбираем первую, как наиболее важную, для простоты рефакторинга
            self.active_goal = candidate_goals[0]
            self.active_goal.status = "active"
            print(f"[GoalManager] Установлена активная цель: {self.active_goal.title}")
        return [g for g in candidate_goals if g.status == "active"]

    # --- Обновление состояния (Вызывается каждый цикл) ---

    def update_all_goals(self, effort_distribution: Dict = None) -> List[Dict]:
        """Обновляет прогресс по всем активным целям."""
        print("[GoalManager] Проверка и обновление прогресса всех целей...")
        results = []
        for goal in self.goals:
            if goal.status == "active":
                # Логика обновления должна учитывать распределение усилий (effort_distribution)
                updated_progress = self._update_goal_progress(goal, effort_distribution)
                results.append({
                    "title": goal.title, 
                    "progress_after": updated_progress['percentage'], 
                    "outcome": "success" if updated_progress['success'] else "failure"
                })
        return results

    def _update_goal_progress(self, goal: Goal, effort: float) -> Dict:
        """Внутренняя логика обновления прогресса одной цели."""
        # Реализация должна учитывать 'effort' и тип цели.
        if goal.status != "active": return {"percentage": 0.0, "success": False}

        goal.cycle_count += 1
        # Здесь будет сложная логика: если достигнут прогресс -> цель завершается.
        return {"percentage": min(100.0, goal.progress + (effort * 2)), "success": True}


    # --- Декомпозиция и Инициализация (Перенос из старого кода) ---

    @staticmethod
    def _generate_goals_from_source(source: str, profile: Dict) -> List[Goal]:
        """Сгенерировать цели на основе источника данных."""
        print(f"  -> Генерация целей по источнику '{source}'...")
        if source == "motivation":
            # Пример: Создаем цель на основе доминантной потребности
            title = f"Изучить {profile['dominant_need']}"
            goal = Goal(title, "learning", "motivation", 0.85)
            goal.subgoals = [SubGoal("Основные концепции", id)] # ID будет подставлен позже
            return [goal]
        # ... (аналогично для values и knowledge_gaps)
        return []

    def decompose(self, goal: Goal, strategy: str):
        """Декомпозиция цели на более мелкие, управляемые шаги."""
        print(f"  -> Декомпозиция '{goal.title}' по стратегии '{strategy}'.")
        # Здесь должна быть логика развертывания subgoals и присвоение им статуса pending
        pass

    def get_dashboard(self) -> dict:
        """Суммарный дашборд."""
        return {
            "active_count": 1, # Placeholder
            "capacity": 3,     # Placeholder
            "completed_count": self.goals.count(lambda g: g.status == "completed"),
            "metrics": {"completion_rate": 0.5}
        }