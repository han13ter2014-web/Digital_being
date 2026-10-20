"""
EmbodimentController — связь между «телом» (вычислительные ресурсы) и разумом.

Аналогия с человеком: интерoцепция — ощущение собственного тела.
Когда человек устал, голоден, у него болит — это влияет на все решения.

В Digital Being «тело» — это:
- Энергия (compute budget)
- Циклы (прожитое время)
- Когнитивная нагрузка (количество активных концепций)
- Время с последнего «отдыха» (sleep)

EmbodimentLayer переводит эти сигналы в эмоциональное состояние,
которое влияет на креативность, скорость обучения, мотивацию.
"""

from typing import Dict, Optional


class EmbodimentController:
    """Контроллер телесности — интерoцепция цифровой жизни."""

    def __init__(self,
                 energy_subsystem=None,
                 cycle_count: int = 0,
                 cognitive_load_limit: int = 1000):
        self.energy_subsystem = energy_subsystem
        self.cycle_count = cycle_count
        self.cognitive_load_limit = cognitive_load_limit
        self._cycles_since_rest = 0

        # Текущие телесные сигналы
        self.fatigue = 0.0  # 0.0-1.0 (растёт с энергией)
        self.hunger = 0.0  # метафора: нехватка данных
        self.pain = 0.0  # боль: ошибки/противоречия
        self.last_felt_state = "balanced"

    def attach_energy(self, energy_subsystem) -> None:
        self.energy_subsystem = energy_subsystem

    def tick(self, cycle_count: int) -> Dict:
        """Обновляет телесные ощущения каждый цикл."""
        self.cycle_count = cycle_count
        self._cycles_since_rest += 1

        # Усталость: высокая при низкой энергии
        if self.energy_subsystem:
            energy_ratio = self.energy_subsystem.energy / max(
                self.energy_subsystem.max_energy, 1
            )
            self.fatigue = max(0.0, 1.0 - energy_ratio)

        # Голод: после длительного бездействия (нет новых концепций)
        # (упрощённо — линейно растёт со временем без отдыха)
        self.hunger = min(1.0, self._cycles_since_rest / 1000.0)

        # Определяем общее состояние
        if self.fatigue > 0.7:
            state = "exhausted"
        elif self.fatigue > 0.4:
            state = "tired"
        elif self.hunger > 0.6:
            state = "understimulated"
        else:
            state = "balanced"

        self.last_felt_state = state
        return self.get_signals()

    def feel_pain(self, intensity: float = 0.5) -> None:
        """Регистрирует «боль» — ошибку или противоречие."""
        self.pain = min(1.0, self.pain + intensity)

    def rest(self, recovery_amount: float = 0.3) -> None:
        """Отдых — снимает усталость."""
        self.fatigue = max(0.0, self.fatigue - recovery_amount)
        self._cycles_since_rest = 0
        self.pain = max(0.0, self.pain - recovery_amount * 0.5)

    # ============================================================
    # Сигналы, влияющие на другие подсистемы
    # ============================================================
    def creativity_modifier(self) -> float:
        """Возвращает модификатор креативности.
        Усталость снижает ε, лёгкий голод — повышает."""
        if self.fatigue > 0.7:
            return -0.05  # усталый — менее креативный
        elif self.hunger > 0.5:
            return 0.05  # голодный — более креативный (хочет нового)
        return 0.0

    def energy_cost_modifier(self) -> float:
        """Модификатор затрат энергии (усталость → больше тратится)."""
        return 1.0 + self.fatigue * 0.5

    def get_signals(self) -> Dict:
        """Возвращает текущие телесные сигналы (для других подсистем)."""
        return {
            "fatigue": round(self.fatigue, 3),
            "hunger": round(self.hunger, 3),
            "pain": round(self.pain, 3),
            "state": self.last_felt_state,
            "cycles_since_rest": self._cycles_since_rest,
            "creativity_modifier": round(self.creativity_modifier(), 3),
            "energy_cost_modifier": round(self.energy_cost_modifier(), 3),
        }