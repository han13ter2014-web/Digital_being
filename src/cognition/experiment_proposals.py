"""Необязательное предложение проверить уже существующее утверждение."""

import math


def propose_experiment(model, *, energy, energy_max, fatigue, cycle, last_cycle=None):
    if last_cycle is not None and cycle - last_cycle < 20:
        return None
    if not all(math.isfinite(value) for value in (energy, energy_max)):
        return None
    from src.cognition.action_expectations import ActionExpectations

    tolerance = ActionExpectations.TOLERANCE
    possible = []
    for claim_id, claim in model.claims.items():
        if claim.subject not in {"rest", "deep_rest"}:
            continue
        if claim.conditions.get("action_performed") is not True:
            continue
        conclusion = claim.conclusion()
        # Уверенное опровержение — тоже результат, не повод бесконечно
        # добиваться предпочитаемого ответа.
        if conclusion["confidence"] >= 0.7:
            continue
        if claim.metric == "energy":
            if claim.relation != "increase" or not claim.conditions.get("energy_below_ceiling"):
                continue
            if not 0 <= energy < energy_max - tolerance:
                continue
        elif claim.metric == "fatigue":
            if claim.relation != "decrease" or not claim.conditions.get("fatigue_above_zero"):
                continue
            if fatigue is None or not math.isfinite(fatigue) or not tolerance < fatigue <= 1:
                continue
        else:
            continue
        uncertainty = 1.0 - conclusion["confidence"]
        possible.append((uncertainty, claim_id, claim))
    if not possible:
        return None
    uncertainty, claim_id, claim = max(possible, key=lambda item: (item[0], item[1]))
    return {"source": "self_experiment", "action": claim.subject,
            "strength": min(0.55, 0.6 * uncertainty),
            "params": {"claim_id": claim_id, "reason": "Проверить собственное неуверенное представление",
                       "uncertainty": uncertainty, "metric": claim.metric}}
