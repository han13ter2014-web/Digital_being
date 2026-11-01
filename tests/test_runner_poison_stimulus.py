"""Отравленный стимул не должен замораживать жизнь.

До фикса perceive/think/act/evolve, упав с исключением, оставляли
``agent._deferred_stimulus`` установленным: раннер ретраил тот же
стимул каждый тик без лимита, cycle_count замирал, чекпоинты по
CHECKPOINT_INTERVAL прекращались, а пользовательские сообщения
простаивали в очереди. Теперь стимул отпускается честно после
MAX_STIMULUS_RETRIES неудач, с объяснением человеку.
"""

import asyncio
import os

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner, MAX_STIMULUS_RETRIES
from src.core.event_bus import EventBus, Events


@pytest.fixture()
def runtime():
    """Агент + шина + раннер, как в реальном запуске (см. test_runner_speed)."""
    from src.core.paths import data_path

    for name in ("life_state.json", "life_requests.json"):
        try:
            os.unlink(data_path(name))
        except OSError:
            pass

    agent = DigitalBeing(name="PoisonTest")
    searcher = getattr(agent, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    bus = EventBus(max_queue_size=200, history_size=100)
    runner = AgentRunner(agent, bus, name="PoisonRunner")
    return agent, bus, runner


def _break_stage(agent, stage: str):
    """Детерминированный сбой на выбранном этапе цикла агента."""

    def _raise(*args, **kwargs):
        raise RuntimeError(f"poison: {stage}")

    setattr(agent, stage, _raise)


def _force_attention(agent):
    """Арбитр всегда выбирает обработку стимула — убираем случайность."""
    agent.autonomous_tick = lambda: {
        "attention_selected": True,
        "arbitrator": {"action": "process_stimulus"},
    }


def _poison_deferred(agent):
    agent._deferred_stimulus = {"text": "отравленный стимул", "user_initiated": True}


def test_poison_stimulus_retried_below_limit(runtime):
    agent, bus, runner = runtime
    _force_attention(agent)
    _break_stage(agent, "think")
    _poison_deferred(agent)

    for _ in range(MAX_STIMULUS_RETRIES - 1):
        asyncio.run(runner._tick_once(wait_for_user=False))

    # Лимит не исчерпан: стимул остаётся отложенным, сообщений об отказе нет.
    assert agent._deferred_stimulus is not None
    assert runner._deferred_fail_count == MAX_STIMULUS_RETRIES - 1
    assert not bus.get_history(name_filter=Events.AGENT_THOUGHT)


def test_poison_stimulus_dropped_after_limit(runtime):
    agent, bus, runner = runtime
    _force_attention(agent)
    _break_stage(agent, "think")
    _poison_deferred(agent)

    for _ in range(MAX_STIMULUS_RETRIES):
        asyncio.run(runner._tick_once(wait_for_user=False))

    assert agent._deferred_stimulus is None
    assert runner._deferred_fail_count == 0
    drops = [
        event
        for event in bus.get_history(name_filter=Events.AGENT_THOUGHT)
        if "отпускаю" in (event.data or {}).get("text", "")
    ]
    assert drops, "человек должен получить честное объяснение"


def test_cycle_count_not_inflated_by_failures(runtime):
    """Неудачные ретраи не выдают себя за прожитые циклы."""
    agent, bus, runner = runtime
    _force_attention(agent)
    _break_stage(agent, "perceive")
    _poison_deferred(agent)

    before = agent.cycle_count
    for _ in range(MAX_STIMULUS_RETRIES):
        asyncio.run(runner._tick_once(wait_for_user=False))

    assert agent.cycle_count == before
    assert agent._deferred_stimulus is None


def test_success_resets_fail_counter(runtime):
    agent, bus, runner = runtime
    _force_attention(agent)
    agent._deferred_stimulus = {"text": "обычная мысль", "user_initiated": True}
    runner._deferred_fail_count = MAX_STIMULUS_RETRIES - 1

    asyncio.run(runner._tick_once(wait_for_user=False))

    assert agent._deferred_stimulus is None
    assert runner._deferred_fail_count == 0
