"""Одно бюджетное решение на попытку действия.

Модуль не создаёт второй запас энергии, таблицу или очередь. Ресурсом
остаётся существующая энергия агента, а ``ActionBudget`` лишь отвечает на
один вопрос: можно ли списать стоимость действия сейчас и какой будет
остаток.

Границы решения:

* при выключенном флаге бюджет работает как прежнее ``energy -= cost`` и
  ничего не запрещает;
* при включённом флаге обычное действие отклоняется, если после списания
  энергия опустилась бы ниже ``min_reserve``;
* стоимость одного действия ограничена ``max_action_cost``;
* восстановительные действия (``repair``, ``deep_rest``, ``checkpoint_now``)
  не блокируются резервом, иначе существо не смогло бы восстановиться;
* повторное решение с тем же ``action_id`` не списывает энергию второй раз
  (в пределах процесса).

Это политика, а не вторая бухгалтерия: durable-таблицы, отдельного файла и
второй истории здесь нет. Ограничение одного процесса и отсутствие
транзакционной защиты явно описаны в отчёте этапа.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from typing import Any, Callable, Dict, FrozenSet, Iterable, Optional


@dataclass(frozen=True)
class BudgetDecision:
    """Результат одного бюджетного решения."""

    allowed: bool
    action_type: str
    cost: float
    energy_before: float
    energy_after: float
    reason: str
    source: str = "core"
    action_id: Optional[str] = None
    enabled: bool = True
    duplicate: bool = False
    capped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": bool(self.allowed),
            "action_type": self.action_type,
            "cost": float(self.cost),
            "energy_before": float(self.energy_before),
            "energy_after": float(self.energy_after),
            "reason": self.reason,
            "source": self.source,
            "action_id": self.action_id,
            "enabled": bool(self.enabled),
            "duplicate": bool(self.duplicate),
            "capped": bool(self.capped),
        }


class ActionBudget:
    """Единая политика расхода существующей энергии на действие."""

    def __init__(
        self,
        get_energy: Callable[[], float],
        set_energy: Callable[[float], None],
        *,
        max_energy: float = 200.0,
        enabled: bool = False,
        min_reserve: float = 5.0,
        max_action_cost: float = 20.0,
        essential_actions: Iterable[str] = (
            "repair",
            "deep_rest",
            "checkpoint_now",
        ),
        cache_size: int = 128,
    ) -> None:
        if not callable(get_energy):
            raise TypeError("get_energy must be callable")
        if not callable(set_energy):
            raise TypeError("set_energy must be callable")

        self._get_energy = get_energy
        self._set_energy = set_energy
        self.max_energy = max(0.0, float(max_energy))
        self.enabled = bool(enabled)
        self.min_reserve = max(0.0, float(min_reserve))
        self.max_action_cost = max(0.0, float(max_action_cost))
        self.essential_actions: FrozenSet[str] = frozenset(
            str(item) for item in essential_actions
        )
        self._cache_size = max(1, int(cache_size))
        self._approved: "OrderedDict[str, BudgetDecision]" = OrderedDict()
        self._allowed_count = 0
        self._denied_count = 0
        self._spent_total = 0.0
        self._last_decision: Optional[BudgetDecision] = None

    def charge(
        self,
        action_type: str,
        cost: float,
        *,
        source: str = "core",
        action_id: Optional[str] = None,
    ) -> BudgetDecision:
        """Принять решение и, если разрешено, списать энергию.

        Один вызов — одно решение. При выключенной политике метод сохраняет
        прежнее поведение ядра: просто вычитает стоимость с клампом энергии.
        """

        action_type = str(action_type or "default")
        action_id = str(action_id) if action_id else None
        before = self._read_energy()

        try:
            requested_cost = float(cost)
        except (TypeError, ValueError):
            return self._deny(
                action_type=action_type,
                cost=0.0,
                before=before,
                reason="invalid_cost",
                source=source,
                action_id=action_id,
            )
        if not math.isfinite(requested_cost):
            return self._deny(
                action_type=action_type,
                cost=0.0,
                before=before,
                reason="invalid_cost",
                source=source,
                action_id=action_id,
            )
        if requested_cost < 0.0:
            requested_cost = 0.0

        if not self.enabled:
            # Важно: при выключенном флаге не применяем новые лимиты.
            # Это сохраняет прежнее поведение ``self.energy -= cost``.
            return self._spend(
                action_type=action_type,
                cost=requested_cost,
                before=before,
                reason="disabled",
                source=source,
                action_id=action_id,
                enabled=False,
                capped=False,
            )

        capped = requested_cost > self.max_action_cost
        charged_cost = min(requested_cost, self.max_action_cost)

        if action_id and action_id in self._approved:
            previous = self._approved[action_id]
            decision = BudgetDecision(
                allowed=True,
                action_type=action_type,
                cost=previous.cost,
                energy_before=before,
                energy_after=before,
                reason="duplicate",
                source=source,
                action_id=action_id,
                enabled=True,
                duplicate=True,
                capped=previous.capped,
            )
            self._last_decision = decision
            return decision

        if charged_cost <= 0.0:
            decision = BudgetDecision(
                allowed=True,
                action_type=action_type,
                cost=0.0,
                energy_before=before,
                energy_after=before,
                reason="zero_cost",
                source=source,
                action_id=action_id,
                enabled=True,
                capped=capped,
            )
            self._last_decision = decision
            return decision

        if action_type in self.essential_actions:
            return self._spend(
                action_type=action_type,
                cost=charged_cost,
                before=before,
                reason="essential",
                source=source,
                action_id=action_id,
                enabled=True,
                capped=capped,
            )

        required = charged_cost + self.min_reserve
        if before + 1e-9 < required:
            return self._deny(
                action_type=action_type,
                cost=charged_cost,
                before=before,
                reason="insufficient_energy",
                source=source,
                action_id=action_id,
                capped=capped,
            )

        return self._spend(
            action_type=action_type,
            cost=charged_cost,
            before=before,
            reason="ok",
            source=source,
            action_id=action_id,
            enabled=True,
            capped=capped,
        )

    def refund(self, amount: float, *, source: str = "refund") -> BudgetDecision:
        """Вернуть часть списания (например, «урок» права на ошибку).

        Энергия по-прежнему одна: возврат идёт через тот же сеттер
        энергии с клампом в [0, max_energy]. Учёт списаний уменьшается
        на фактически применённую сумму, чтобы статус не расходился
        с энергией. Возврат не кэшируется и не считается «решением
        о списании».
        """
        try:
            requested = float(amount)
        except (TypeError, ValueError):
            requested = 0.0
        if not math.isfinite(requested) or requested < 0.0:
            requested = 0.0
        before = self._read_energy()
        after = max(0.0, min(self.max_energy, before + requested))
        applied = after - before
        if applied > 0.0:
            self._write_energy(after)
            self._spent_total = max(0.0, self._spent_total - applied)
        return BudgetDecision(
            allowed=True,
            action_type="refund",
            cost=applied,
            energy_before=before,
            energy_after=after,
            reason="refund",
            source=source,
        )

    def status(self) -> Dict[str, Any]:
        """Снимок политики без побочных эффектов."""

        return {
            "enabled": bool(self.enabled),
            "min_reserve": float(self.min_reserve),
            "max_action_cost": float(self.max_action_cost),
            "essential_actions": sorted(self.essential_actions),
            "allowed": int(self._allowed_count),
            "denied": int(self._denied_count),
            "spent": round(float(self._spent_total), 6),
            "cached_decisions": len(self._approved),
            "last_decision": (
                self._last_decision.to_dict()
                if self._last_decision is not None
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_energy(self) -> float:
        try:
            return float(self._get_energy())
        except (TypeError, ValueError):
            return 0.0

    def _write_energy(self, value: float) -> None:
        self._set_energy(float(value))

    def _spend(
        self,
        *,
        action_type: str,
        cost: float,
        before: float,
        reason: str,
        source: str,
        action_id: Optional[str],
        enabled: bool,
        capped: bool,
    ) -> BudgetDecision:
        after = max(0.0, min(self.max_energy, before - cost))
        self._write_energy(after)
        self._allowed_count += 1
        self._spent_total += max(0.0, before - after)
        decision = BudgetDecision(
            allowed=True,
            action_type=action_type,
            cost=cost,
            energy_before=before,
            energy_after=after,
            reason=reason,
            source=source,
            action_id=action_id,
            enabled=enabled,
            capped=capped,
        )
        self._last_decision = decision
        if enabled and action_id:
            self._approved[action_id] = decision
            self._approved.move_to_end(action_id)
            while len(self._approved) > self._cache_size:
                self._approved.popitem(last=False)
        return decision

    def _deny(
        self,
        *,
        action_type: str,
        cost: float,
        before: float,
        reason: str,
        source: str,
        action_id: Optional[str],
        capped: bool = False,
    ) -> BudgetDecision:
        # Отказ не кэшируется: после восстановления энергии та же попытка
        # должна получить новое решение, а не старый отказ.
        self._denied_count += 1
        decision = BudgetDecision(
            allowed=False,
            action_type=action_type,
            cost=cost,
            energy_before=before,
            energy_after=before,
            reason=reason,
            source=source,
            action_id=action_id,
            enabled=True,
            capped=capped,
        )
        self._last_decision = decision
        return decision


__all__ = ["ActionBudget", "BudgetDecision"]
