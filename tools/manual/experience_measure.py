"""Контрольный опыт: повторение, гипотеза, наблюдение и следующий выбор.

python tools/manual/experience_measure.py --report PATH
Без создания живого агента, сети и записи в data/. Это проверка механизма,
а не доказательство самостоятельного освоения знаний в долгой жизни.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.cognition.mental_models import ConceptNode, MentalModel
from src.core.agent import DigitalBeing


def measure() -> list[dict]:
    model = MentalModel()
    agent = DigitalBeing.__new__(DigitalBeing)
    agent._exploration_history = []
    rows = []

    def sample(stage):
        node = model.concepts["память"]
        rows.append({
            "stage": stage, "encounters": len(node.experiences),
            "evidence": node.evidence()[0], "confidence": node.confidence,
            "answerable": model.can_answer_about("память"),
            "exploration_candidate": agent._pick_shallow_concept(model.concepts),
        })

    for index in range(8):
        model.encounter_concept("память", f"вопрос_{index}", "Что такое память?", 0.9)
        model.consolidate()
    sample("повторение без ответа")
    model.encounter_concept("память", "гипотеза", "Возможно, это сохранение опыта", 0.9,
                            evidence_kind="hypothesis", source="self:hypothesis")
    sample("собственная гипотеза")
    model.encounter_concept("память", "проверка записи", "После перезапуска запись сохранилась", -0.7,
                            evidence_strength=0.8, evidence_kind="observation", source="action:restart:1")
    sample("неприятное подтверждающее наблюдение")
    for index in range(8):
        model.encounter_concept("память", f"вспоминание_{index}", "После перезапуска запись сохранилась",
                                evidence_strength=0.8, evidence_kind="observation", source="action:restart:1")
        model.consolidate()
    sample("повтор того же свидетельства и сон")
    stored = model.concepts["память"].to_storage_dict()
    model.concepts["память"] = ConceptNode.from_dict(json.loads(json.dumps(stored)))
    sample("сохранение и восстановление")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    text = json.dumps(measure(), ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
