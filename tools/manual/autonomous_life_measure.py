"""Естественная конкуренция побуждений, телесная энергия и перезапуск.

Ускоренный прогон: каждый шаг получает 5 секунд регенерации как live.
Реальные wall-clock кулдауны не ускоряются — это ограничение замера.
Ни энергия, ни арбитр, ни исходы действий не подменяются. Сеть выключена.
"""

import argparse
import asyncio
from collections import Counter
import json
import logging
import os
from pathlib import Path
import random
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def measure(cycles, seed):
    import numpy as np
    from src.app.paths import setup_environment
    from src.app.bootstrap import create_agent
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    random.seed(seed)
    np.random.seed(seed)
    env = setup_environment(chdir=False)
    agent, _ = create_agent(env, "AutonomousMeasure", new=True)
    actions, sources, offers, selected = Counter(), Counter(), Counter(), Counter()
    rivals, matches = Counter(), Counter()
    traces = []
    escape_traces = []
    initial_sources, transitions = Counter(), Counter()
    deferred_methods, released_methods = Counter(), Counter()
    energies, fatigues = [], []
    continuation_offers, continuation_choices, continuation_losses = (
        Counter(),
        Counter(),
        Counter(),
    )
    continuation_traces = []
    restart = None
    play_turns = 0
    action_offers = Counter()
    satisfactions, resolutions, intention_statuses = Counter(), Counter(), Counter()
    empty_productive = Counter()
    max_history = max_waiting = max_active_waiting = 0
    arbitration_rounds = exact_tie_rounds = 0
    tie_winners, tie_participants = Counter(), Counter()
    loss_reasons, loss_actions = Counter(), Counter()
    intention_offers, intention_choices = Counter(), Counter()
    goal_offers = Counter()
    candidate_score_stats = {}
    candidate_losses_to = {}
    waiting_states, waiting_actions, waiting_goal_links = (
        Counter(),
        Counter(),
        Counter(),
    )

    def attach(current):
        original = current.autonomous_tick

        def observe():
            nonlocal play_turns, max_history, max_waiting, max_active_waiting
            nonlocal arbitration_rounds, exact_tie_rounds
            report = original()
            if (report.get("autonomous_action") or {}).get("action") == "play":
                play_turns += 1
            arbiter = report.get("arbitrator") or {}
            actions[arbiter.get("action", "none")] += 1
            sources[arbiter.get("source", "none")] += 1

            # LoopCloser может заменить финальное действие. Конкуренцию score
            # измеряем на исходном решении арбитра, не на последующем escape.
            arbitration = report.get("initial_arbitration") or arbiter
            diagnostics = arbitration.get("choice_diagnostics") or {}
            evaluations = arbitration.get("all_evaluations") or []
            winner_index = diagnostics.get("winner_input_index")
            tied_indices = set(diagnostics.get("tied_input_indices") or [])
            if diagnostics:
                arbitration_rounds += 1
                if diagnostics.get("exact_tie"):
                    exact_tie_rounds += 1
                    tie_winners[
                        f"{arbitration.get('source')}:{arbitration.get('action')}"
                    ] += 1
            for evaluation in evaluations:
                action = evaluation.get("action", "none")
                action_offers[action] += 1
                stats = candidate_score_stats.setdefault(
                    action,
                    {
                        "offers": 0,
                        "strength_total": 0.0,
                        "arbiter_score_total": 0.0,
                        "combined_score_total": 0.0,
                        "combined_score_min": None,
                        "combined_score_max": None,
                    },
                )
                stats["offers"] += 1
                for field in ("strength", "arbiter_score", "combined_score"):
                    value = evaluation.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        stats[f"{field}_total"] += float(value)
                combined = evaluation.get("combined_score")
                if isinstance(combined, (int, float)) and not isinstance(
                    combined, bool
                ):
                    stats["combined_score_min"] = (
                        combined
                        if stats["combined_score_min"] is None
                        else min(stats["combined_score_min"], combined)
                    )
                    stats["combined_score_max"] = (
                        combined
                        if stats["combined_score_max"] is None
                        else max(stats["combined_score_max"], combined)
                    )

                contexts = []
                if evaluation.get("target") is not None:
                    contexts.append("with_target")
                if evaluation.get("goal_id") is not None:
                    contexts.append("with_goal_id")
                    goal_offers[str(evaluation["goal_id"])] += 1
                if evaluation.get("continuation_of") is not None:
                    contexts.append("continuation")
                for context in contexts:
                    intention_offers[context] += 1
                    if evaluation.get("input_index") == winner_index:
                        intention_choices[context] += 1

                if (
                    diagnostics.get("exact_tie")
                    and evaluation.get("input_index") in tied_indices
                ):
                    tie_participants[f"{evaluation.get('source')}:{action}"] += 1
                if evaluation.get("input_index") == winner_index:
                    continue
                if evaluation.get("verdict") == "stop":
                    reason = "stopped"
                elif evaluation.get("input_index") in tied_indices:
                    reason = "exact_tie_input_order"
                else:
                    reason = "lower_score"
                loss_reasons[reason] += 1
                loss_actions[f"{action}:{reason}"] += 1
                winner = f"{arbitration.get('source')}:{arbitration.get('action')}"
                candidate_losses_to.setdefault(action, Counter())[winner] += 1

            selected_entry = next(
                (
                    item
                    for item in reversed(getattr(current, "_intention_history", []))
                    if item["id"] == report.get("intention_id")
                ),
                None,
            )
            if selected_entry is not None:
                intention_statuses[selected_entry["status"]] += 1
                episode = selected_entry.get("decision_episode") or {}
                satisfactions[episode.get("satisfaction", "missing")] += 1
                resolutions[episode.get("resolution", "missing")] += 1
                action = selected_entry.get("action", "none")
                outcome = selected_entry.get("outcome") or {}
                if (
                    selected_entry.get("status") == "performed"
                    and action not in {"wait", "rest", "deep_rest"}
                    and not outcome.get("had_effect")
                ):
                    empty_productive[action] += 1
            max_history = max(
                max_history, len(getattr(current, "_intention_history", []))
            )
            waiting = getattr(current, "_waiting_intentions", {})
            max_waiting = max(max_waiting, len(waiting))
            active_waiting = 0
            for waiting_entry in waiting.values():
                resolution = waiting_entry.get("resolution") or {}
                state = resolution.get("kind") or (
                    waiting_entry.get("evidence_goal") or {}
                ).get("status", "unknown")
                waiting_states[state] += 1
                waiting_actions[waiting_entry.get("action", "unknown")] += 1
                linked = waiting_entry.get("goal_id") is not None
                waiting_goal_links["with_goal_id" if linked else "without_goal_id"] += 1
                if not resolution:
                    active_waiting += 1
            max_active_waiting = max(max_active_waiting, active_waiting)
            continuation = report.get("continuation_proposal")
            if continuation:
                target = continuation["params"]["topic"]
                continuation_offers[target] += 1
                if arbiter.get("source") == "intention_continuation":
                    continuation_choices[target] += 1
                    entry = next(
                        (
                            item
                            for item in reversed(
                                getattr(current, "_intention_history", [])
                            )
                            if item["id"] == report.get("intention_id")
                        ),
                        None,
                    )
                    continuation_traces.append(
                        {
                            "cycle": current.cycle_count,
                            "target": target,
                            "entry": entry.copy() if entry else None,
                        }
                    )
                else:
                    continuation_losses[arbiter.get("source", "none")] += 1
            feedback = report.get("method_feedback") or {}
            deferred_methods.update(
                item["normalized_action"] for item in feedback.get("deferred", [])
            )
            released_methods.update(feedback.get("released", []))
            initial_sources[
                (report.get("initial_arbitration") or {}).get("source", "none")
            ] += 1
            escape = report.get("loop_escape")
            if escape:
                transitions[f"{escape['from']} -> {escape['to']}"] += 1
                outcome = current.loop_closer.last_outcome
                escape_traces.append(
                    {
                        "cycle": current.cycle_count,
                        **escape,
                        "initial_source": (report.get("initial_arbitration") or {}).get(
                            "source"
                        ),
                        "energy": current.energy,
                        "fatigue": current.interoception.state.fatigue,
                        "outcome": outcome.as_dict() if outcome else None,
                    }
                )
            proposal = report.get("experiment_proposal")
            if proposal:
                claim_id = proposal["params"]["claim_id"]
                offers[claim_id] += 1
                if arbiter.get("source") != "self_experiment":
                    rivals[arbiter.get("source", "none")] += 1
            result = report.get("experiment_result")
            if result:
                selected[result["claim_id"]] += 1
                observation = result.get("observation")
                metric = proposal["params"]["metric"] if proposal else None
                if observation and metric in observation.get("claims", {}):
                    field = (
                        "fatigue_prediction_matched"
                        if metric == "fatigue"
                        else "prediction_matched"
                    )
                    matches[str(observation.get(field))] += 1
                else:
                    matches["target_not_observed"] += 1
                traces.append({"cycle": current.cycle_count, **result})
            return report

        current.autonomous_tick = observe
        runner = AgentRunner(current, EventBus(), name="AutonomousMeasureRunner")
        runner.set_speed("max")
        runner.set_stimulus_mode("pool")
        return runner

    runner = attach(agent)
    await runner.start()
    try:
        for step in range(1, cycles + 1):
            runner.energy_policy.regenerate(5.0)
            await runner.step_once()
            energies.append(float(agent.energy))
            fatigues.append(float(agent.interoception.state.fatigue))
            if step == cycles // 2:
                before = agent.mental_models.to_storage_dict()
                energy_before = agent.energy
                fatigue_before = agent.interoception.state.fatigue
                last_check = getattr(agent, "_last_experiment_cycle", None)
                history_before = list(getattr(agent, "_intention_history", []))
                from copy import deepcopy

                game_before = deepcopy(getattr(agent, "_local_play", None))
                await runner.stop()
                from src.core.subsystem_base import PluginRegistry

                PluginRegistry.reset_global()
                agent, report = create_agent(env, "AutonomousMeasure")
                restart = {
                    "source": report["source"],
                    "memory_identical": before == agent.mental_models.to_storage_dict(),
                    "energy_identical": energy_before == agent.energy,
                    "fatigue_identical": fatigue_before
                    == agent.interoception.state.fatigue,
                    "cooldown_identical": last_check
                    == getattr(agent, "_last_experiment_cycle", None),
                }
                restart["intention_history_equal"] = history_before == getattr(
                    agent, "_intention_history", []
                )
                restart["game_equal"] = game_before == getattr(
                    agent, "_local_play", None
                )
                runner = attach(agent)
                await runner.start()
    finally:
        await runner.stop()
    claims = {
        key: {
            **claim.conclusion(),
            "observations": len(claim.evidence_node.experiences),
        }
        for key, claim in agent.mental_models.claims.items()
    }
    return {
        "seed": seed,
        "cycles": cycles,
        "arbitrated_actions": dict(actions),
        "action_offers": dict(action_offers),
        "arbitration_rounds": arbitration_rounds,
        "exact_tie_rounds": exact_tie_rounds,
        "exact_tie_winners": dict(tie_winners),
        "exact_tie_participants": dict(tie_participants),
        "candidate_loss_reasons": dict(loss_reasons),
        "candidate_loss_actions": dict(loss_actions),
        "candidate_losses_to": {
            action: dict(winners) for action, winners in candidate_losses_to.items()
        },
        "candidate_score_stats": candidate_score_stats,
        "intention_context_offers": dict(intention_offers),
        "intention_context_choices": dict(intention_choices),
        "goal_id_offers": dict(goal_offers),
        "decision_satisfaction": dict(satisfactions),
        "decision_resolutions": dict(resolutions),
        "intention_statuses": dict(intention_statuses),
        "empty_productive_actions": dict(empty_productive),
        "max_intention_history": max_history,
        "max_waiting_intentions": max_waiting,
        "max_active_waiting_intentions": max_active_waiting,
        "waiting_state_observations": dict(waiting_states),
        "waiting_action_observations": dict(waiting_actions),
        "waiting_goal_link_observations": dict(waiting_goal_links),
        "final_waiting_queue": [
            {
                "action": entry.get("action"),
                "target": entry.get("target"),
                "goal_id": entry.get("goal_id"),
                "evidence_status": (entry.get("evidence_goal") or {}).get("status"),
                "resolution": entry.get("resolution"),
            }
            for entry in getattr(agent, "_waiting_intentions", {}).values()
        ],
        "play_turns": play_turns,
        "final_game": getattr(agent, "_local_play", None),
        "continuation_offers": dict(continuation_offers),
        "continuation_choices": dict(continuation_choices),
        "continuation_losses": dict(continuation_losses),
        "continuation_traces": continuation_traces,
        "final_intention_history": list(getattr(agent, "_intention_history", [])),
        "winning_sources": dict(sources),
        "initial_sources": dict(initial_sources),
        "escape_transitions": dict(transitions),
        "escape_traces": escape_traces,
        "deferred_methods": dict(deferred_methods),
        "released_methods": dict(released_methods),
        "productive_actions": agent.loop_closer.productive_total,
        "productive_effects": agent.loop_closer.productive_effect_total,
        "proposals": dict(offers),
        "selected_checks": dict(selected),
        "checks_lost_to": dict(rivals),
        "prediction_matches": dict(matches),
        "experiment_traces": traces,
        "energy_range": [min(energies), max(energies)],
        "fatigue_range": [min(fatigues), max(fatigues)],
        "restart": restart,
        "claims": claims,
        "concept_experiences": sum(
            len(node.experiences) for node in agent.mental_models.concepts.values()
        ),
        "claim_observations": sum(
            len(claim.evidence_node.experiences)
            for claim in agent.mental_models.claims.values()
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--no-method-feedback", action="store_true")
    parser.add_argument("--no-continuation", action="store_true")
    args = parser.parse_args()
    if args.cycles < 2:
        parser.error("Нужно минимум два цикла")
    with tempfile.TemporaryDirectory(prefix="db_autonomous_life_") as directory:
        os.environ["DIGITAL_BEING_DATA_DIR"] = directory
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG

        LR_CONFIG.WEB_SEARCH_ENABLED = False
        from contextlib import ExitStack
        from unittest.mock import patch

        with ExitStack() as stack:
            if args.no_method_feedback:
                stack.enter_context(
                    patch(
                        "src.cognition.method_feedback.prepare_candidates",
                        side_effect=lambda agent, candidates: (candidates, {}),
                    )
                )
            if args.no_continuation:
                stack.enter_context(
                    patch(
                        "src.cognition.intention_continuation.continuation_candidate",
                        return_value=None,
                    )
                )
            result = asyncio.run(measure(args.cycles, args.seed))
        result["continuation_enabled"] = not args.no_continuation
        result["method_feedback_enabled"] = not args.no_method_feedback
        args.report.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        logging.shutdown()
