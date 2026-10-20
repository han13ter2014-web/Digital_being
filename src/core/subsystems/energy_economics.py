"""
EnergySubsystem — подсистема энергетики и адаптивных затрат.

Инкапсулирует:
- Энергию агента и её регенерацию
- Адаптивные стоимости действий (ε-greedy адаптация)
- Креативный ε-greedy (стохастическое поведение)
- Забывание (приоритетное, по уверенности и частоте использования)
- Креативные награды/штрафы
"""

import gc
import random
from typing import Dict, List, Optional, Callable


class EnergySubsystem:
    """Подсистема энергетики агента."""

    def __init__(self,
                 starting_energy: float = 150,
                 max_energy: float = 200,
                 regen_per_cycle: float = 5,
                 low_threshold: float = 20,
                 critical_threshold: float = 5,
                 gc_interval: int = 5):

        # max_energy должен быть известен до первой записи в energy:
        # свойство energy клампит значение в [0, max_energy].
        self.max_energy = max_energy
        self._energy = 0.0
        self.energy = starting_energy
        self.regen_per_cycle = regen_per_cycle
        self.low_threshold = low_threshold
        self.critical_threshold = critical_threshold
        self.gc_interval = gc_interval

        # Адаптивные затраты по типам действий
        self._action_costs: Dict[str, int] = {
            "default": 2,
            "hypothesis": 3,
            "decomposition": 4,
            "mental_model": 1,
            "know_answer": 1,
        }

        # Креативность (ε-greedy)
        self._creative_wins = 0
        self._creative_losses = 0
        self.epsilon_greedy = 0.15

        # Забывание
        self._concept_usage_count: Dict[str, int] = {}

    # ============================================================
    # Энергия — инвариант: всегда в [0, max_energy]
    # ============================================================
    @property
    def energy(self) -> float:
        return self._energy

    @energy.setter
    def energy(self, value: float) -> None:
        """Клампит энергию в [0, max_energy].

        Раньше здесь было обычное поле, и агент доходил до -2.34
        (см. docs/BASELINE.md). Отрицательная энергия ломала
        ``is_alive()`` и делала бессмысленными пороги усталости.
        """
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        self._energy = min(float(self.max_energy), max(0.0, numeric))

    def regenerate(self) -> None:
        """Восстанавливает энергию на regen_per_cycle (не выше max)."""
        if self.energy < self.max_energy:
            self.energy = min(self.max_energy,
                              self.energy + self.regen_per_cycle)

    def refill_to(self, target: float = 100) -> None:
        """Восстанавливает энергию до целевого уровня (для восстановления)."""
        self.energy = min(self.max_energy, max(self.energy, target))

    def is_critical(self) -> bool:
        return self.energy < self.critical_threshold

    def is_low(self) -> bool:
        return self.energy < self.low_threshold

    def is_alive(self) -> bool:
        """Жив ли агент по энергии.

        Энергия больше не убивает (см. README: «энергия только замедляет»),
        поэтому 0 — это не смерть, а истощение. Смерть определяется
        max_cycles и внешними причинами.
        """
        return self.energy >= 0

    def is_exhausted(self) -> bool:
        """Энергии нет: агент может только отдыхать и восстанавливаться."""
        return self.energy <= 0

    # ============================================================
    # Адаптивные стоимости действий
    # ============================================================
    def cost_for(self, action_type: str) -> int:
        """Возвращает текущую стоимость действия (для конкретного типа)."""
        return self._action_costs.get(action_type, 2)

    def pay(self, action_type: str = "default") -> int:
        """Списывает энергию за действие. Возвращает списанную сумму.

        Ниже нуля энергия не опускается — клампит свойство ``energy``.
        """
        cost = self.cost_for(action_type)
        self.energy -= cost
        return cost

    def adapt_cost(self, action_type: str, success: bool,
                   rate: float = 0.1) -> None:
        """Адаптирует стоимость действия по результату.
        Успех → повышает (агент готов платить больше).
        Неуспех → снижает (агент избегает)."""
        current = self._action_costs.get(action_type, 2)
        if success:
            new_cost = min(10, int(current * (1 + rate)))
        else:
            new_cost = max(1, int(current * (1 - rate)))
        self._action_costs[action_type] = new_cost

    # ============================================================
    # Креативность (ε-greedy)
    # ============================================================
    def should_be_creative(self, enabled: bool = True) -> bool:
        """Возвращает True если агент сейчас должен действовать случайно."""
        if not enabled:
            return False
        return random.random() < self.epsilon_greedy

    def record_creative_success(self, bonus_energy: int = 3) -> int:
        """Учитывает успех креативного действия. Возвращает бонус (если начислен)."""
        self._creative_wins += 1
        if self._creative_wins >= 5:
            self.energy += bonus_energy * 2
            self._creative_wins = 0
            return bonus_energy * 2
        return 0

    def record_creative_failure(self) -> None:
        """Учитывает неудачу креативного действия.
        Снижает ε при серии неудач."""
        self._creative_losses += 1
        if self._creative_losses >= 3:
            self.epsilon_greedy = max(0.05, self.epsilon_greedy - 0.02)
            self._creative_losses = 0

    # ============================================================
    # Забывание
    # ============================================================
    def track_concept_usage(self, concept: str) -> None:
        """Учитывает использование концепции (для решения о забывании)."""
        self._concept_usage_count[concept] = (
            self._concept_usage_count.get(concept, 0) + 1
        )

    def forget_unused(self,
                      mental_models,
                      min_confidence: float = 0.1,
                      max_forget_pct: int = 20) -> int:
        """Забывает неиспользуемые концепции с низкой уверенностью.
        Возвращает количество забытых."""
        to_remove = []
        for concept_name, node in list(mental_models.concepts.items()):
            if node.confidence < min_confidence:
                usage = self._concept_usage_count.get(concept_name, 0)
                if usage <= 1:
                    to_remove.append(concept_name)

        max_forget = int(len(mental_models.concepts) * max_forget_pct / 100)
        if len(to_remove) > max_forget:
            to_remove = to_remove[:max_forget]

        for name in to_remove:
            del mental_models.concepts[name]
            self._concept_usage_count.pop(name, None)
        return len(to_remove)

    # ============================================================
    # GC
    # ============================================================
    def maybe_gc(self, cycle_count: int) -> bool:
        """Запускает gc.collect() если пришло время. Возвращает True если запущен."""
        if cycle_count > 0 and cycle_count % self.gc_interval == 0:
            gc.collect()
            return True
        return False

    # ============================================================
    # Сериализация
    # ============================================================
    def to_checkpoint_dict(self) -> Dict:
        return {
            "energy": self.energy,
            "_action_costs": dict(self._action_costs),
            "_creative_wins": self._creative_wins,
            "_creative_losses": self._creative_losses,
            "epsilon_greedy": self.epsilon_greedy,
            "_concept_usage_count": dict(self._concept_usage_count),
        }

    def restore_from_checkpoint(self, state: Dict) -> None:
        self.energy = state.get("energy", self.energy)
        self._action_costs.update(state.get("_action_costs", {}))
        self._creative_wins = state.get("_creative_wins", 0)
        self._creative_losses = state.get("_creative_losses", 0)
        self.epsilon_greedy = state.get("epsilon_greedy", 0.15)
        self._concept_usage_count.update(
            state.get("_concept_usage_count", {})
        )