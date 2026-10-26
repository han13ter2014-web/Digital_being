"""Отдельные проверяемые утверждения с явными условиями и происхождением."""

from dataclasses import dataclass, field

from src.cognition.mental_models import ConceptNode


@dataclass
class EmpiricalClaim:
    claim_id: str
    subject: str
    metric: str
    relation: str
    conditions: dict
    evidence_node: ConceptNode = field(repr=False)

    @classmethod
    def create(cls, claim_id, subject, metric, relation, conditions):
        return cls(claim_id, subject, metric, relation, dict(conditions), ConceptNode(claim_id))

    def conclusion(self) -> dict:
        strength, agreement = self.evidence_node.evidence()
        direction = self.evidence_node.evidence_direction()
        confidence = self.evidence_node.confidence
        status = "insufficient"
        if confidence > 0.4 and direction:
            status = "supported" if direction > 0 else "refuted"
        return {"status": status, "direction": direction, "confidence": confidence,
                "strength": strength, "agreement": agreement}

    def observe(self, source, before, after, supports, *, context):
        # Сравнение уже сделано измерителем именно этого свойства.
        self.evidence_node.add_experience(
            context, f"{self.metric}: {before:g} → {after:g}",
            evidence_strength=0.5, evidence_kind="observation", source=source,
            evidence_direction=1 if supports else -1,
        )

    def to_dict(self):
        return {"claim_id": self.claim_id, "subject": self.subject,
                "metric": self.metric, "relation": self.relation,
                "conditions": dict(self.conditions),
                "evidence": self.evidence_node.to_storage_dict()}

    @classmethod
    def from_dict(cls, data):
        if data["metric"] not in {"energy", "fatigue"}:
            raise ValueError("Неизвестная измеряемая величина утверждения")
        if data["relation"] not in {"increase", "decrease"}:
            raise ValueError("Неизвестное отношение утверждения")
        if not isinstance(data["conditions"], dict):
            raise ValueError("Условия утверждения должны быть словарём")
        return cls(data["claim_id"], data["subject"], data["metric"], data["relation"],
                   dict(data["conditions"]), ConceptNode.from_dict(data["evidence"]))


def get_body_claim(model, action, metric):
    relation = "increase" if metric == "energy" else "decrease"
    claim_id = f"body:{action}:{metric}:{relation}:v1"
    if claim_id not in model.claims:
        conditions = ({"energy_below_ceiling": True} if metric == "energy"
                      else {"fatigue_above_zero": True})
        conditions["action_performed"] = True
        claim = EmpiricalClaim.create(claim_id, action, metric, relation, conditions)
        if metric == "energy":
            # Переносим только прежнее точно такое же утверждение. Прочие
            # знания о понятии «отдых» не становятся доказательством.
            legacy_name = f"телесный опыт: {action} повышает энергию ниже потолка"
            old = model.concepts.get(legacy_name)
            if old is not None:
                claim.evidence_node = ConceptNode.from_dict(old.to_storage_dict())
                claim.evidence_node.name = claim_id
        model.claims[claim_id] = claim
    return model.claims[claim_id]
