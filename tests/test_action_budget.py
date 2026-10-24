"""Stage 19: unit tests for the core-owned action budget."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from src.core.action_budget import ActionBudget


def make_budget(
    energy: float = 100.0,
    *,
    enabled: bool = True,
    max_energy: float = 200.0,
    min_reserve: float = 5.0,
    max_action_cost: float = 20.0,
    essential_actions: Optional[Tuple[str, ...]] = None,
    cache_size: int = 128,
) -> Tuple[ActionBudget, Dict[str, float]]:
    state: Dict[str, float] = {"energy": float(energy)}

    def get_energy() -> float:
        return state["energy"]

    def set_energy(value: float) -> None:
        state["energy"] = max(0.0, min(float(max_energy), float(value)))

    kwargs: Dict[str, Any] = {
        "max_energy": max_energy,
        "enabled": enabled,
        "min_reserve": min_reserve,
        "max_action_cost": max_action_cost,
        "cache_size": cache_size,
    }
    if essential_actions is not None:
        kwargs["essential_actions"] = essential_actions
    return ActionBudget(get_energy, set_energy, **kwargs), state


def test_disabled_budget_preserves_legacy_spend_without_new_limits() -> None:
    budget, state = make_budget(
        energy=10,
        enabled=False,
        min_reserve=50,
        max_action_cost=2,
    )

    decision = budget.charge("hypothesis", 7)

    assert decision.allowed is True
    assert decision.enabled is False
    assert decision.reason == "disabled"
    assert decision.cost == 7.0
    assert decision.energy_before == 10.0
    assert decision.energy_after == 3.0
    assert state["energy"] == 3.0
    assert decision.capped is False


def test_enabled_budget_denies_below_reserve_without_spending() -> None:
    budget, state = make_budget(energy=7, min_reserve=5)

    decision = budget.charge("hypothesis", 3)

    assert decision.allowed is False
    assert decision.reason == "insufficient_energy"
    assert decision.energy_before == 7.0
    assert decision.energy_after == 7.0
    assert state["energy"] == 7.0
    assert budget.status()["denied"] == 1
    assert budget.status()["spent"] == 0.0


def test_budget_allows_spend_that_lands_exactly_on_reserve() -> None:
    budget, state = make_budget(energy=8, min_reserve=5)

    decision = budget.charge("hypothesis", 3)

    assert decision.allowed is True
    assert decision.reason == "ok"
    assert state["energy"] == 5.0


def test_essential_action_may_go_below_reserve() -> None:
    budget, state = make_budget(energy=2, min_reserve=5)

    decision = budget.charge("deep_rest", 3)

    assert decision.allowed is True
    assert decision.reason == "essential"
    assert decision.energy_after == 0.0
    assert state["energy"] == 0.0


def test_action_cost_is_capped_when_budget_is_enabled() -> None:
    budget, state = make_budget(
        energy=100,
        min_reserve=5,
        max_action_cost=10,
    )

    decision = budget.charge("hypothesis", 50)

    assert decision.allowed is True
    assert decision.cost == 10.0
    assert decision.capped is True
    assert state["energy"] == 90.0


def test_same_action_id_does_not_spend_twice() -> None:
    budget, state = make_budget(energy=100)

    first = budget.charge(
        "delamain_goal",
        4,
        action_id="goal-1-attempt-1",
    )
    second = budget.charge(
        "delamain_goal",
        4,
        action_id="goal-1-attempt-1",
    )
    third = budget.charge(
        "delamain_goal",
        4,
        action_id="goal-1-attempt-2",
    )

    assert first.allowed is True
    assert first.duplicate is False
    assert second.allowed is True
    assert second.duplicate is True
    assert second.cost == 4.0
    assert second.energy_before == 96.0
    assert second.energy_after == 96.0
    assert third.allowed is True
    assert third.duplicate is False
    assert state["energy"] == 92.0


def test_denied_action_id_is_not_cached() -> None:
    budget, state = make_budget(energy=4, min_reserve=5)
    action_id = "goal-2-attempt-1"

    denied = budget.charge("delamain_goal", 2, action_id=action_id)
    state["energy"] = 10.0
    allowed = budget.charge("delamain_goal", 2, action_id=action_id)

    assert denied.allowed is False
    assert allowed.allowed is True
    assert allowed.duplicate is False
    assert state["energy"] == 8.0


def test_invalid_cost_fails_closed_without_spending() -> None:
    budget, state = make_budget(energy=10)

    decision = budget.charge("hypothesis", "not-a-number")  # type: ignore[arg-type]

    assert decision.allowed is False
    assert decision.reason == "invalid_cost"
    assert decision.cost == 0.0
    assert state["energy"] == 10.0


def test_non_finite_cost_fails_closed() -> None:
    budget, state = make_budget(energy=10)

    decision = budget.charge("hypothesis", float("inf"))

    assert decision.allowed is False
    assert decision.reason == "invalid_cost"
    assert state["energy"] == 10.0


def test_zero_cost_is_allowed_below_reserve() -> None:
    budget, state = make_budget(energy=1, min_reserve=5)

    decision = budget.charge("noop", 0)

    assert decision.allowed is True
    assert decision.reason == "zero_cost"
    assert state["energy"] == 1.0


def test_status_reports_policy_and_last_decision() -> None:
    budget, _ = make_budget(
        energy=50,
        min_reserve=7,
        max_action_cost=12,
    )
    budget.charge("hypothesis", 30, action_id="action-1")

    status = budget.status()

    assert status["enabled"] is True
    assert status["min_reserve"] == 7.0
    assert status["max_action_cost"] == 12.0
    assert status["allowed"] == 1
    assert status["denied"] == 0
    assert status["spent"] == 12.0
    assert status["cached_decisions"] == 1
    assert status["last_decision"]["action_id"] == "action-1"
    assert status["last_decision"]["capped"] is True
