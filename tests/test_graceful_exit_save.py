"""graceful_exit_save никогда не сохраняет из живого потока жизни.

Сохранение параллельно с работающим тиком роняет сериализацию
(мутируемые dict) и угрожает непрерывности чекпоинтов. Гарди в main.py:
сначала мягкая остановка и ожидание, повторное сохранение — только если
поток завершился и сам сохранить не смог.
"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

from main import graceful_exit_save


def _make_runtime(*, finished, saved_on_stop, wait_result):
    runtime = SimpleNamespace(
        finished=threading.Event(),
        saved_on_stop=saved_on_stop,
        agent=Mock(),
        request_shutdown=Mock(),
        wait=Mock(return_value=wait_result),
    )
    if finished:
        runtime.finished.set()
    return runtime


def test_hung_thread_is_not_saved_from_foreign_thread():
    runtime = _make_runtime(
        finished=False, saved_on_stop=False, wait_result=False
    )
    ok = graceful_exit_save(runtime, wait_timeout=0.01)
    assert ok is False
    runtime.request_shutdown.assert_called_once()
    runtime.agent.save_state.assert_not_called()


def test_live_thread_that_stops_in_time_skips_extra_save():
    runtime = _make_runtime(
        finished=False, saved_on_stop=True, wait_result=True
    )
    ok = graceful_exit_save(runtime, wait_timeout=0.01)
    assert ok is True
    runtime.request_shutdown.assert_called_once()
    runtime.agent.save_state.assert_not_called()


def test_finished_runtime_uses_retry_save_only_when_runner_failed():
    runtime = _make_runtime(
        finished=True, saved_on_stop=False, wait_result=True
    )
    ok = graceful_exit_save(runtime)
    assert ok is True
    runtime.agent.save_state.assert_called_once_with(force=True)


def test_finished_and_saved_runtime_is_untouched():
    runtime = _make_runtime(
        finished=True, saved_on_stop=True, wait_result=True
    )
    ok = graceful_exit_save(runtime)
    assert ok is True
    runtime.agent.save_state.assert_not_called()


def test_retry_save_failure_is_reported_not_raised():
    runtime = _make_runtime(
        finished=True, saved_on_stop=False, wait_result=True
    )
    runtime.agent.save_state.side_effect = RuntimeError("disk full")
    ok = graceful_exit_save(runtime)
    assert ok is False
