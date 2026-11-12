"""Длинная совместная проверка тела, арбитра и восстановления состояния."""

from collections import Counter
import math

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent


def _finish(agent):
    registry = getattr(agent, "plugin_registry", None)
    if registry is not None:
        registry.teardown_all()


def test_six_hundred_autonomous_cycles_with_body_limits_and_restarts():
    agent = DigitalBeing(name="BodyArbiterStress")
    agent.web_searcher.toggle(False)
    actions = Counter()
    restarts = 0
    try:
        for step in range(1, 601):
            if step in (201, 401):
                snapshot = build_state_from_agent(agent)
                reborn = DigitalBeing(name="BodyArbiterStressReborn")
                reborn.web_searcher.toggle(False)
                try:
                    apply_state_to_agent(reborn, snapshot)
                    assert reborn.energy == agent.energy
                    assert reborn.interoception.state.atp == agent.interoception.state.atp
                    assert reborn.interoception.state.fatigue == agent.interoception.state.fatigue
                    assert reborn.cycle_count == agent.cycle_count
                finally:
                    _finish(agent)
                agent = reborn
                restarts += 1

            result = agent.autonomous_tick()
            action = (result.get("arbitrator") or {}).get("action")
            if action:
                actions[action] += 1

            state = agent.interoception.state
            assert math.isfinite(agent.energy)
            assert 0.0 <= agent.energy <= agent.energy_subsystem.max_energy
            assert math.isfinite(state.glucose) and state.glucose >= 0.0
            assert math.isfinite(state.atp) and 0.0 <= state.atp <= state.atp_max
            assert math.isfinite(state.fatigue) and 0.0 <= state.fatigue <= 1.0
            assert math.isfinite(state.mitochondrial_health)
            assert 0.0 <= state.mitochondrial_health <= 1.0

        assert restarts == 2
        assert actions["rest"] + actions["deep_rest"] > 0
        assert any(action not in {"rest", "deep_rest"} for action in actions)
        assert len(actions) >= 2
    finally:
        _finish(agent)
