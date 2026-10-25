"""Stage 19: Integration of the action budget with DigitalBeing.act()."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pytest

from src.core.action_budget import ActionBudget


class _FakeBeing:
    """Minimal object that satisfies the fields used by DigitalBeing.act()."""

    def __init__(
        self,
        energy: float,
        *,
        enabled: bool = True,
        min_reserve: float = 5.0,
        max_action_cost: float = 20.0,
        essential_actions: Optional[Iterable[str]] = None,
    ) -> None:
        self.energy = float(energy)
        self.cycle_count = 1
        self._action_type_counts: Dict[str, int] = {}
        self._concept_usage_count: Dict[str, int] = {}
        self._action_costs = {
            "default": 2,
            "hypothesis": 3,
            "deep_rest": 2,
            "repair": 4,
        }
        kwargs: Dict[str, Any] = {
            "enabled": enabled,
            "min_reserve": min_reserve,
            "max_action_cost": max_action_cost,
        }
        if essential_actions is not None:
            kwargs["essential_actions"] = essential_actions
        self.action_budget = ActionBudget(
            lambda: self.energy,
            lambda value: setattr(self, "energy", value),
            **kwargs,
        )

    def _get_adaptive_cost(self, action_type: str) -> int:
        return int(self._action_costs.get(action_type, 2))


def test_disabled_budget_preserves_existing_act_spend() -> None:
    from src.core.agent import DigitalBeing

    being = _FakeBeing(
        energy=10,
        enabled=False,
        min_reserve=50,
        max_action_cost=2,
    )

    result = DigitalBeing.act(being, "гипотеза")

    assert result == "Ответ: гипотеза"
    assert being.energy == 7.0


def test_enabled_budget_denies_act_and_keeps_energy() -> None:
    from src.core.agent import DigitalBeing

    being = _FakeBeing(energy=7, min_reserve=5)

    result = DigitalBeing.act(being, "гипотеза")

    assert "Бюджет не разрешает hypothesis" in result
    assert "insufficient_energy" in result
    assert being.energy == 7.0
    assert being._action_type_counts["hypothesis"] == 1
    assert being.action_budget.status()["denied"] == 1


def test_enabled_budget_allows_act_above_reserve() -> None:
    from src.core.agent import DigitalBeing

    being = _FakeBeing(energy=20, min_reserve=5)

    result = DigitalBeing.act(being, "гипотеза")

    assert result == "Ответ: гипотеза"
    assert being.energy == 17.0
    last = being.action_budget.status()["last_decision"]
    assert last["allowed"] is True
    assert last["reason"] == "ok"
    assert last["source"] == "core_act"


def test_essential_action_is_allowed_below_reserve() -> None:
    """Отдых проходит ниже резерва и больше не стоит энергии.

    Раньше отдых был платным (2 единицы) и потому недоступен именно при
    истощении: 243 отказа «too_tired» на 400 попыток в замере. Теперь
    восстановительное действие бесплатно и не блокируется резервом.
    """
    from src.core.agent import DigitalBeing

    being = _FakeBeing(energy=2, min_reserve=5)

    result = DigitalBeing.act(being, "глубокий отдых")

    assert result == "Ответ: глубокий отдых"
    assert being.energy == 2.0
    last = being.action_budget.status()["last_decision"]
    assert last["allowed"] is True
    assert last["reason"] == "zero_cost"


def test_repair_is_allowed_below_reserve() -> None:
    """Служебное действие не блокируется резервом — иначе не починиться."""
    from src.core.agent import DigitalBeing

    class _Integrity:
        def manual_repair(self, intensity: float) -> Dict[str, Any]:
            return {"intensity": intensity}

    class _DeathRisk:
        def __init__(self) -> None:
            self.integrity = _Integrity()

    being = _FakeBeing(energy=2, min_reserve=5)
    being.death_risk = _DeathRisk()

    DigitalBeing.act(being, "repair")

    last = being.action_budget.status()["last_decision"]
    assert last["allowed"] is True
    assert last["reason"] == "essential"


def test_denied_action_does_not_run_side_effect() -> None:
    from src.core.agent import DigitalBeing

    class _Integrity:
        def __init__(self) -> None:
            self.calls = 0

        def manual_repair(self, intensity: float) -> Dict[str, Any]:
            self.calls += 1
            return {"intensity": intensity}

    class _DeathRisk:
        def __init__(self) -> None:
            self.integrity = _Integrity()

    being = _FakeBeing(
        energy=1,
        min_reserve=5,
        essential_actions=(),
    )
    being.death_risk = _DeathRisk()

    result = DigitalBeing.act(being, "repair")

    assert "Бюджет не разрешает repair" in result
    assert being.death_risk.integrity.calls == 0
    assert being.energy == 1.0


def test_digital_being_exposes_default_off_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.agent import DigitalBeing
    from src.core.subsystem_base import PluginRegistry

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DELAMAIN_ENABLED", "0")
    monkeypatch.setenv("DELAMAIN_EFFECTOR_ENABLED", "0")
    PluginRegistry.reset_global()
    agent = None
    try:
        agent = DigitalBeing("BudgetIntegration")
        assert agent.action_budget is not None
        assert agent.action_budget.enabled is False
        status = agent.get_subsystems_status()["action_budget"]
        assert status["enabled"] is False
        assert status["min_reserve"] == 5.0
        assert status["max_action_cost"] == 20.0

        before = agent.energy
        result = agent.act("гипотеза")
        assert result.startswith("Ответ:")
        assert agent.energy < before
    finally:
        if agent is not None:
            agent.plugin_registry.teardown_all()
        PluginRegistry.reset_global()
