"""Проверяемые ожидания о собственном теле, не универсальная истина о мире."""

from dataclasses import asdict, dataclass
import math
from uuid import uuid4


@dataclass(frozen=True)
class ActionExpectation:
    trial_id: str
    action: str
    claim: str
    energy_before: float
    energy_max: float
    expected_direction: int
    prior_confidence: float
    fatigue_before: float | None = None
    fatigue_expected_direction: int = 1
    energy_testable: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class ActionExpectations:
    """Ожидание фиксируется до действия; наблюдение не выводится из награды.

    Первичная версия — гипотеза «отдых увеличивает энергию, если есть запас
    до потолка». Следующие ожидания используют наблюдения, а не конфиг
    количества восстановления. На потолке эта гипотеза непроверяема.
    """

    ACTIONS = frozenset({"rest", "deep_rest"})
    TOLERANCE = 1e-6

    def __init__(self):
        self.last_trial = None
        self._pending = {}

    def begin(self, model, action: str, energy: float, energy_max: float, *, fatigue: float | None = None):
        self.last_trial = None
        # Незавершённое действие не становится наблюдением при следующем.
        self._pending.clear()
        if action not in self.ACTIONS:
            return None
        if not all(math.isfinite(value) for value in (energy, energy_max)):
            return None
        if energy < 0 or energy_max <= 0 or energy > energy_max:
            return None
        energy_testable = energy < energy_max - self.TOLERANCE
        if fatigue is not None and (not math.isfinite(fatigue) or not 0 <= fatigue <= 1):
            fatigue = None
        if not energy_testable and not (fatigue is not None and fatigue > self.TOLERANCE):
            return None
        from src.cognition.empirical_claims import get_body_claim

        energy_claim = get_body_claim(model, action, "energy") if energy_testable else None
        fatigue_claim = get_body_claim(model, action, "fatigue") if fatigue is not None and fatigue > self.TOLERANCE else None
        claim = f"телесный опыт: {action} повышает энергию ниже потолка"
        node = model.concepts.get(claim)
        confidence = node.confidence if node else 0.1
        # Свидетельства относятся к конкретному утверждению, не ко всем
        # свойствам отдыха. Противоречия остаются в памяти.
        signed = energy_claim.evidence_node.evidence_direction() if energy_claim else 0
        fatigue_direction = fatigue_claim.evidence_node.evidence_direction() if fatigue_claim else 0
        trial = ActionExpectation(str(uuid4()), action, claim, float(energy),
                                  float(energy_max), -1 if signed < 0 else 1, confidence,
                                  fatigue, -1 if fatigue_direction < 0 else 1, energy_testable)
        if node is None and energy_testable:
            model.encounter_concept(
                claim, f"ожидание:{trial.trial_id}",
                f"Предполагаю: {action} увеличит мою энергию, если она ниже потолка",
                evidence_kind="hypothesis", source="self:body-expectation",
            )
        self._pending[trial.trial_id] = trial
        return trial

    def finish(self, model, trial, energy_after: float, *, fatigue_after: float | None = None):
        if trial is None or self._pending.pop(trial.trial_id, None) is not trial:
            return None
        if not math.isfinite(energy_after) or not 0 <= energy_after <= trial.energy_max + self.TOLERANCE:
            return None
        delta = float(energy_after) - trial.energy_before
        support = delta > self.TOLERANCE
        direction = 1 if support else -1
        from src.cognition.empirical_claims import get_body_claim

        conclusions = {}
        if trial.energy_testable:
            energy_claim = get_body_claim(model, trial.action, "energy")
            energy_claim.observe(f"action:{trial.trial_id}", trial.energy_before, energy_after,
                                 support, context=f"trial:{trial.trial_id}")
            conclusions["energy"] = energy_claim.conclusion()
        if (trial.fatigue_before is not None and trial.fatigue_before > self.TOLERANCE
                and fatigue_after is not None and math.isfinite(fatigue_after)
                and 0 <= fatigue_after <= 1):
            fatigue_claim = get_body_claim(model, trial.action, "fatigue")
            fatigue_claim.observe(f"action:{trial.trial_id}", trial.fatigue_before, fatigue_after,
                                  fatigue_after < trial.fatigue_before - self.TOLERANCE,
                                  context=f"trial:{trial.trial_id}")
            conclusions["fatigue"] = fatigue_claim.conclusion()
        node = model.encounter_concept(
            trial.claim, f"наблюдение:{trial.trial_id}",
            f"После {trial.action}: энергия {trial.energy_before:g} → {energy_after:g}; "
            f"потолок {trial.energy_max:g}. "
            + ("Рост наблюдался" if support else "Ожидаемого роста не наблюдалось"),
            evidence_strength=0.5, evidence_kind="observation",
            source=f"action:{trial.trial_id}", evidence_direction=direction,
        ) if trial.energy_testable else None
        self.last_trial = {
            **trial.to_dict(), "energy_after": float(energy_after), "delta": delta,
            "supports_claim": support if trial.energy_testable else None,
            "prediction_matched": ((delta > self.TOLERANCE) if trial.expected_direction == 1 else (delta <= self.TOLERANCE)) if trial.energy_testable else None,
            "confidence_after": node.confidence if node else None,
            "claims": conclusions,
            "fatigue_after": fatigue_after,
            "fatigue_prediction_matched": (
                ((fatigue_after < trial.fatigue_before - self.TOLERANCE)
                 == (trial.fatigue_expected_direction == 1))
                if "fatigue" in conclusions else None
            ),
        }
        return dict(self.last_trial)

    def cancel(self, trial):
        if trial is not None:
            self._pending.pop(trial.trial_id, None)
