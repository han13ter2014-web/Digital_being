"""Неподменённый выбор внимания и сверка числа действий с тиками."""

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


async def measure(cycles, seed, burst=1, restart=False):
    import numpy as np
    from src.app.bootstrap import create_agent
    from src.app.paths import setup_environment
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    random.seed(seed)
    np.random.seed(seed)
    env = setup_environment(chdir=False, console=False)
    agent, _ = create_agent(env, "AttentionMeasure", new=True)
    runner = AgentRunner(agent, EventBus())
    runner.set_speed("max")
    counts = Counter()
    actions_per_tick = Counter()
    executed = 0
    original_act = agent.act

    def act(decision):
        nonlocal executed
        executed += 1
        return original_act(decision)

    agent.act = act
    pending_since = None
    waits = []
    restart_equal = None
    await runner.start()
    try:
        for step in range(cycles):
            if step % 100 == 0:
                if not hasattr(runner, "_pending_user_messages"):
                    raise RuntimeError("runner queue missing")
                for index in range(burst):
                    runner._pending_user_messages.put_nowait(f"вопрос: что такое память {step}:{index}")
                    counts["user_injected"] += 1
            before = executed
            runner.energy_policy.regenerate(5.0)
            await runner.step_once()
            actions_per_tick[executed - before] += 1
            ledger = runner._last_tick_ledger
            counts[ledger["kind"]] += 1
            if ledger["kind"] == "stimulus_deferred":
                if pending_since is None:
                    pending_since = step
            elif ledger["kind"] == "stimulus_processed":
                if ledger.get("user_initiated"):
                    counts["user_processed"] += 1
                if pending_since is not None:
                    waits.append(step - pending_since)
                    pending_since = None
            if restart and step + 1 == cycles // 2:
                before_pending = list(agent._pending_message_texts)
                before_deferred = getattr(agent, "_deferred_stimulus", None)
                await runner.stop()
                from src.core.subsystem_base import PluginRegistry
                PluginRegistry.reset_global()
                agent, _ = create_agent(env, "AttentionMeasure")
                restart_equal = (before_pending == agent._pending_message_texts
                                 and before_deferred == agent._deferred_stimulus)
                original_act = agent.act
                agent.act = act
                runner = AgentRunner(agent, EventBus())
                runner.set_speed("max")
                await runner.start()
    finally:
        await runner.stop()
    return {"seed": seed, "cycles": cycles, "counts": dict(counts),
            "actions_per_tick": dict(actions_per_tick), "actual_act_calls": executed,
            "max_completed_wait": max(waits, default=0),
            "unfinished_wait": cycles - pending_since if pending_since is not None else None,
            "queued_user_messages": runner._pending_user_messages.qsize(),
            "restart_queue_equal": restart_equal, "burst": burst,
            "final_cycle": agent.cycle_count}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--burst", type=int, default=1)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="db_attention_") as directory:
        os.environ["DIGITAL_BEING_DATA_DIR"] = directory
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG
        LR_CONFIG.WEB_SEARCH_ENABLED = False
        result = asyncio.run(measure(args.cycles, args.seed, args.burst, args.restart))
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logging.shutdown()
