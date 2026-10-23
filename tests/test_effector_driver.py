"""Stage 18B: the core owns the effector clock."""

from __future__ import annotations

from src.core.effector_driver import EffectorDriver
from src.core.effector_port import EffectorResult, EffectorStatus


class FakeEffector:
    def __init__(self, results=None) -> None:
        self.enabled = True
        self.core_driven = True
        self.results = list(results or [])
        self.calls = []

    def step(self, cycle):
        self.calls.append(cycle)
        if not self.results:
            return None
        return self.results.pop(0)


def result(request_id: str = "req-1") -> EffectorResult:
    return EffectorResult(
        request_id=request_id,
        status=EffectorStatus.SUCCEEDED,
        goal_id=1,
        ok=True,
    )


def test_driver_steps_once_per_cycle() -> None:
    effector = FakeEffector([result()])
    driver = EffectorDriver(effector)

    first = driver.tick(7)
    assert first["skipped"] is None
    assert first["result"]["status"] == "succeeded"
    assert effector.calls == [7]

    duplicate = driver.tick(7)
    assert duplicate["skipped"] == "duplicate_cycle"
    assert duplicate["result"] is None
    assert effector.calls == [7]

    empty = driver.tick(8)
    assert empty["skipped"] == "no_pending"
    assert effector.calls == [7, 8]
    assert driver.status()["steps"] == 1


def test_disabled_driver_does_not_call_step() -> None:
    effector = FakeEffector([result()])
    driver = EffectorDriver(effector, enabled=False)

    report = driver.tick(1)
    assert report["skipped"] == "disabled"
    assert effector.calls == []


def test_disabled_effector_is_reported_without_calling_step() -> None:
    effector = FakeEffector([result()])
    effector.enabled = False
    driver = EffectorDriver(effector)

    report = driver.tick(1)
    assert report["skipped"] == "effector_disabled"
    assert effector.calls == []


def test_step_failure_is_contained() -> None:
    class BrokenEffector:
        enabled = True

        def step(self, cycle):
            raise RuntimeError("action layer unavailable")

    driver = EffectorDriver(BrokenEffector())
    report = driver.tick(1)

    assert report["skipped"] == "error"
    assert "action layer unavailable" in driver.status()["last_error"]
    # A failed cycle is still consumed; the next cycle may retry.
    assert driver.tick(2)["skipped"] == "error"
