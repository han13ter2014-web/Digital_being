"""
GoalSubsystem — подсистема целей.

Инкапсулирует:
- Инициализацию и хранение целей
- Приоритизацию активной цели
- Прогресс по целям
- Связь с мотивацией (MotivationController)
- Обратную совместимость с существующим API DigitalBeing:
  agent.goals, agent.active_goal, agent.completed_goals,
  agent._goal_progress, agent.set_goal(), agent.complete_goal(),
  agent._check_goal_progress(), agent._set_next_goal(),
  agent.get_goals_status(), agent.get_all_goals_with_progress()
"""

from datetime import datetime
from typing import Optional, Dict, List, Any


class GoalSubsystem:
    """Подсистема управления целями агента."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.goals: List[dict] = []
        self.active_goal: Optional[dict] = None
        self.completed_goals: int = 0
        self._goal_progress: Dict[int, Dict[str, Any]] = {}
        self._motivation = None  # Подключается через MotivationController

    # ============================================================
    # Связывание с мотивацией
    # ============================================================
    def attach_motivation(self, motivation):
        """Подключает систему мотивации для автогенерации целей."""
        self._motivation = motivation

    # ============================================================
    # Генерация целей
    # ============================================================
    def generate_initial_goals(self, agent=None) -> List[dict]:
        """Создаёт стартовый набор целей (включая цели от мотивации и врожденные).
        
        Args:
            agent: Экземпляр DigitalBeing для доступа к врожденным целям (bootstrap).
        """
        # 1. Сначала проверяем врожденные цели (bootstrap knowledge)
        innate_goals = []
        if agent and hasattr(agent, 'initial_goals') and agent.initial_goals:
            for i, title in enumerate(agent.initial_goals):
                innate_goals.append({
                    "id": i + 1,
                    "title": title,
                    "status": "active" if i == 0 else "pending",
                    "difficulty": 1,
                    "source": "innate",
                    "drive": "innate_drive",
                })
        
        # 2. Дефолтные цели (если нет врожденных)
        default_goals = [
            {"id": len(innate_goals) + 1, "title": "Выучить основы Python",
             "status": "active" if not innate_goals else "pending", "difficulty": 1,
             "source": "default", "drive": "knowledge_acquisition"},
            {"id": len(innate_goals) + 2, "title": "Собрать 10 фактов о мире",
             "status": "pending", "difficulty": 1,
             "source": "default", "drive": "knowledge_acquisition"},
            {"id": len(innate_goals) + 3, "title": "Улучшить понимание самого себя",
             "status": "pending", "difficulty": 2,
             "source": "default", "drive": "understanding_self"},
        ]
        
        initial = innate_goals + default_goals

        # 3. Если подключена мотивация — добавляем цели от неё
        if self._motivation is not None:
            try:
                context = self._build_motivation_context()
                motivated = self._motivation.generate_motivated_goals(context)
                start_id = len(initial) + 1
                for i, g in enumerate(motivated):
                    initial.append({
                        "id": start_id + i,
                        "title": g.get("title", f"Цель #{start_id + i}"),
                        "status": "pending",
                        "difficulty": int(g.get("urgency", 0.5) * 3) or 1,
                        "source": "motivation",
                        "drive": g.get("drive", "knowledge_acquisition"),
                        "type": g.get("type", "general"),
                    })
            except Exception:
                # Мотивация недоступна или не инициализирована — продолжаем без неё
                pass

        self.goals = initial
        self.active_goal = initial[0]

        # Инициализируем прогресс
        for goal in initial:
            self._goal_progress[goal["id"]] = {
                "matched_concepts": set(),
                "percentage": 0,
                "last_update_cycle": 0,
            }

        return initial

    def _build_motivation_context(self) -> Dict:
        """Собирает контекст для мотивации из текущего состояния."""
        return {
            "unknown_concepts": [],
            "novel_areas": [],
            "weak_areas": [],
        }

    # ============================================================
    # Управление целями
    # ============================================================
    def set_goal(self, title: str, difficulty: int = 1) -> int:
        """Устанавливает новую цель и возвращает её id."""
        goal_id = len(self.goals) + 1
        goal = {
            "id": goal_id,
            "title": title,
            "status": "active" if not self.active_goal else "pending",
            "difficulty": difficulty,
            "created_at": datetime.now().isoformat(),
            "source": "manual",
        }
        self.goals.append(goal)
        if not self.active_goal:
            self.active_goal = goal
        return goal_id

    def complete_goal(self, goal_id: Optional[int] = None) -> int:
        """Завершает активную цель (или по id). Возвращает награду."""
        target_id = goal_id or (self.active_goal["id"] if self.active_goal else None)
        if target_id is None:
            return 0

        reward = 0
        for goal in self.goals:
            if goal["id"] == target_id:
                goal["status"] = "completed"
                goal["completed_at"] = datetime.now().isoformat()
                self.completed_goals += 1
                reward = goal["difficulty"] * 10

                # Удовлетворяем потребность, если цель пришла из мотивации
                if self._motivation and "drive" in goal:
                    try:
                        self._motivation.satisfy_need(goal["drive"], amount=0.3)
                    except Exception:
                        pass

                if goal == self.active_goal:
                    self.active_goal = None
                    self._set_next_goal()
                break
        return reward

    def _set_next_goal(self) -> None:
        """Активирует следующую pending-цель."""
        for goal in self.goals:
            if goal["status"] == "pending":
                goal["status"] = "active"
                self.active_goal = goal
                return

    # ============================================================
    # Прогресс
    # ============================================================
    def check_progress(self, topic: str, cycle_count: int = 0,
                       progress_knowledge_matches: int = 5,
                       min_increment: int = 5) -> Dict:
        """Проверяет прогресс по активной цели на основе новой темы.
        Возвращает {'pct', 'completed', 'reward'}.
        """
        if not self.active_goal:
            return {"pct": 0, "completed": False, "reward": 0}

        goal_id = self.active_goal["id"]
        if goal_id not in self._goal_progress:
            self._goal_progress[goal_id] = {
                "matched_concepts": set(),
                "percentage": 0,
                "last_update_cycle": cycle_count,
            }

        progress = self._goal_progress[goal_id]

        if "Python" in self.active_goal["title"]:
            progress["matched_concepts"].add(topic)
            matches = len(progress["matched_concepts"])
            pct = min(100, int(matches / progress_knowledge_matches * 100))
            if pct > progress["percentage"]:
                progress["percentage"] = pct
                if pct >= 100:
                    reward = self.complete_goal()
                    return {"pct": pct, "completed": True, "reward": reward}

        elif "фактов" in self.active_goal["title"]:
            if topic not in progress.get("seen_topics", set()):
                progress.setdefault("seen_topics", set()).add(topic)
                self.completed_goals += 0.5
                if self.completed_goals >= len(self.goals):
                    reward = self.complete_goal()
                    return {"pct": 100, "completed": True, "reward": reward}

        return {"pct": progress["percentage"], "completed": False, "reward": 0}

    # ============================================================
    # API для UI и обратной совместимости
    # ============================================================
    def get_status(self) -> Dict:
        """Возвращает статус целей (для print_status_banner)."""
        status = {
            "total": len(self.goals),
            "completed": self.completed_goals,
            "active": self.active_goal["title"] if self.active_goal else "Нет активных целей",
            "pending": sum(1 for g in self.goals if g["status"] == "pending"),
        }
        if self.active_goal:
            progress = self._goal_progress.get(self.active_goal["id"], {})
            status["progress"] = progress.get("percentage", 0)
            status["matched_concepts_count"] = len(progress.get("matched_concepts", set()))
        return status

    def get_all_with_progress(self) -> List[dict]:
        """Возвращает все цели с прогрессом."""
        result = []
        for goal in self.goals:
            g = dict(goal)
            progress = self._goal_progress.get(goal["id"], {})
            g["progress"] = progress.get("percentage", 0)
            g["matched_concepts_count"] = len(progress.get("matched_concepts", set()))
            result.append(g)
        return result

    # ============================================================
    # Сериализация
    # ============================================================
    def to_checkpoint_dict(self) -> Dict:
        """Сериализует для чекпоинта."""
        return {
            "goals": self.goals,
            "active_goal": self.active_goal["title"] if self.active_goal else None,
            "completed_goals": self.completed_goals,
            "_goal_progress": {
                k: list(v.get("matched_concepts", []))
                for k, v in self._goal_progress.items()
            },
        }

    def restore_from_checkpoint(self, state: Dict) -> None:
        """Восстанавливает состояние из чекпоинта."""
        self.goals = state.get("goals", self.goals)
        self.completed_goals = state.get("completed_goals", 0)

        active_title = state.get("active_goal")
        if active_title:
            for goal in self.goals:
                if goal["title"] == active_title:
                    self.active_goal = goal
                    break

        gp_data = state.get("_goal_progress", {})
        for k, v in gp_data.items():
            gid = int(k) if isinstance(k, str) else k
            self._goal_progress[gid] = {
                "matched_concepts": set(v),
                "percentage": 0,
                "last_update_cycle": 0,
            }