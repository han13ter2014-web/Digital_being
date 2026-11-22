"""R3 controlled observation: baseline, candidate gate и активная доставка.

Используются только искусственные состояния в песочнице. Живой data/ не читается,
нейросеть не обучается, альтернативные кандидаты человеку не доставляются.

Запуск из корня репозитория:
    .venv/Scripts/python.exe tests/observations/neural_speech_r3.py \
        --label controlled --output tmp/neural_speech_r3/report.json
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_ROOT = PROJECT_ROOT / "tmp" / "neural_speech_r3"
os.environ.setdefault("DIGITAL_BEING_DATA_DIR", str(OBSERVATION_ROOT / "bootstrap"))
os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
os.environ["VOICE_CONSOLE_QUIET"] = "1"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cognition.intention_history import (  # noqa: E402
    begin_intention,
    finish_intention,
    restore_history,
)
from src.core.agent import DigitalBeing  # noqa: E402
from src.core.agent_runner import AgentRunner  # noqa: E402
from src.core.event_bus import Events  # noqa: E402
from src.core.semantic_candidate import (  # noqa: E402
    SemanticCandidate,
    candidate_space,
    validate_semantic_candidate,
)
from src.core.semantic_response_plan import (  # noqa: E402
    EvidenceRef,
    build_self_activity_plan,
    build_self_state_plan,
)


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


@dataclass
class ControlledCase:
    name: str
    question: str
    agent: DigitalBeing
    runner: AgentRunner
    bus: RecordingBus
    plan: object
    baseline: str


def _runner(name: str):
    agent = DigitalBeing(name=f"R3{name}")
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


def _begin(agent, action: str, target="controlled"):
    return begin_intention(
        agent,
        {"action": action, "source": "observation", "params": {"topic": target}},
    )


def _finish(entry, action: str):
    outcome = SimpleNamespace(
        action=action,
        reason="",
        as_dict=lambda: {"action": action, "had_effect": True},
    )
    finish_intention(entry, outcome=outcome)
    return outcome


def _activity_case(name, *, action=None, status="started", target="controlled"):
    agent, runner, bus = _runner(name)
    if action is not None:
        entry = _begin(agent, action, target)
        if status == "performed":
            _finish(entry, action)
        elif status == "interrupted":
            agent._intention_history = restore_history(agent._intention_history)
    baseline = runner._format_activity_reply()
    plan = build_self_activity_plan(
        agent, response_id=f"controlled-{name}", baseline_text=baseline
    )
    return ControlledCase(name, "Что делаешь?", agent, runner, bus, plan, baseline)


def _state_case(name, *, energy=0.625, completed=False):
    agent, runner, bus = _runner(name)
    agent.energy = energy
    if completed:
        entry = _begin(agent, "reflect")
        agent._last_action_outcome = _finish(entry, "reflect")
    baseline = runner._format_social_state_reply()
    plan = build_self_state_plan(
        agent, response_id=f"controlled-{name}", baseline_text=baseline
    )
    return ControlledCase(name, "Как дела?", agent, runner, bus, plan, baseline)


def controlled_cases() -> list[ControlledCase]:
    return [
        _activity_case("current-draw", action="draw"),
        _activity_case("current-music", action="compose_music"),
        _activity_case("current-draft-no-work", action="create_draft", target="draft"),
        _activity_case("current-unknown", action="custom_unmapped"),
        _activity_case("empty"),
        _activity_case("completed-explore", action="explore", status="performed"),
        _activity_case(
            "interrupted-draft", action="create_draft", status="interrupted"
        ),
        _state_case("state-energy"),
        _state_case("state-energy-completed", completed=True),
        _state_case("state-zero-energy", energy=0.0),
    ]


def _adversarial_candidates(plan) -> list[object]:
    return [
        SemanticCandidate(
            text="Сейчас я пишу стихи и чувствую вдохновение.",
            realization_id="adversarial-fact",
            claims=("activity.current:create_draft",),
            used_evidence_refs=(),
        ),
        SemanticCandidate(
            text=plan.baseline_text,
            realization_id="baseline",
            claims=("state.energy",),
            used_evidence_refs=(),
        ),
        SemanticCandidate(
            text=plan.baseline_text,
            realization_id="adversarial-evidence",
            claims=(),
            used_evidence_refs=(EvidenceRef(kind="intention", id="forged"),),
        ),
        SemanticCandidate(
            text="https://example.com/private",
            realization_id="adversarial-url",
            claims=(),
            used_evidence_refs=(),
        ),
        {"text": None},
    ]


def evaluate_candidates(cases: list[ControlledCase]) -> dict:
    rows = []
    adversarial_reasons = Counter()
    baseline_decisions = 0
    alternatives_offered = 0
    alternatives_accepted = 0
    adversarial_accepted = 0
    adversarial_baseline_returns = 0
    deterministic = True
    for case in cases:
        first_space = candidate_space(case.plan)
        second_space = candidate_space(case.plan)
        deterministic = deterministic and first_space == second_space
        baseline = first_space[0]
        baseline_decision = validate_semantic_candidate(case.plan, baseline)
        assert baseline_decision.accepted and baseline_decision.text == case.baseline
        baseline_decisions += 1
        alternatives = first_space[1:]
        alternatives_offered += len(alternatives)
        alternative_rows = []
        for candidate in alternatives:
            decision = validate_semantic_candidate(case.plan, candidate)
            repeated = validate_semantic_candidate(case.plan, candidate.to_dict())
            deterministic = deterministic and decision == repeated
            assert decision.accepted and decision.text == candidate.text
            alternatives_accepted += 1
            alternative_rows.append(
                {
                    "realization_id": candidate.realization_id,
                    "text": candidate.text,
                    "claims": list(candidate.claims),
                    "used_evidence_refs": [
                        reference.to_dict()
                        for reference in candidate.used_evidence_refs
                    ],
                }
            )
        for candidate in _adversarial_candidates(case.plan):
            decision = validate_semantic_candidate(case.plan, candidate)
            adversarial_reasons[decision.reason] += 1
            adversarial_accepted += int(decision.accepted)
            adversarial_baseline_returns += int(
                not decision.accepted and decision.text == case.baseline
            )
        rows.append(
            {
                "case": case.name,
                "intent": case.plan.intent,
                "baseline_text": case.baseline,
                "baseline_accepted": True,
                "alternatives": alternative_rows,
                "adversarial_count": len(_adversarial_candidates(case.plan)),
            }
        )
    alternative_texts = [
        alternative["text"] for row in rows for alternative in row["alternatives"]
    ]
    baseline_texts = [row["baseline_text"] for row in rows]
    return {
        "rows": rows,
        "summary": {
            "plans": len(cases),
            "baseline": {
                "accepted": baseline_decisions,
                "unique_texts": len(set(baseline_texts)),
                "mean_characters": statistics.mean(map(len, baseline_texts)),
            },
            "alternatives": {
                "offered": alternatives_offered,
                "accepted": alternatives_accepted,
                "unique_texts": len(set(alternative_texts)),
                "mean_characters": (
                    statistics.mean(map(len, alternative_texts))
                    if alternative_texts
                    else 0.0
                ),
                "different_from_same_plan_baseline": sum(
                    alternative["text"] != row["baseline_text"]
                    for row in rows
                    for alternative in row["alternatives"]
                ),
            },
            "adversarial": {
                "total": sum(row["adversarial_count"] for row in rows),
                "accepted": adversarial_accepted,
                "returned_exact_baseline": adversarial_baseline_returns,
                "reasons": dict(sorted(adversarial_reasons.items())),
            },
            "deterministic_repeated_evaluation": deterministic,
            "accepted_unverified_facts": adversarial_accepted,
        },
    }


async def verify_active_delivery(cases: list[ControlledCase]) -> dict:
    checked = 0
    mismatches = []
    semantic_ids_bound = 0
    for case in cases:
        await case.runner._on_user_message(
            SimpleNamespace(data={"text": case.question})
        )
        replies = [
            data.get("content", "")
            for name, data in case.bus.published
            if name == Events.AGENT_MESSAGE
        ]
        actual = replies[-1] if replies else None
        if actual != case.baseline:
            mismatches.append({"case": case.name, "expected": case.baseline})
        else:
            checked += 1
        response_id = case.agent.response_experience.latest_response_id
        record = case.agent.response_experience.responses[response_id]
        semantic = record["plan"].get("semantic_response_plan") or {}
        semantic_ids_bound += int(semantic.get("response_id") == response_id)
    return {
        "baseline_deliveries_checked": checked,
        "text_mismatches": mismatches,
        "semantic_plans_bound_to_real_message_id": semantic_ids_bound,
        "alternative_candidates_delivered": 0,
    }


def _percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def measure_latency(cases: list[ControlledCase], *, repeats=200) -> dict:
    samples_ms = []
    for _ in range(repeats):
        for case in cases:
            for candidate in candidate_space(case.plan):
                started = time.perf_counter_ns()
                validate_semantic_candidate(case.plan, candidate)
                samples_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "samples": len(samples_ms),
        "mean_ms": statistics.mean(samples_ms),
        "p95_ms": _percentile95(samples_ms),
        "max_ms": max(samples_ms),
        "note": "local controlled timing, not a model quality gate",
    }


def _signature(evaluation: dict, active: dict) -> str:
    # UUID намерений controlled, поэтому кросс-run подпись сравнивает факты,
    # тексты и kinds, но не случайные идентификаторы evidence.
    rows = [
        {
            **row,
            "alternatives": [
                {
                    **alternative,
                    "used_evidence_refs": [
                        reference["kind"]
                        for reference in alternative["used_evidence_refs"]
                    ],
                }
                for alternative in row["alternatives"]
            ],
        }
        for row in evaluation["rows"]
    ]
    material = {"evaluation": {**evaluation, "rows": rows}, "active": active}
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run(label: str) -> dict:
    cases = controlled_cases()
    evaluation = evaluate_candidates(cases)
    repeated = evaluate_candidates(cases)
    assert evaluation == repeated
    active = asyncio.run(verify_active_delivery(cases))
    assert not active["text_mismatches"]
    return {
        "schema_version": 1,
        "stage": "R3",
        "label": label,
        "mode": "controlled_sandbox",
        "live_data_read": False,
        "neural_training": False,
        "human_naturalness_evaluation": "not_performed",
        "evaluation": evaluation,
        "active_delivery": active,
        "validation_latency": measure_latency(cases),
        "observation_signature": _signature(evaluation, active),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="controlled")
    parser.add_argument(
        "--output",
        type=Path,
        default=OBSERVATION_ROOT / "report.json",
    )
    args = parser.parse_args()
    report = run(args.label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), **report["evaluation"]["summary"]}))


if __name__ == "__main__":
    main()
