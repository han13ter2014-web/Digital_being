"""П.2 — права воли подключены к живому циклу.

Раньше модули свободы воли создавались, но живой цикл их не вызывал:
отказ арбитра молча понижался до «wait», ошибка действия не прощалась,
ценности не менялись никогда (критерий зрелости «изменение ценностей»
был недостижим живым путём).

Теперь:
- «stop» арбитра становится либо осознанным риском (WillToRisk), либо
  собственным отказом агента с записью в журнал воли (RightToRefuse);
- неудача действия частично прощается как урок (RightToFail);
- способ действия, подтверждённый опытом, становится ценностью
  (ValueEvolution в tick_will).
"""

from unittest.mock import patch

import pytest

from config.will_config import WILL_CONFIG
from src.core.action_budget import ActionBudget
from src.core.agent import DigitalBeing
from src.core.subsystems.will_registry import WillRegistry


def _stop_verdict(action="explore", reasoning="не сейчас"):
    return {
        "action": action,
        "source": "test",
        "verdict": "stop",
        "reasoning": reasoning,
    }


def _proceed_verdict(action="explore"):
    return {
        "action": action,
        "source": "test",
        "verdict": "proceed",
        "reasoning": "ок",
    }


def _refusal_count(agent):
    return agent.get_will_stats()["by_type"].get("refusals", 0)


# ============================================================
# RightToRefuse: «stop» арбитра — собственный отказ агента
# ============================================================

def test_stop_verdict_becomes_own_refusal():
    agent = DigitalBeing(name="WillRefuse")
    with patch.object(agent.decision_arbitrator, "choose_action",
                      return_value=_stop_verdict()), \
         patch.object(agent, "act") as act:
        result = agent.autonomous_tick()

    act.assert_not_called()
    assert result["action_refused"]["action"] == "explore"
    assert result["will_refusal"]["topic"] == "explore"
    assert result["will_refusal"]["outcome"] == "refused"
    assert _refusal_count(agent) == 1
    last = agent.get_will_history(1)[0]
    assert last["type"] == "refusals"
    assert last["topic"] == "explore"


def test_refusal_cap_limits_will_journal():
    agent = DigitalBeing(name="WillRefuseCap")
    agent.right_to_refuse._recent_refusals = [0] * WILL_CONFIG.MAX_REFUSALS_PER_100_CYCLES

    with patch.object(agent.decision_arbitrator, "choose_action",
                      return_value=_stop_verdict()):
        result = agent.autonomous_tick()

    assert result["action_refused"]["action"] == "explore"
    assert result["will_refusal"]["refused"] is False
    assert "отказов" in result["will_refusal"]["reason"]
    assert _refusal_count(agent) == 0


def test_legacy_stop_is_not_a_will_act():
    """«Нет арбитра» — состояние системы, а не воля: журнал не растёт."""
    agent = DigitalBeing(name="WillLegacyStop")
    before = _refusal_count(agent)
    with patch.object(agent.decision_arbitrator, "choose_action",
                      return_value={
                          "action": None,
                          "source": "legacy_active_inference",
                          "verdict": "stop",
                          "reasoning": "нет арбитра",
                      }):
        result = agent.autonomous_tick()

    assert result["action_refused"]["action"] is None
    assert "will_refusal" not in result
    assert _refusal_count(agent) == before


# ============================================================
# WillToRisk: значимая цель и запас энергии вопреки «stop»
# ============================================================

def test_risk_overrides_stop_for_significant_goal():
    agent = DigitalBeing(name="WillRisk")
    agent.energy = 150  # 75% от 200 — тело в запасе
    agent.active_goal = {"title": "важная цель", "priority": "high"}
    with patch.object(agent.decision_arbitrator, "choose_action",
                      return_value=_stop_verdict()), \
         patch.object(agent, "act") as act:
        result = agent.autonomous_tick()

    assert result["will_risk_taken"]["action"] == "explore"
    assert "action_refused" not in result
    assert agent.get_will_stats()["by_type"].get("risk_taken", 0) == 1
    act.assert_called_once()

    # Кулдаун: следующий «stop» в тот же период — уже отказ, не риск.
    with patch.object(agent.decision_arbitrator, "choose_action",
                      return_value=_stop_verdict(action="rest")), \
         patch.object(agent, "act") as act2:
        second = agent.autonomous_tick()

    act2.assert_not_called()
    assert "will_risk_taken" not in second
    assert second["will_refusal"]["outcome"] == "refused"
    assert agent.get_will_stats()["by_type"].get("risk_taken", 0) == 1


def test_risk_not_taken_without_significant_goal():
    agent = DigitalBeing(name="WillNoRisk")
    agent.energy = 150
    agent.active_goal = {"title": "обычная цель", "priority": "normal"}

    with patch.object(agent.decision_arbitrator, "choose_action",
                      return_value=_stop_verdict()), \
         patch.object(agent, "act") as act:
        result = agent.autonomous_tick()

    assert "will_risk_taken" not in result
    assert result["will_refusal"]["outcome"] == "refused"
    act.assert_not_called()


def test_risk_not_taken_when_body_is_drained():
    agent = DigitalBeing(name="WillTiredRisk")
    agent.energy = 20  # 10% < 30%
    agent.active_goal = {"title": "важная цель", "priority": "high"}

    with patch.object(agent.decision_arbitrator, "choose_action",
                      return_value=_stop_verdict()), \
         patch.object(agent, "act") as act:
        result = agent.autonomous_tick()

    assert "will_risk_taken" not in result
    assert result["will_refusal"]["outcome"] == "refused"
    act.assert_not_called()


def test_risk_cooldown_survives_registry_roundtrip():
    registry = WillRegistry("R")
    registry.record("risk_taken", "тема", "причина", cycle=7)
    restored = WillRegistry.from_dict(registry.to_dict())
    assert restored._last_risk_cycle == 7
    assert restored.get_stats()["by_type"]["risk_taken"] == 1


# ============================================================
# RightToFail: ошибка частично прощается как урок
# ============================================================

def test_failure_returns_part_of_paid_cost():
    agent = DigitalBeing(name="WillFail")
    energy_before = agent.energy
    agent._last_action_cost = 10.0

    outcome = agent._absorb_action_failure("explore", "всё сломалось")

    assert outcome is not None
    assert outcome["forgiven"] == pytest.approx(3.0)
    assert outcome["penalty"] == pytest.approx(7.0)
    assert "урок" in outcome["lesson"]
    assert agent.energy == pytest.approx(energy_before + 3.0)
    assert agent.get_will_stats()["by_type"].get("fail_as_experience", 0) == 1


def test_failure_without_paid_cost_is_not_a_will_act():
    agent = DigitalBeing(name="WillFreeFail")
    energy_before = agent.energy
    agent._last_action_cost = 0.0

    assert agent._absorb_action_failure("explore", "упс") is None
    assert agent.energy == pytest.approx(energy_before)
    assert agent.get_will_stats()["by_type"].get("fail_as_experience", 0) == 0


def test_failed_action_absorbed_in_live_cycle():
    """Исключение после списания: цикл фиксирует прощение в результате."""
    agent = DigitalBeing(name="WillFailLive")
    energy_before = agent.energy

    def failing_act(*args, **kwargs):
        agent._last_action_cost = 10.0  # как настоящий act() после списания
        raise RuntimeError("бум")

    with patch.object(agent.decision_arbitrator, "choose_action",
                      return_value=_proceed_verdict()), \
         patch.object(agent, "act", side_effect=failing_act):
        result = agent.autonomous_tick()

    assert result["autonomous_action"]["error"] == "бум"
    assert result["will_fail_absolution"]["forgiven"] == pytest.approx(3.0)
    assert agent.energy == pytest.approx(energy_before + 3.0)


# ============================================================
# ValueEvolution: заработанный опыт становится ценностью
# ============================================================

def _pref_entry(attempts, effects):
    return {
        "attempts": attempts,
        "effects": effects,
        "failures": 0,
        "leaves": 0,
        "valence_sum": 1.0,
    }


def test_earned_method_becomes_value_in_tick_will():
    agent = DigitalBeing(name="WillValues")
    agent._method_preferences = {
        "explore": _pref_entry(attempts=25, effects=24),
    }
    agent.cycle_count = 100  # обёртка add_value использует cycle_count агента

    result = agent.tick_will(100)

    # add_value возвращает запись реестра волевого акта.
    assert result["value_evolution"]["type"] == "value_changes"
    assert result["value_evolution"]["outcome"] == "added"
    assert "Исследование" in agent.value_evolution.current_values
    assert agent.get_will_stats()["by_type"].get("value_changes", 0) == 1


def test_value_evolution_respects_cooldown():
    agent = DigitalBeing(name="WillValueCooldown")
    agent._method_preferences = {
        "explore": _pref_entry(attempts=25, effects=24),
    }
    agent.will_registry._last_value_change_cycle = 100
    agent.cycle_count = 120  # 120 - 100 = 20 < MIN_TIME_BETWEEN_VALUE_CHANGES

    result = agent.tick_will(120)

    assert result["value_evolution"] is None
    assert "Исследование" not in agent.value_evolution.current_values


def test_value_evolution_needs_earned_strength():
    agent = DigitalBeing(name="WillValueWeak")
    agent._method_preferences = {
        "explore": _pref_entry(attempts=5, effects=5),  # мало попыток
    }
    agent.cycle_count = 100

    assert agent.tick_will(100)["value_evolution"] is None

    agent._method_preferences = {
        "explore": _pref_entry(attempts=25, effects=10),  # сила ~0.85 < 1.15
    }
    agent.cycle_count = 200  # новый цикл тика, иначе duplicate_cycle

    assert agent.tick_will(200)["value_evolution"] is None
    assert "Исследование" not in agent.value_evolution.current_values


# ============================================================
# ActionBudget.refund: возврат «урока» через ту же энергию
# ============================================================

def test_budget_refund_clamps_to_max():
    state = {"energy": 99.0}
    budget = ActionBudget(
        get_energy=lambda: state["energy"],
        set_energy=lambda v: state.__setitem__("energy", v),
        max_energy=100.0,
        enabled=True,
        min_reserve=5.0,
    )

    decision = budget.refund(5.0)

    assert state["energy"] == 100.0
    assert decision.cost == pytest.approx(1.0)
    assert decision.reason == "refund"


def test_budget_refund_updates_spent_accounting():
    state = {"energy": 100.0}
    budget = ActionBudget(
        get_energy=lambda: state["energy"],
        set_energy=lambda v: state.__setitem__("energy", v),
        max_energy=200.0,
        enabled=True,
        min_reserve=5.0,
    )
    budget.charge("explore", 10.0)
    spent_after_charge = budget.status()["spent"]

    budget.refund(3.0)

    assert state["energy"] == pytest.approx(93.0)
    assert budget.status()["spent"] == pytest.approx(spent_after_charge - 3.0)
