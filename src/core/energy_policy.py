"""
EnergyPolicy — новая политика энергии для трей-режима.

Философское изменение: энергия больше НЕ убивает агента.
В старой модели `energy < 0` означало смерть (и крах процесса).
В новой модели энергия определяет **частоту дыхания**:
- 100% энергии → цикл каждые 5 секунд (бодр)
- 50% энергии → цикл каждые 10 секунд (спокойный)
- 10% энергии → цикл каждую минуту (устал)
- < 5% энергии → цикл каждые 5 минут (спит, но не умер)

Смерть теперь — ТОЛЬКО явная:
1. Пользователь закрыл трей (Quit)
2. SelfTermination (защита от жестокости)
3. НЕ от энергии никогда

Сохраняем регенерацию — энергия восстанавливается, и если тише тикали —
быстрее восстанавливаются (отдых полезен).

Использование:
    policy = EnergyPolicy(agent.energy, agent.max_energy)
    delay = policy.current_tick_interval_sec()  # сколько ждать до следующего тика
    policy.regenerate(elapsed_sec)              # восстановить энергию за время простоя
    if policy.is_exhausted():
        await bus.publish(Events.ENERGY_LOW, ...)
"""

import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class EnergyThresholds:
    """Пороги, определяющие поведение."""
    # Энергия → минимальный интервал тика
    FULL_ENERGY_INTERVAL = 5.0       # ≥80% энергии — быстрые циклы
    NORMAL_INTERVAL = 10.0           # ≥50%
    SLOW_INTERVAL = 30.0             # ≥20%
    TIRED_INTERVAL = 60.0            # ≥10%
    EXHAUSTED_INTERVAL = 300.0       # <10% — почти спит

    # Восстановление энергии в секунду простоя
    # (когда тик медленный — агент «отдыхает» и восстанавливается)
    REGEN_PER_SEC_FULL_ENERGY = 0.5     # быстро при 80%+
    REGEN_PER_SEC_NORMAL = 0.3          # при 50-80%
    REGEN_PER_SEC_SLOW = 0.1            # при 20-50%
    REGEN_PER_SEC_TIRED = 0.02          # при 10-20% — еле-еле
    REGEN_PER_SEC_EXHAUSTED = 0.005     # <10% — почти не восстанавливается

    # Когда публиковать ENERGY_LOW
    LOW_THRESHOLD = 20.0
    CRITICAL_THRESHOLD = 5.0

    # Когда публиковать ENERGY_RECOVERED
    RECOVERED_THRESHOLD = 80.0


class EnergyPolicy:
    """Политика «энергия управляет темпом, а не жизнью/смертью»."""

    def __init__(self, get_energy, max_energy: float = 200.0):
        """
        Args:
            get_energy: callable, возвращающий текущую энергию агента.
                        Это функция (а не число), потому что энергия меняется.
            max_energy: максимальная энергия агента (потолок).
        """
        self._get_energy = get_energy
        self._max_energy = float(max_energy)
        # Флаги уведомлений (чтобы не спамить)
        self._low_warned = False           # True после первого LOW-уведомления
        self._critical_warned = False      # True после первого CRITICAL-уведомления
        self._recovered_notified = False   # True после RECOVERED-уведомления
        # Защита от ложного «я восстановился» при старте:
        # уведомляем о recovered только если до этого были LOW/CRITICAL.
        self._has_been_low_before = False

    @property
    def energy(self) -> float:
        """Текущая энергия (через callback)."""
        return self._get_energy()

    @property
    def max_energy(self) -> float:
        return self._max_energy

    @property
    def energy_percent(self) -> float:
        """Энергия в процентах (0..100)."""
        return max(0.0, min(100.0, (self.energy / self._max_energy) * 100))

    def energy_level(self) -> str:
        """Текстовая категория: 'full' / 'normal' / 'slow' / 'tired' / 'exhausted'."""
        pct = self.energy_percent
        if pct >= 80:
            return "full"
        if pct >= 50:
            return "normal"
        if pct >= 20:
            return "slow"
        if pct >= 10:
            return "tired"
        return "exhausted"

    def current_tick_interval_sec(self) -> float:
        """Сколько секунд ждать до следующего тика в зависимости от энергии."""
        level = self.energy_level()
        return {
            "full":      EnergyThresholds.FULL_ENERGY_INTERVAL,
            "normal":    EnergyThresholds.NORMAL_INTERVAL,
            "slow":      EnergyThresholds.SLOW_INTERVAL,
            "tired":     EnergyThresholds.TIRED_INTERVAL,
            "exhausted": EnergyThresholds.EXHAUSTED_INTERVAL,
        }[level]

    def regenerate(self, elapsed_sec: float) -> float:
        """Восстановить энергию за время простоя elapsed_sec.

        Возвращает, сколько энергии фактически добавлено.
        Использует ступенчатую функцию: чем ниже энергия, тем меньше regen.
        Это сделано чтобы избежать «бесконечного буста» при длительном сне:
        уставший агент сначала отдыхает медленно, потом — быстрее.
        """
        if elapsed_sec <= 0:
            return 0.0

        pct = self.energy_percent
        if pct >= 80:
            rate = EnergyThresholds.REGEN_PER_SEC_FULL_ENERGY
        elif pct >= 50:
            rate = EnergyThresholds.REGEN_PER_SEC_NORMAL
        elif pct >= 20:
            rate = EnergyThresholds.REGEN_PER_SEC_SLOW
        elif pct >= 10:
            rate = EnergyThresholds.REGEN_PER_SEC_TIRED
        else:
            rate = EnergyThresholds.REGEN_PER_SEC_EXHAUSTED

        gained = rate * elapsed_sec
        # Не позволяем энергии превысить потолок
        old_energy = self.energy
        new_energy = min(self._max_energy, old_energy + gained)
        actual_gained = new_energy - old_energy

        if actual_gained > 0.01:
            # Записываем обратно через setter (если есть) или callback
            self._set_energy(new_energy)

        # Сбрасываем флаги предупреждений при восстановлении
        if self.energy_percent >= EnergyThresholds.RECOVERED_THRESHOLD:
            if not self._recovered_notified:
                self._recovered_notified = True
            self._low_warned = False
            self._critical_warned = False

        return actual_gained

    def _set_energy(self, value: float) -> None:
        """Записать энергию обратно. По умолчанию — нет setter (только чтение).

        Если у агента есть метод типа `set_energy` — передайте его при инициализации.
        Чтобы не ломать существующий API, используем lambda в AgentRunner.
        """
        if hasattr(self, "_set_energy_cb") and self._set_energy_cb is not None:
            self._set_energy_cb(value)

    def attach_setter(self, setter) -> None:
        """Привязать функцию записи энергии: setter(float) -> None."""
        self._set_energy_cb = setter

    # ============================================================
    # События для шины
    # ============================================================

    def should_publish_low(self) -> bool:
        """True, если только что пересёкли порог LOW (для публикации события)."""
        if self.energy_percent < EnergyThresholds.LOW_THRESHOLD and not self._low_warned:
            self._low_warned = True
            self._has_been_low_before = True
            return True
        return False

    def should_publish_critical(self) -> bool:
        """True, если только что пересёкли порог CRITICAL."""
        if self.energy_percent < EnergyThresholds.CRITICAL_THRESHOLD and not self._critical_warned:
            self._critical_warned = True
            self._has_been_low_before = True
            return True
        return False

    def should_publish_recovered(self) -> bool:
        """True, если только что восстановились после LOW/CRITICAL.

        Уведомляем только если до этого был LOW или CRITICAL — иначе при старте
        агент с полной энергией сразу бы получил «я восстановился» (абсурд).
        """
        if (
            self._has_been_low_before
            and self.energy_percent >= EnergyThresholds.RECOVERED_THRESHOLD
            and not self._recovered_notified
        ):
            self._recovered_notified = True
            return True
        return False

    # ============================================================
    # Диагностика
    # ============================================================

    def get_status(self) -> dict:
        """Полный статус для dashboard / tray."""
        return {
            "energy": round(self.energy, 1),
            "max_energy": self._max_energy,
            "percent": round(self.energy_percent, 1),
            "level": self.energy_level(),
            "tick_interval_sec": self.current_tick_interval_sec(),
            "low_warned": self._low_warned,
            "critical_warned": self._critical_warned,
        }

    def __repr__(self) -> str:
        return (
            f"EnergyPolicy(energy={self.energy:.0f}/{self._max_energy:.0f} "
            f"({self.energy_percent:.0f}%, level={self.energy_level()}, "
            f"tick={self.current_tick_interval_sec():.0f}s))"
        )


# ============================================================
# Backward compatibility: legacy-функция для main.py
# ============================================================

def is_agent_alive_legacy(energy: float, max_cycles: int, cycle_count: int) -> bool:
    """Старая проверка жизнеспособности. Оставлена для CLI-режима.

    В трей-режиме НЕ используется — там AgentRunner не имеет понятия смерти.
    """
    return energy > 0 and cycle_count < max_cycles