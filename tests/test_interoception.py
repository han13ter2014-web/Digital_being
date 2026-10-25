"""Интероцептивная модель: работа утомляет, отдых восстанавливает.

До калибровки модель была односторонней и не связанной с действиями:

* ``step()`` вызывался только из отдыха и восстановления чекпоинта, так
  что усталость не росла от работы (замер: 20 рабочих циклов → fatigue 0);
* глюкоза убывала всегда (приход только от ``food_intake``, которого никто
  не подавал), поэтому даже полный покой через 60 тактов давал fatigue 1.0;
* из полного истощения не было выхода: при нулевой глюкозе производство
  АТФ невозможно, и отдых не восстанавливал ничего.

Теперь у тела есть баланс: работа тратит глюкозу и АТФ, отдых возвращает
глюкозу и повышает эффективность производства, усталость следует за
нехваткой АТФ относительно комфортного уровня.
"""

import pytest

from src.core.interoception import InteroceptiveModel


class _FakeAgent:
    cycle_count = 0


def _model() -> InteroceptiveModel:
    return InteroceptiveModel(_FakeAgent())


# ============================================================
# 1. Работа утомляет, покой — нет
# ============================================================


def test_rest_does_not_tire():
    """Сытое тело в покое не устаёт, даже если ничего не делает."""
    model = _model()

    for _ in range(60):
        model.step(dt=1.0, cognitive_load=0.0)

    assert model.state.fatigue < 0.1
    assert model.state.atp > model.state.atp_max * 0.9


def test_work_tires():
    model = _model()

    for _ in range(40):
        model.step(dt=1.0, cognitive_load=1.0)

    assert model.state.fatigue > 0.6
    assert model.state.atp < model.state.atp_max * 0.3


def test_cognitive_load_drives_fatigue():
    """Чем тяжелее работа, тем быстрее усталость — это не таймер."""
    easy = _model()
    hard = _model()

    for _ in range(20):
        easy.step(dt=1.0, cognitive_load=0.2)
        hard.step(dt=1.0, cognitive_load=1.0)

    assert hard.state.fatigue > easy.state.fatigue
    assert hard.state.atp < easy.state.atp


def test_idle_drains_slowly_not_catastrophically():
    """Бездействие не должно убивать: глюкоза убывает медленно."""
    model = _model()

    for _ in range(60):
        model.step(dt=1.0, cognitive_load=0.0)

    assert model.state.glucose > 0


# ============================================================
# 2. Отдых восстанавливает
# ============================================================


def test_rest_recovers_after_work():
    model = _model()

    for _ in range(45):
        model.step(dt=1.0, cognitive_load=1.0)
    assert model.state.fatigue > 0.6

    for _ in range(45):
        model.step(dt=1.0, cognitive_load=0.0, rest_depth=1.0)

    assert model.state.fatigue < 0.3
    assert model.state.atp > model.state.atp_max * 0.75
    assert model.state.glucose > model.state.glucose_max * 0.9


def test_rest_refills_glucose():
    model = _model()
    model.state.glucose = 0.0
    model.state.atp = 0.0

    for _ in range(15):
        model.step(dt=1.0, rest_depth=1.0)

    assert model.state.glucose > 5.0
    assert model.state.atp > 1.0


def test_deep_rest_recovers_faster_than_shallow():
    deep = _model()
    shallow = _model()
    for m in (deep, shallow):
        m.state.glucose = 0.0
        m.state.atp = 0.0
        m.state.fatigue = 0.9

    for _ in range(20):
        deep.step(dt=1.0, rest_depth=1.0)
        shallow.step(dt=1.0, rest_depth=0.3)

    assert deep.state.glucose > shallow.state.glucose
    assert deep.state.atp > shallow.state.atp
    assert deep.state.fatigue < shallow.state.fatigue


# ============================================================
# 3. Усталость как сигнал, а не как счётчик времени
# ============================================================


def test_fatigue_starts_below_comfort_level():
    """Пока АТФ выше комфортного уровня, усталости нет."""
    model = _model()
    model.state.fatigue = 0.0

    model.step(dt=1.0, cognitive_load=0.0)

    assert model.state.fatigue == pytest.approx(0.0, abs=1e-6)


def test_throughput_falls_with_fatigue():
    model = _model()
    model.state.fatigue = 0.8
    model._refresh_derived()

    assert model.state.cognitive_throughput < 0.5
    assert model.state.action_cost_multiplier > 3.0


def test_energy_cost_multiplier_scales_with_fatigue():
    fresh = _model()
    fresh._refresh_derived()
    tired = _model()
    tired.state.fatigue = 1.0
    tired._refresh_derived()

    assert fresh.get_action_cost(2.0) == pytest.approx(2.0)
    assert tired.get_action_cost(2.0) == pytest.approx(8.0)


# ============================================================
# 4. Прогноз не расходится с реальностью
# ============================================================


def test_predicted_trajectory_matches_step():
    """Прогноз считается теми же уравнениями, что и step()."""
    model = _model()

    model.step(dt=1.0, cognitive_load=0.8)
    predicted_fatigue = list(model.predicted_fatigue_trajectory)

    actual = _model()
    actual.glucose_to_atp_efficiency = model.glucose_to_atp_efficiency
    actual.atp_to_fatigue_sensitivity = model.atp_to_fatigue_sensitivity
    actual.state.glucose = model.state.glucose
    actual.state.atp = model.state.atp
    actual.state.fatigue = model.state.fatigue
    for _ in range(model.predicted_fatigue_horizon - 1):
        actual.step(dt=1.0, cognitive_load=0.8)

    assert actual.state.fatigue == pytest.approx(
        predicted_fatigue[-1], abs=0.05
    )


def test_prediction_says_work_tires_and_rest_recovers():
    model = _model()
    model.step(dt=1.0, cognitive_load=1.0, rest_depth=0.0)
    work_forecast = model.predicted_fatigue_trajectory[-1]

    model.step(dt=1.0, cognitive_load=0.0, rest_depth=1.0)
    rest_forecast = model.predicted_fatigue_trajectory[-1]

    assert work_forecast > rest_forecast