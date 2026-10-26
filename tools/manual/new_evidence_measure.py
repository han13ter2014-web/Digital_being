"""Новый ответ человека: свидетельство и доступность возврата, без сети.

Контролируемое построение незавершённой попытки; не естественное рождение цели.
"""

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def measure(case):
    from src.core.agent import DigitalBeing
    from src.core.subsystem_base import PluginRegistry
    from src.cognition.intention_history import begin_intention, finish_intention
    from src.cognition.intention_evidence import finish_evidence_goal, evidence_sources
    from src.cognition.intention_continuation import continuation_candidate
    from src.cognition.method_feedback import information_context

    PluginRegistry.reset_global()
    agent = DigitalBeing(name="NewEvidenceMeasure")
    agent.cycle_count = 100
    first = begin_intention(agent, {"action": "explore", "source": "test", "params": {"topic": "память"}})
    agent.mental_models.encounter_concept("память", "первая встреча", "Встретил неизвестную тему")
    finish_intention(first)
    finish_evidence_goal(agent, first)
    agent.cycle_count += 1
    retry = begin_intention(agent, continuation_candidate(agent))
    finish_intention(retry)
    finish_evidence_goal(agent, retry)
    agent.cycle_count += 1
    before_context = information_context(agent)
    before_sources = evidence_sources(agent, "память")
    if case != "no_source":
        topic = "память" if case == "relevant_answer" else "дерево"
        answer = ("Память сохраняет опыт и позволяет использовать его позднее."
                  if topic == "память" else "Дерево — многолетнее растение с одревесневшим стволом.")
        queued = agent.user_interaction.ask_user(topic, cycle=agent.cycle_count)
        if queued["status"] != "queued":
            raise RuntimeError(queued)
        agent._process_user_answer(answer)
    proposal = continuation_candidate(agent)
    thought = agent.think("вопрос: память") if case == "relevant_answer" else None
    result = {"case": case,
              "goal_status": retry["evidence_goal"]["status"],
              "answer_from_memory": bool(thought and "[Ментальная модель]" in thought), "sources_before": before_sources,
              "sources_after": evidence_sources(agent, "память"),
              "information_context_changed": before_context != information_context(agent),
              "continuation_offered": proposal is not None,
              "offered_topic": proposal["params"]["topic"] if proposal else None,
              "meaning": "New evidence is not proof of full understanding"}
    PluginRegistry.reset_global()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="db_new_evidence_") as directory:
        os.environ["DIGITAL_BEING_DATA_DIR"] = directory
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG
        LR_CONFIG.WEB_SEARCH_ENABLED = False
        results = [measure(case) for case in ("no_source", "unrelated_answer", "relevant_answer")]
        args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results, ensure_ascii=True, indent=2))
        logging.shutdown()
