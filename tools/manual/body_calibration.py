"""Калибровка интероцептивной модели: работа утомляет, отдых восстанавливает.

Не тест: печатает траектории тела, чтобы числа можно было подбирать
осмысленно, а не на глаз. Запуск из корня проекта:

    python tools/manual/body_calibration.py

Что должно быть видно (после калибровки):

* полный покой не утомляет — усталость 0, АТФ полон;
* работа утомляет тем быстрее, чем тяжелее нагрузка;
* отдых после работы возвращает глюкозу, АТФ и снимает усталость;
* из полного истощения есть выход: глюкоза возвращается отдыхом.
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ["DIGITAL_BEING_DATA_DIR"] = tempfile.mkdtemp(prefix="db_body_calib_")
os.environ["DIGITAL_BEING_TEST_MODE"] = "1"

from src.core.interoception import InteroceptiveModel  # noqa: E402


class _FakeAgent:
    cycle_count = 0


def _row(step: int, phase: str, model: InteroceptiveModel) -> str:
    s = model.state
    return (
        f"  t={step:3d} {phase:4s} glucose={s.glucose:5.2f} atp={s.atp:5.2f} "
        f"fatigue={s.fatigue:5.2f} cost×{s.action_cost_multiplier:4.2f}"
    )


def run_phase(model: InteroceptiveModel, steps: int, *, load: float,
              rest: float, phase: str, every: int = 5):
    for i in range(steps):
        model.step(dt=1.0, cognitive_load=load, rest_depth=rest)
        if i % every == 0 or i == steps - 1:
            print(_row(i, phase, model))


def scenario(label: str, steps: int, *, load: float, rest: float,
             every: int = 5):
    print(f"\n=== {label} ===")
    run_phase(
        InteroceptiveModel(_FakeAgent()),
        steps,
        load=load,
        rest=rest,
        phase="work" if load > 0 else ("rest" if rest > 0 else "idle"),
        every=every,
    )


def scenario_work_then_rest(work: int = 40, rest: int = 40):
    print(f"\n=== работа {work} тактов, затем отдых {rest} ===")
    model = InteroceptiveModel(_FakeAgent())
    run_phase(model, work, load=1.0, rest=0.0, phase="work")
    run_phase(model, rest, load=0.0, rest=1.0, phase="rest")


def scenario_collapse():
    print("\n=== полное истощение, затем отдых 40 ===")
    model = InteroceptiveModel(_FakeAgent())
    model.state.glucose = 0.0
    model.state.atp = 0.0
    model.state.fatigue = 0.9
    print(_row(0, "start", model))
    run_phase(model, 40, load=0.0, rest=1.0, phase="rest")


if __name__ == "__main__":
    scenario("покой 60 тактов (не должен утомлять)", 60, load=0.0, rest=0.0)
    scenario("работа 60 тактов", 60, load=1.0, rest=0.0, every=10)
    scenario_work_then_rest()
    scenario_collapse()