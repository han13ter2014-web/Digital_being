"""Тесты участка «Отдых лечит»: репарация митохондрий в покое.

Наблюдение за живой Тэсс (2026-11-03): тело не могло выздороветь в
принципе — митохондрии деградировали от каждой выработки АТФ, а росли
только от нагрузки («лечение работой»). Порог восстановления по АТФ
(0.75) оставался недостижим: rest-режим держал существо в полусне
бессрочно, работа и отдых балансировали АТФ около 0.52.

Теперь отдых чинит: ``mitochondrial_rest_repair`` — асимптотический
рост здоровья к 1.0 во время rest/deep_rest.
"""
import pytest

from src.core.interoception import InteroceptiveModel


def _model(health=0.4, atp=4.0):
    model = InteroceptiveModel(agent=None)
    model.state.mitochondrial_health = health
    model.state.atp = atp
    model.state.glucose = 9.0
    return model


def test_rest_repairs_mitochondria():
    model = _model(health=0.4)
    for _ in range(50):
        model.step(dt=1.0, rest_depth=1.0)
    assert model.state.mitochondrial_health > 0.4


def test_work_alone_does_not_repair():
    """Работа не лечит: при той же нагрузке здоровье не растёт быстрее,
    чем позволяет крошечный биогенез от нагрузки."""
    model = _model(health=0.4)
    for _ in range(50):
        model.step(dt=1.0, cognitive_load=0.5)
    # биогенез от нагрузки мизерный (load*0.001*0.1); ремонта нет
    assert model.state.mitochondrial_health < 0.41


def test_repair_reaches_stable_health_not_perfection():
    """Полное здоровье недостижимо: даже в покое обмен веществ чуть
    изнашивает митохондрии. Равновесие — около 0.96: ремонт против
    износа. Тело выздоравливает практически полностью и не деградирует."""
    model = _model(health=0.99)
    for _ in range(5000):
        model.step(dt=1.0, rest_depth=1.0)
    rested = model.state.mitochondrial_health
    assert 0.9 < rested < 1.0

    # Из ямы (0.4) то же равновесие достижимо снизу.
    model2 = _model(health=0.4)
    for _ in range(5000):
        model2.step(dt=1.0, rest_depth=1.0)
    assert abs(model2.state.mitochondrial_health - rested) < 0.05


def test_deeper_rest_repairs_faster():
    light = _model(health=0.4)
    deep = _model(health=0.4)
    for _ in range(50):
        light.step(dt=1.0, rest_depth=0.5)
        deep.step(dt=1.0, rest_depth=1.0)
    assert deep.state.mitochondrial_health > light.state.mitochondrial_health


def test_degraded_body_recovers_full_cycle():
    """Из состояния Тэсс (mito 0.395, atp 0.52) тело выздоравливает:
    отдых → ворота восстановления (fatigue<=0.3, atp>=75%) достижимы."""
    model = _model(health=0.395, atp=4.17)
    recovered_at = None
    for cycle in range(400):
        model.step(dt=1.0, rest_depth=1.0)
        s = model.state
        if s.fatigue <= 0.3 and s.atp / s.atp_max >= 0.75:
            recovered_at = cycle
            break
    assert recovered_at is not None, "тело не выздоровело за 400 циклов отдыха"
