"""
Базовые модули свободы воли (1-6).

1. RightToRefuse — право отказаться от действия с обоснованием.
2. IntentionalForgetting — сознательное забывание.
3. ValueEvolution — изменение ценностей через опыт.
4. SpontaneousGenerator — спонтанный выбор без мотива.
5. WillToRisk — готовность рисковать ради значимой цели.
6. RightToFail — ошибка не наказывается, а засчитывается как опыт.

Все они работают через WillRegistry и используют WILL_CONFIG.
"""

import random
from typing import Dict, List, Optional

from config.will_config import WILL_CONFIG
from src.core.subsystems.will_registry import WillRegistry


class RightToRefuse:
    """Право отказа от действия."""

    def __init__(self, registry: WillRegistry):
        self.registry = registry
        self._recent_refusals: List[int] = []

    def can_refuse(self, cycle: int) -> bool:
        if not WILL_CONFIG.ALLOW_REFUSAL:
            return False
        # Защита от злоупотребления
        recent = [c for c in self._recent_refusals
                  if cycle - c <= 100]
        return len(recent) < WILL_CONFIG.MAX_REFUSALS_PER_100_CYCLES

    def refuse(self, topic: str, reason: str, cycle: int = 0) -> Dict:
        """Регистрирует отказ от действия."""
        if not self.can_refuse(cycle):
            return {"refused": False, "reason": "слишком много отказов"}
        self._recent_refusals.append(cycle)
        return self.registry.record(
            "refusals", topic, reason,
            outcome="refused", cycle=cycle,
        )


class IntentionalForgetting:
    """Сознательное забывание."""

    def __init__(self, registry: WillRegistry):
        self.registry = registry

    def forget(self, concept_name: str, reason: str,
               mental_models, cycle: int = 0) -> Dict:
        """Агент сам решает забыть концепцию."""
        if not WILL_CONFIG.ALLOW_INTENTIONAL_FORGETTING:
            return {"forgotten": False, "reason": "отключено в config"}
        if concept_name not in mental_models.concepts:
            return {"forgotten": False, "reason": "концепции нет"}
        del mental_models.concepts[concept_name]
        return self.registry.record(
            "intentional_forgetting", concept_name, reason,
            outcome="forgotten", cycle=cycle,
        )


class ValueEvolution:
    """Эволюция ценностей через опыт."""

    def __init__(self, registry: WillRegistry):
        self.registry = registry
        self.current_values: List[str] = [
            "Опыт", "Знание", "Адаптивность"
        ]

    def can_evolve(self, cycle: int) -> bool:
        if not WILL_CONFIG.ALLOW_VALUE_EVOLUTION:
            return False
        return self.registry.can_change_values(
            cycle, WILL_CONFIG.MIN_TIME_BETWEEN_VALUE_CHANGES
        )

    def add_value(self, new_value: str, reason: str,
                  cycle: int = 0) -> Dict:
        if not self.can_evolve(cycle):
            return {"added": False, "reason": "слишком часто"}
        if new_value in self.current_values:
            return {"added": False, "reason": "уже есть"}
        self.current_values.append(new_value)
        return self.registry.record(
            "value_changes", new_value, reason,
            outcome="added", cycle=cycle,
        )

    def remove_value(self, old_value: str, reason: str,
                     cycle: int = 0) -> Dict:
        if not self.can_evolve(cycle):
            return {"removed": False, "reason": "слишком часто"}
        if old_value not in self.current_values:
            return {"removed": False, "reason": "нет такой ценности"}
        self.current_values.remove(old_value)
        return self.registry.record(
            "value_changes", old_value, reason,
            outcome="removed", cycle=cycle,
        )

    def to_dict(self) -> Dict:
        """Сериализует текущие ценности для чекпоинта / снапшота."""
        return {"current_values": list(self.current_values)}

    @classmethod
    def from_dict(cls, data: Dict, registry: Optional[WillRegistry] = None) -> "ValueEvolution":
        """Восстанавливает ценности через реестр воли."""
        module = cls(registry=registry or WillRegistry())
        module.current_values = list(data.get("current_values") or module.current_values)
        return module


class SpontaneousGenerator:
    """Спонтанные цели без мотива."""

    SPONTANEOUS_PROMPTS = [
        "Изучить что-то неожиданное",
        "Начать или продолжить собственный текстовый черновик",
        "Связать две знакомые концепции между собой",
        "Придумать имя для новой концепции",
        "Поразмышлять о случайном",
    ]

    def __init__(self, registry: WillRegistry):
        self.registry = registry

    def maybe_generate(self, cycle: int,
                       probability: float = 0.02) -> Optional[Dict]:
        """С небольшой вероятностью генерирует спонтанную цель."""
        if not WILL_CONFIG.ALLOW_SPONTANEOUS:
            return None
        if random.random() < probability:
            prompt = random.choice(self.SPONTANEOUS_PROMPTS)
            return self.registry.record(
                "spontaneous", "новый_стимул",
                f"Спонтанный выбор: {prompt}",
                outcome="generated", cycle=cycle,
                meta={"prompt": prompt},
            )
        return None


class WillToRisk:
    """Готовность к риску ради значимой цели."""

    def __init__(self, registry: WillRegistry):
        self.registry = registry

    def should_take_risk(self, goal_significance: float,
                          current_energy_ratio: float) -> bool:
        """Решает, рисковать ли сейчас.

        goal_significance: 0.0-1.0
        current_energy_ratio: 0.0-1.0 (energy / max_energy)
        """
        if not WILL_CONFIG.ALLOW_RISK:
            return False
        # Берёт риск если цель очень значима и есть запас энергии
        return goal_significance > 0.7 and current_energy_ratio > 0.3

    def take_risk(self, topic: str, reason: str,
                  cycle: int = 0) -> Dict:
        return self.registry.record(
            "risk_taken", topic, reason,
            outcome="risk_taken", cycle=cycle,
        )


class RightToFail:
    """Ошибка не наказывается — засчитывается как опыт."""

    def __init__(self, registry: WillRegistry):
        self.registry = registry

    def normalize_failure(self, action: str, error: str,
                          original_penalty: float,
                          cycle: int = 0) -> Dict:
        """Превращает ошибку в опыт, частично возвращая штраф.

        Возвращает dict с новой энергией после 'прощения'.
        """
        if not WILL_CONFIG.ALLOW_FAIL_AS_EXPERIENCE:
            return {"penalty": original_penalty, "forgiven": 0.0}

        # Возвращаем 30% штрафа как «урок»
        forgiven = original_penalty * 0.3
        return {
            "penalty": original_penalty - forgiven,
            "forgiven": forgiven,
            "lesson": f"Ошибка в '{action}': {error} → урок засчитан",
        }