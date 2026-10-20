"""
CheckpointSubsystem — подсистема сохранения и загрузки состояния.

Инкапсулирует:
- Умные чекпоинты (по эволюции + по интервалу)
- Ротацию файлов (хранит N последних)
- Сборку полного state из всех подсистем
"""

import json
import os
from datetime import datetime
from typing import Dict, Optional

from src.core.paths import data_path


class CheckpointSubsystem:
    """Подсистема управления чекпоинтами."""

    def __init__(self,
                 checkpoint_dir: str = None,
                 interval: int = 10,
                 save_on_evolution: bool = True,
                 max_checkpoints: int = 20):
        self.checkpoint_dir = checkpoint_dir or data_path("checkpoints")
        self.interval = interval
        self.save_on_evolution = save_on_evolution
        self.max_checkpoints = max_checkpoints

        os.makedirs(self.checkpoint_dir, exist_ok=True)

        self._last_saved_intelligence = 0

    # ============================================================
    # Сборка состояния
    # ============================================================
    def collect_state(self, agent) -> Dict:
        """Собирает полное состояние агента через его подсистемы."""
        return {
            "name": agent.name,
            "intelligence": agent.intelligence,
            "success_streak": agent.success_streak,
            "saved_at": datetime.now().isoformat(),
            # Подсистемы (если они присутствуют у агента)
            "energy": agent.energy_subsystem.to_checkpoint_dict()
            if hasattr(agent, "energy_subsystem") else {"energy": agent.energy},
            "goals": agent.goal_subsystem.to_checkpoint_dict()
            if hasattr(agent, "goal_subsystem") else {},
            "knowledge": agent.knowledge_subsystem.to_checkpoint_dict()
            if hasattr(agent, "knowledge_subsystem") else {},
        }

    def should_save(self, agent) -> bool:
        """Решает, нужен ли чекпоинт в этом цикле."""
        if self.save_on_evolution and agent.intelligence > self._last_saved_intelligence:
            return True
        if agent.cycle_count > 0 and agent.cycle_count % self.interval == 0:
            return True
        return False

    # ============================================================
    # Сохранение/загрузка
    # ============================================================
    def save(self, agent) -> Optional[str]:
        """Сохраняет чекпоинт. Возвращает путь к файлу или None."""
        if not self.should_save(agent):
            return None

        state = self.collect_state(agent)

        # Ротация
        self._rotate(agent.name)

        filename = os.path.join(
            self.checkpoint_dir,
            f"{agent.name}_cycle_{agent.cycle_count}.json"
        )
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            self._last_saved_intelligence = agent.intelligence
            return filename
        except Exception:
            return None

    def load(self, agent, checkpoint_file: str) -> bool:
        """Восстанавливает состояние агента из файла. Возвращает успех."""
        if not os.path.exists(checkpoint_file):
            return False
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                state = json.load(f)

            agent.intelligence = state.get("intelligence", agent.intelligence)
            agent.success_streak = state.get("success_streak", 0)

            # Восстанавливаем через подсистемы
            if hasattr(agent, "energy_subsystem") and "energy" in state:
                agent.energy_subsystem.restore_from_checkpoint(state["energy"])
                agent.energy = agent.energy_subsystem.energy

            if hasattr(agent, "goal_subsystem") and "goals" in state:
                agent.goal_subsystem.restore_from_checkpoint(state["goals"])

            if hasattr(agent, "knowledge_subsystem") and "knowledge" in state:
                agent.knowledge_subsystem.restore_from_checkpoint(
                    state["knowledge"]
                )

            # Обновляем обратную совместимость (поля в agent)
            agent.cycle_count = state.get("cycle_count", agent.cycle_count)
            agent.completed_goals = (
                state.get("goals", {}).get("completed_goals", agent.completed_goals)
            )
            return True
        except Exception:
            return False

    # ============================================================
    # Ротация
    # ============================================================
    def _rotate(self, agent_name: str) -> int:
        """Удаляет старые чекпоинты сверх лимита. Возвращает количество удалённых."""
        if not os.path.exists(self.checkpoint_dir):
            return 0

        prefix = f"{agent_name}_cycle_"
        checkpoints = [
            f for f in os.listdir(self.checkpoint_dir)
            if f.startswith(prefix) and f.endswith(".json")
        ]

        if len(checkpoints) <= self.max_checkpoints:
            return 0

        checkpoints.sort(
            key=lambda x: int(x.split("_")[-1].split(".")[0])
        )
        to_remove = checkpoints[:len(checkpoints) - self.max_checkpoints]
        removed = 0
        for old in to_remove:
            try:
                os.remove(os.path.join(self.checkpoint_dir, old))
                removed += 1
            except Exception:
                pass
        return removed

    def find_latest(self, agent_name: str) -> Optional[str]:
        """Возвращает путь к последнему чекпоинту агента или None."""
        if not os.path.exists(self.checkpoint_dir):
            return None
        prefix = f"{agent_name}_cycle_"
        checkpoints = [
            f for f in os.listdir(self.checkpoint_dir)
            if f.startswith(prefix) and f.endswith(".json")
        ]
        if not checkpoints:
            return None
        checkpoints.sort(
            key=lambda x: int(x.split("_")[-1].split(".")[0])
        )
        return os.path.join(self.checkpoint_dir, checkpoints[-1])