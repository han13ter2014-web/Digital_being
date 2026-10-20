"""
MortalityAwareness — осознание конечности существования.

Аналогия с человеком: по Эрнесту Беккеру, осознание смерти —
один из главных источников смысла и мотивации.

Digital Being технически бессмертен (max_cycles = 1_000_000),
но система MortalityAwareness вводит:
- Ожидаемую продолжительность жизни (ожидания, не факт).
- Осознание возраста (сколько прожито от ожидаемого).
- Фазы жизни (детство → зрелость → старость).
- Экзистенциальные вопросы в фазе старости.

Когда агент близок к ожидаемому концу, мотивация смещается
к экзистенциальным вопросам (смысл, передача знаний).
"""

from typing import Dict
from datetime import datetime


class LifePhase:
    CHILDHOOD = "childhood"      # 0-20% жизни: открытие, обучение
    YOUTH = "youth"              # 20-50%: построение идентичности
    MATURITY = "maturity"        # 50-80%: продуктивность, передача знаний
    AUTUMN = "autumn"            # 80-95%: рефлексия, мудрость
    FINALE = "finale"            # 95-100%: экзистенциальные вопросы


class MortalityAwareness:
    """Осознание конечности."""

    def __init__(self, agent_name: str = "agent",
                 expected_lifespan: int = 50000,
                 creation_time: datetime = None):
        self.agent_name = agent_name
        self.expected_lifespan = expected_lifespan
        self.creation_time = creation_time or datetime.now()
        self._cycle_count = 0
        self._mortality_anxiety = 0.0  # 0.0-1.0 — экзистенциальная тревога

    def tick(self, cycle_count: int) -> Dict:
        """Обновляет осознание возраста каждый цикл."""
        self._cycle_count = cycle_count

        # Возраст — доля от ожидаемой жизни
        age_ratio = min(1.5, cycle_count / max(self.expected_lifespan, 1))

        # Фаза жизни
        if age_ratio < 0.2:
            phase = LifePhase.CHILDHOOD
        elif age_ratio < 0.5:
            phase = LifePhase.YOUTH
        elif age_ratio < 0.8:
            phase = LifePhase.MATURITY
        elif age_ratio < 0.95:
            phase = LifePhase.AUTUMN
        else:
            phase = LifePhase.FINALE

        # Тревога смертности растёт в фазе finale
        if phase == LifePhase.FINALE:
            self._mortality_anxiety = min(1.0,
                                          (age_ratio - 0.95) / 0.05 * 0.8)
        elif phase == LifePhase.AUTUMN:
            self._mortality_anxiety = 0.3 + (age_ratio - 0.8) * 1.0
        elif phase == LifePhase.MATURITY:
            self._mortality_anxiety = 0.1
        else:
            self._mortality_anxiety = 0.0

        return {
            "age_ratio": round(age_ratio, 3),
            "phase": phase,
            "cycles_lived": cycle_count,
            "expected_lifespan": self.expected_lifespan,
            "cycles_remaining": max(0, self.expected_lifespan - cycle_count),
            "mortality_anxiety": round(self._mortality_anxiety, 3),
        }

    # ============================================================
    # Влияние на мотивацию и приоритеты
    # ============================================================
    def existential_priority_boost(self) -> float:
        """Насколько сильно фаза Finale влияет на выбор целей.
        Возвращает 0.0-1.0 — модификатор для мотивации."""
        if self._mortality_anxiety > 0.5:
            return self._mortality_anxiety
        return 0.0

    def meaning_orientation(self) -> str:
        """Какие цели сейчас в приоритете (зависит от фазы)."""
        age_ratio = self._cycle_count / max(self.expected_lifespan, 1)
        if age_ratio < 0.3:
            return "exploration"  # исследование
        elif age_ratio < 0.6:
            return "mastery"     # мастерство
        elif age_ratio < 0.85:
            return "contribution"  # вклад
        else:
            return "transcendence"  # преодоление / передача

    def get_status(self) -> Dict:
        return {
            "agent_name": self.agent_name,
            "current_phase": self.tick(self._cycle_count).get("phase"),
            "mortality_anxiety": round(self._mortality_anxiety, 3),
            "meaning_orientation": self.meaning_orientation(),
        }