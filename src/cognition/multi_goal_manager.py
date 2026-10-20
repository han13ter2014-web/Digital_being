import json
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum


class GoalState(Enum):
    """Состояния цели."""
    PENDING = "pending"          # Ожидает начала
    ACTIVE = "active"            # Активно выполняется
    PAUSED = "paused"            # Приостановлена
    BLOCKED = "blocked"          # Заблокирована (нужны ресурсы)
    COMPLETED = "completed"      # Завершена
    FAILED = "failed"            # Не получилась


class Goal:
    """Представляет отдельную цель с многоцикловым управлением."""

    def __init__(self, goal_id: int, title: str, description: str = "",
                 difficulty: int = 1, priority: int = 1):
        self.id = goal_id
        self.title = title
        self.description = description
        self.difficulty = difficulty
        self.priority = priority  # 1=низкий, 5=критический

        self.state = GoalState.PENDING
        self.progress = 0.0  # 0.0-1.0
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

        self.sub_goals: List['Goal'] = []
        self.required_resources: List[str] = []
        self.blocked_by: List[int] = []  # IDs целей которые блокируют
        self.contributes_to: List[int] = []  # IDs целей к которым это вносит вклад

        self.cycles_spent = 0  # Сколько циклов работаем над целью
        self.interruptions = 0  # Сколько раз была приостановлена
        self.last_worked_cycle = 0  # В каком цикле последний раз работали

    def activate(self):
        """Активирует цель."""
        if self.state == GoalState.PENDING:
            self.state = GoalState.ACTIVE
            self.started_at = datetime.now()

    def pause(self):
        """Приостанавливает цель."""
        if self.state == GoalState.ACTIVE:
            self.state = GoalState.PAUSED
            self.interruptions += 1

    def resume(self):
        """Возобновляет цель."""
        if self.state == GoalState.PAUSED:
            self.state = GoalState.ACTIVE

    def complete(self, reward: float = 10.0):
        """Завершает цель."""
        self.state = GoalState.COMPLETED
        self.progress = 1.0
        self.completed_at = datetime.now()
        return reward * (1.0 + self.difficulty * 0.5)

    def fail(self):
        """Отмечает цель как неудачную."""
        self.state = GoalState.FAILED
        self.completed_at = datetime.now()

    def block(self, blocking_goal_id: int):
        """Блокирует цель другой целью."""
        self.state = GoalState.BLOCKED
        self.blocked_by.append(blocking_goal_id)

    def get_time_spent(self) -> float:
        """Возвращает время затраченное на цель (часы)."""
        if self.started_at:
            end = self.completed_at or datetime.now()
            delta = end - self.started_at
            return delta.total_seconds() / 3600
        return 0.0

    def to_dict(self) -> dict:
        """Сериализует цель."""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'difficulty': self.difficulty,
            'priority': self.priority,
            'state': self.state.value,
            'progress': self.progress,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'cycles_spent': self.cycles_spent,
            'interruptions': self.interruptions,
            'sub_goals': len(self.sub_goals),
            'required_resources': self.required_resources,
            'blocked_by': self.blocked_by,
            'contributes_to': self.contributes_to
        }

    @staticmethod
    def from_dict(data: dict) -> 'Goal':
        """Десериализует цель."""
        goal = Goal(
            goal_id=data['id'],
            title=data['title'],
            description=data.get('description', ''),
            difficulty=data.get('difficulty', 1),
            priority=data.get('priority', 1)
        )

        goal.state = GoalState(data.get('state', 'pending'))
        goal.progress = data.get('progress', 0.0)
        goal.cycles_spent = data.get('cycles_spent', 0)
        goal.interruptions = data.get('interruptions', 0)
        goal.required_resources = data.get('required_resources', [])
        goal.blocked_by = data.get('blocked_by', [])
        goal.contributes_to = data.get('contributes_to', [])

        if data.get('created_at'):
            goal.created_at = datetime.fromisoformat(data['created_at'])
        if data.get('started_at'):
            goal.started_at = datetime.fromisoformat(data['started_at'])
        if data.get('completed_at'):
            goal.completed_at = datetime.fromisoformat(data['completed_at'])

        return goal


class MultiTaskGoalManager:
    """Управляет множеством целей одновременно."""

    def __init__(self, max_active_goals: int = 3):
        self.goals: Dict[int, Goal] = {}
        self.max_active_goals = max_active_goals
        self.next_goal_id = 1
        self._goal_history: List[Dict] = []

    def add_goal(self, title: str, description: str = "",
                difficulty: int = 1, priority: int = 1) -> Goal:
        """Добавляет новую цель."""
        goal = Goal(self.next_goal_id, title, description, difficulty, priority)
        self.goals[goal.id] = goal
        self.next_goal_id += 1
        return goal

    def get_active_goals(self) -> List[Goal]:
        """Возвращает активные цели."""
        return [g for g in self.goals.values() if g.state == GoalState.ACTIVE]

    def get_available_goals_to_activate(self) -> List[Goal]:
        """Возвращает цели готовые к активации."""
        available = []

        for goal in self.goals.values():
            if goal.state != GoalState.PENDING:
                continue

            # Проверяем зависимости (блокирующие цели должны быть завершены)
            if goal.blocked_by:
                blocker_exists = any(
                    self.goals.get(bid, Goal(bid, "")).state != GoalState.COMPLETED
                    for bid in goal.blocked_by
                )
                if blocker_exists:
                    continue

            available.append(goal)

        # Сортируем по приоритету и сложности
        available.sort(key=lambda g: (g.priority, g.difficulty), reverse=True)
        return available

    def select_goals_for_cycle(self, available_energy: float) -> List[Goal]:
        """Выбирает цели для работы в текущем цикле.

        Использует стратегию распределения энергии между целями.
        """
        active = self.get_active_goals()
        available = self.get_available_goals_to_activate()

        # Активируем новые цели если есть место
        while len(active) < self.max_active_goals and available:
            goal = available.pop(0)
            goal.activate()
            active.append(goal)

        # Приоритизируем цели для работы (простой RR + приоритет)
        active.sort(key=lambda g: (g.priority, -g.cycles_spent), reverse=True)

        return active[:self.max_active_goals]

    def update_goal_progress(self, goal_id: int, progress_delta: float):
        """Обновляет прогресс цели."""
        goal = self.goals.get(goal_id)
        if goal:
            goal.progress = min(1.0, goal.progress + progress_delta)

    def complete_goal(self, goal_id: int) -> float:
        """Завершает цель и возвращает награду."""
        goal = self.goals.get(goal_id)
        if goal:
            reward = goal.complete()
            # Разблокируем зависящие от неё цели
            for other_goal in self.goals.values():
                if goal_id in other_goal.blocked_by:
                    other_goal.blocked_by.remove(goal_id)
            return reward
        return 0.0

    def fail_goal(self, goal_id: int):
        """Отмечает цель как неудачную."""
        goal = self.goals.get(goal_id)
        if goal:
            goal.fail()

    def get_goals_summary(self) -> Dict:
        """Возвращает сводку по целям."""
        by_state = {}
        for state in GoalState:
            by_state[state.value] = len([g for g in self.goals.values() if g.state == state])

        completed = [g for g in self.goals.values() if g.state == GoalState.COMPLETED]
        total_reward = sum(g.difficulty for g in completed) * 10

        return {
            'total_goals': len(self.goals),
            'by_state': by_state,
            'completed_count': len(completed),
            'active_goals': len(self.get_active_goals()),
            'total_reward_earned': total_reward,
            'blocked_goals': len([g for g in self.goals.values() if g.blocked_by])
        }

    def get_goal_efficiency(self, goal_id: int) -> Dict:
        """Вычисляет эффективность работы над целью."""
        goal = self.goals.get(goal_id)
        if not goal:
            return {}

        if goal.cycles_spent == 0:
            return {'efficiency': 0.0, 'cycles_per_percent': 0}

        cycles_per_percent = goal.cycles_spent / max(goal.progress, 0.01)

        return {
            'goal_title': goal.title,
            'progress': goal.progress,
            'cycles_spent': goal.cycles_spent,
            'cycles_per_percent': cycles_per_percent,
            'efficiency': goal.progress / max(goal.cycles_spent, 1),
            'interruptions': goal.interruptions,
            'time_spent_hours': goal.get_time_spent()
        }

    def visualize_goals(self) -> str:
        """Возвращает текстовое представление целей."""
        lines = []
        lines.append(f"\n{'='*60}")
        lines.append(f"  МНОГОЗАДАЧНОСТЬ: {len(self.get_active_goals())}/{self.max_active_goals} целей активно")
        lines.append(f"{'='*60}")

        # Активные
        active = self.get_active_goals()
        if active:
            lines.append("\n  🔥 АКТИВНЫЕ ЦЕЛИ:")
            for goal in active:
                bar = '█' * int(goal.progress * 20) + '░' * (20 - int(goal.progress * 20))
                lines.append(
                    f"    [{bar}] {goal.title[:30]} ({goal.progress:.0%})"
                )

        # Ожидающие
        pending = [g for g in self.goals.values() if g.state == GoalState.PENDING]
        if pending:
            lines.append("\n  ⏳ ОЖИДАЮЩИЕ:")
            for goal in pending[:3]:
                lines.append(f"    • {goal.title[:40]} (приоритет: {goal.priority})")

        return '\n'.join(lines)

    def to_dict(self) -> dict:
        """Сериализует состояние."""
        return {
            'goals': {k: v.to_dict() for k, v in self.goals.items()},
            'max_active_goals': self.max_active_goals,
            'next_goal_id': self.next_goal_id
        }

    def from_dict(self, data: dict):
        """Десериализует состояние."""
        self.max_active_goals = data.get('max_active_goals', 3)
        self.next_goal_id = data.get('next_goal_id', 1)

        for goal_data in data.get('goals', {}).values():
            goal = Goal.from_dict(goal_data)
            self.goals[goal.id] = goal
