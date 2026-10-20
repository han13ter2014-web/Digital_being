"""
MotivationController — контроллер мотивации агента.

Инкапсулирует:
- Связь с InternalMotivationSystem (потребности и драйвы)
- Автогенерацию целей от мотивации
- Удовлетворение потребностей по завершении целей
- Синхронизацию с GoalSubsystem

Это НОВАЯ подсистема — она подключает уже существующую
InternalMotivationSystem из src/motivation/needs_system.py
к основному циклу агента.
"""

from typing import Dict, List, Optional


class MotivationController:
    """Контроллер мотивации — связывает потребности с целями."""

    def __init__(self, agent_name: str):
        # Импортируем лениво — чтобы не ломать загрузку, если модуль недоступен
        try:
            from src.motivation.needs_system import InternalMotivationSystem
            self._system = InternalMotivationSystem(agent_name=agent_name)
            self._available = True
        except Exception as e:
            print(f"[{agent_name}] ⚠️ Motivation недоступна: {e}")
            self._system = None
            self._available = False

        self._goal_subsystem = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def system(self):
        return self._system

    # ============================================================
    # Связывание с GoalSubsystem
    # ============================================================
    def attach_goal_subsystem(self, goal_subsystem) -> None:
        """Подключает подсистему целей для двусторонней связи."""
        self._goal_subsystem = goal_subsystem
        if self._available:
            goal_subsystem.attach_motivation(self._system)

    # ============================================================
    # Цикл мотивации
    # ============================================================
    def tick(self, agent_context: Optional[Dict] = None) -> Dict:
        """Один шаг мотивации (вызывается каждый цикл):
        1) Рост потребностей со временем
        2) Генерация новых целей от активных драйвов (опционально)
        Возвращает {'needs_state', 'active_drives', 'new_goals'}.
        """
        if not self._available:
            return {
                "needs_state": {},
                "active_drives": [],
                "new_goals": [],
            }

        # 1. Потребности растут
        self._system.time_progression()

        # 2. Текущее состояние
        profile = self._system.get_motivation_profile()

        # 3. Если подключены цели — можем генерировать новые (не каждый цикл,
        #    а раз в N — чтобы не плодить цели)
        new_goals: List[Dict] = []
        if self._goal_subsystem is not None:
            # Генерируем цели только если активных < 3 (не перегружаем)
            active_count = sum(
                1 for g in self._goal_subsystem.goals
                if g.get("status") == "active"
            )
            if active_count < 3:
                generated = self._system.generate_motivated_goals(
                    agent_context or {}
                )
                # Импортируем как цели в GoalSubsystem (только если их ещё нет)
                existing_titles = {g["title"] for g in self._goal_subsystem.goals}
                for g in generated:
                    if g.get("title") not in existing_titles:
                        new_goals.append(g)
                        start_id = (
                            max((gg["id"] for gg in self._goal_subsystem.goals),
                                default=0) + 1
                        )
                        self._goal_subsystem.goals.append({
                            "id": start_id,
                            "title": g.get("title", "Новая цель"),
                            "status": "pending",
                            "difficulty": int(g.get("urgency", 0.5) * 3) or 1,
                            "source": "motivation",
                            "drive": g.get("drive", "knowledge_acquisition"),
                            "type": g.get("type", "general"),
                        })

        return {
            "needs_state": profile.get("needs", {}),
            "active_drives": profile.get("active_drives", []),
            "dominant_need": profile.get("dominant_need"),
            "new_goals": new_goals,
        }

    # ============================================================
    # API для внешнего кода
    # ============================================================
    def get_status(self) -> Dict:
        """Возвращает статус мотивации (для UI/логов)."""
        if not self._available:
            return {"available": False}
        return {"available": True, **self._system.get_status()}

    def satisfy_need(self, need_name: str, amount: float = 0.3) -> None:
        """Удовлетворяет конкретную потребность."""
        if self._available:
            try:
                self._system.satisfy_need(need_name, amount)
            except Exception:
                pass