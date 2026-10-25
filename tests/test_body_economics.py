"""Телесная экономика: отдых доступен, когда он нужен, и возвращает ресурс.

До этой правки истощённый агент не мог выйти из нуля:

* ``act()`` отклонял действия по усталости **до** обработчика, и отдых
  попадал под тот же запрет;
* отдых стоил энергии (2 единицы), то есть был недоступен именно при
  нуле;
* пассивная регенерация ниже 20 % — 0.1 за цикл при стоимости действия
  2–4, поэтому баланс всегда отрицательный;
* ветка «тело просит отдых» читала ``_interoception_status``, который
  никто не выставлял, — отдых не предлагался вовсе;
* запасным вариантом выхода из тупика был ``think_decompose``, который
  тоже отклонялся.

Замер до правки (40 циклов, старт с энергии 0): энергия 0.0 на всех
циклах, 80 отказов ``too_tired``, выбор застывал на ``think_decompose``.
После: энергия 0 → 21.7 → … → 192.7, отказов 0, затем обычная работа.
"""

import pytest

from src.core.agent import ESSENTIAL_ACTIONS, RECOVERY_ACTIONS, DigitalBeing
from src.core.loop_closure import LoopCloser
from src.core.world_delta import WorldSignature


@pytest.fixture()
def agent():
    a = DigitalBeing(name="BodyAgent")
    searcher = getattr(a, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)  # тесты не ходят в сеть
    return a


# ============================================================
# 1. Отдых бесплатен и всегда доступен
# ============================================================


def test_recovery_actions_are_free():
    fresh = DigitalBeing(name="BodyCost")
    try:
        assert fresh._get_adaptive_cost("rest") == 0
        assert fresh._get_adaptive_cost("deep_rest") == 0
        # Обычная работа по-прежнему стоит энергии.
        assert fresh._get_adaptive_cost("explore") > 0
    finally:
        fresh.plugin_registry.teardown_all()


def test_essential_actions_include_recovery():
    assert RECOVERY_ACTIONS == frozenset({"rest", "deep_rest"})
    assert RECOVERY_ACTIONS <= ESSENTIAL_ACTIONS
    assert {"repair", "checkpoint_now"} <= ESSENTIAL_ACTIONS


def test_rest_is_available_at_zero_energy(agent):
    agent.energy = 0.0

    assert agent._is_action_available("deep_rest") is True
    assert agent._is_action_available("rest") is True


def test_work_is_not_offered_without_energy(agent):
    """Действие, на которое нет энергии, — пустой цикл, а не выбор."""
    agent.energy = 0.0

    assert agent._is_action_available("explore") is False
    assert agent._is_action_available("synthesize") is False


def test_work_becomes_available_after_rest(agent):
    agent.energy = 0.0
    assert agent._is_action_available("explore") is False

    agent.act("deep_rest")

    assert agent.energy > 0
    assert agent._is_action_available("explore") is True


# ============================================================
# 2. Отдых возвращает ресурс
# ============================================================


def test_deep_rest_restores_energy(agent):
    agent.energy = 0.0

    result = agent.act("deep_rest")

    assert agent.energy > 0
    assert "восстановил" in result


def test_rest_restores_less_than_deep_rest(agent):
    agent.energy = 0.0
    agent.act("rest")
    shallow = agent.energy

    agent.energy = 0.0
    agent.act("deep_rest")
    deep = agent.energy

    assert 0 < shallow < deep


def test_rest_does_not_exceed_max_energy(agent):
    from config.simulation_config import LR_CONFIG

    agent.energy = float(LR_CONFIG.ENERGY_MAX) - 1.0
    agent.act("deep_rest")

    assert agent.energy <= float(LR_CONFIG.ENERGY_MAX)


# ============================================================
# 3. Истощённый агент выбирает отдых, а не отказ
# ============================================================


def test_exhausted_agent_rests_instead_of_being_denied(agent):
    agent.energy = 0.0
    agent.interoception.state.fatigue = 0.9

    result = agent.autonomous_tick()

    chosen = (result.get("arbitrator") or {}).get("action")
    assert chosen in {"deep_rest", "rest"}, result.get("arbitrator")
    assert agent.energy > 0
    # Никаких отказов: арбитру не предлагали невозможное.
    assert agent.loop_closer.denied_streak("deep_rest") == 0


def test_body_needs_rest_by_energy(agent):
    agent.energy = 0.0
    assert agent._body_needs_rest() is True

    agent.energy = float(agent.energy_subsystem.max_energy)
    agent.interoception.state.fatigue = 0.0
    assert agent._body_needs_rest() is False


def test_body_needs_rest_by_fatigue(agent):
    agent.interoception.state.fatigue = 0.95
    assert agent._body_needs_rest() is True


# ============================================================
# 4. После отдыха очередь действий оживает
# ============================================================


def test_queue_revives_after_rest(agent):
    """Из нуля агент выходит отдыхом и снова начинает действовать.

    Это главная проверка: раньше цикл замыкался на «слишком устал» и
    энергия оставалась 0.0 навсегда. Отдых длится, пока тело не
    восстановится (гистерезис), поэтому циклов нужно больше, чем один
    «порог усталости».
    """
    agent.energy = 0.0
    agent.interoception.state.fatigue = 0.9
    agent.interoception.state.atp = 0.0
    agent.interoception.state.glucose = 0.0

    actions = []
    for _ in range(80):
        result = agent.autonomous_tick()
        chosen = (result.get("arbitrator") or {}).get("action")
        if chosen:
            actions.append(chosen)

    assert actions[0] in {"deep_rest", "rest"}, actions[:5]
    # Работа вернулась: среди выборов есть не только отдых.
    assert any(a not in {"deep_rest", "rest"} for a in actions), actions
    assert agent.energy > 0
    assert agent.interoception.state.fatigue < 0.6


# ============================================================
# 5. Отказ перестаёт быть правдой, когда ресурс вернулся
# ============================================================


def test_denied_action_is_released_when_affordable(agent):
    agent.energy = 0.0
    agent.act("explore")
    assert agent.loop_closer.denied_streak("explore") == 1
    assert agent.loop_closer.is_stuck("explore") is True

    agent.act("deep_rest")  # энергия вернулась

    agent._release_recovered_denials()
    assert agent.loop_closer.denied_streak("explore") == 0
    assert agent.loop_closer.is_stuck("explore") is False


def test_denial_stays_while_body_is_empty(agent):
    agent.energy = 0.0
    agent.act("explore")

    agent._release_recovered_denials()

    assert agent.loop_closer.denied_streak("explore") == 1


def test_reset_denial_keeps_no_effect_counter():
    """Снятие отказа не должно стирать «нет эффекта» — это разные факты."""
    closer = LoopCloser(max_no_effect=3)
    empty = WorldSignature()
    closer.observe("explore", empty, empty)
    closer.observe("explore", empty, empty, reason="denied:too_tired")

    closer.reset_denial("explore")

    assert closer.denied_streak("explore") == 0
    assert closer.no_effect_streak("explore") == 2


def test_denial_survives_checkpoint():
    closer = LoopCloser()
    closer.observe("explore", WorldSignature(), WorldSignature(), reason="denied:too_tired")

    restored = LoopCloser()
    restored.restore_from_checkpoint(closer.to_checkpoint_dict())

    assert restored.denied_streak("explore") == 1
    assert restored.is_stuck("explore") is True


# ============================================================
# 6. Тело живёт от действий, а не от времени
# ============================================================


def test_work_accumulates_fatigue_through_act(agent):
    """Каждое действие — такт тела: работа утомляет по-настоящему."""
    assert agent.interoception.state.fatigue == 0.0

    for _ in range(40):
        agent.energy = float(agent.energy_subsystem.max_energy)
        agent.act("explore")

    assert agent.interoception.state.fatigue > 0.5
    assert agent.interoception.state.atp < agent.interoception.state.atp_max * 0.4


def test_rest_reduces_fatigue_through_act(agent):
    state = agent.interoception.state
    state.fatigue = 0.8
    state.atp = 0.0
    state.glucose = 0.0

    for _ in range(20):
        agent.energy = 100.0
        agent.act("deep_rest")

    assert state.fatigue < 0.5
    assert state.atp > 0.5


def test_denied_action_ages_body_less_than_work(agent):
    """Отказ — не работа: тело живёт такт, но почти не тратит ресурс."""
    agent.energy = 0.0
    agent.act("explore")  # отказ по усталости
    denied_atp = agent.interoception.state.atp

    agent2 = DigitalBeing(name="BodyAgentWork")
    try:
        agent2.energy = float(agent2.energy_subsystem.max_energy)
        agent2.act("explore")
        work_atp = agent2.interoception.state.atp
    finally:
        agent2.plugin_registry.teardown_all()

    assert denied_atp > work_atp


def test_rest_mode_has_hysteresis(agent):
    """Отдых не прекращается на самом пороге усталости."""
    agent.energy = 100.0
    agent.interoception.state.fatigue = 0.7

    assert agent._update_rest_mode() is True

    # Усталость упала чуть ниже порога, но АТФ ещё не восстановлен.
    agent.interoception.state.fatigue = 0.5
    agent.interoception.state.atp = 1.0
    assert agent._update_rest_mode() is True

    # Восстановлено и то, и другое — можно работать.
    agent.interoception.state.fatigue = 0.2
    agent.interoception.state.atp = agent.interoception.state.atp_max
    assert agent._update_rest_mode() is False


def test_rest_choice_appears_when_tired(agent):
    agent.energy = 100.0
    agent.interoception.state.fatigue = 0.8
    agent.interoception.state.atp = 0.0

    result = agent.autonomous_tick()
    chosen = (result.get("arbitrator") or {}).get("action")

    assert chosen in {"deep_rest", "rest"}, result.get("arbitrator")


def test_checkpoint_restore_does_not_age_body(agent):
    """Загрузка чекпоинта не должна тратить глюкозу и АТФ."""
    from src.core.checkpoint_serializer import (
        apply_state_to_agent,
        build_state_from_agent,
    )

    state = agent.interoception.state
    state.glucose = 4.0
    state.atp = 3.0
    state.fatigue = 0.5

    snapshot = build_state_from_agent(agent)

    reborn = DigitalBeing(name="BodyAgentReborn")
    try:
        reborn.web_searcher.toggle(False)
        apply_state_to_agent(reborn, snapshot)
        restored = reborn.interoception.state
        assert restored.glucose == pytest.approx(4.0, abs=1e-6)
        assert restored.atp == pytest.approx(3.0, abs=1e-6)
        assert restored.fatigue == pytest.approx(0.5, abs=1e-6)
        # Производные величины пересчитаны, а не взяты из файла.
        assert restored.action_cost_multiplier == pytest.approx(2.5, abs=0.01)
    finally:
        reborn.plugin_registry.teardown_all()
