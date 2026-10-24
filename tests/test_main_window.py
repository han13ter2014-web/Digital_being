"""Тесты логики окна без Tk.

Окно создаёт Tk-объекты только в своём потоке (при ``show()``), поэтому
экземпляр можно создать в тесте: проверяется логика — какие события
уходят в шину и когда кнопка подтверждения действительно подтверждает.
"""

import time

import pytest

from src.core.event_bus import Events
from src.ui.main_window import SPEED_LABELS, MainWindow


class RecordingBus:
    def __init__(self):
        self.published = []
        self.subscriptions = []

    def subscribe(self, event, handler=None):
        self.subscriptions.append(event)

    def unsubscribe(self, *args, **kwargs):
        return None

    async def publish(self, event, data=None, **kwargs):
        self.published.append((event, dict(data or {})))

    def publish_sync(self, event, data=None, **kwargs):
        self.published.append((event, dict(data or {})))

    def names(self):
        return [name for name, _ in self.published]

    def last(self, event):
        for name, data in reversed(self.published):
            if name == event:
                return data
        return None


@pytest.fixture()
def window():
    bus = RecordingBus()
    win = MainWindow(bus, "Alpha")
    return win, bus


# ============================================================
# Управление темпом
# ============================================================


def test_speed_buttons_publish_event(window):
    win, bus = window
    win._action_set_speed("fast")

    assert bus.last(Events.SPEED_CHANGED) == {"mode": "fast"}


def test_all_speed_labels_exist(window):
    win, bus = window
    for mode in ("live", "fast", "max"):
        win._action_set_speed(mode)
        assert bus.last(Events.SPEED_CHANGED) == {"mode": mode}
    assert set(SPEED_LABELS) >= {"live", "fast", "max", "step"}


def test_pause_toggles_based_on_state(window):
    win, bus = window

    # По умолчанию считаем, что не на паузе → просим паузу.
    win._action_toggle_pause()
    assert bus.last(Events.PAUSE_REQUESTED) == {}

    # Теперь состояние «на паузе» → просим продолжить.
    win._apply_status({"paused": True})
    win._action_toggle_pause()
    assert bus.last(Events.RESUME_REQUESTED) == {}


def test_step_and_save_publish(window):
    win, bus = window
    win._action_step()
    win._action_save()
    assert Events.STEP_REQUESTED in bus.names()
    assert Events.SAVE_REQUESTED in bus.names()


# ============================================================
# Жизнь: окно только просит
# ============================================================


def test_dream_button_requests_not_kills(window):
    win, bus = window
    win._action_request_dream()

    payload = bus.last(Events.LIFE_REQUEST)
    assert payload["kind"] == "dream"


def test_terminate_button_requests_not_kills(window):
    win, bus = window
    win._action_request_termination()

    payload = bus.last(Events.LIFE_REQUEST)
    assert payload["kind"] == "terminate"


def test_quit_publishes_shutdown(window):
    win, bus = window
    win._action_quit()
    assert bus.last(Events.SHUTDOWN_REQUESTED) == {}


# ============================================================
# Подтверждение ухода
# ============================================================


def _prompt(win, *, phrase="Alpha", cooldown=0.0):
    win._apply_life_prompt(
        {
            "request_id": "dream-1",
            "kind": "dream",
            "phrase": phrase,
            "cooldown_sec": cooldown,
            "description": "Агент уйдёт в сон.",
        }
    )


def test_wrong_phrase_is_not_sent_as_confirmation(window):
    win, bus = window
    _prompt(win)

    assert win._try_confirm_life("да") is False
    assert Events.LIFE_CONFIRM not in bus.names()


def test_correct_phrase_is_sent_as_confirmation(window):
    win, bus = window
    _prompt(win)

    assert win._try_confirm_life("Alpha") is True
    payload = bus.last(Events.LIFE_CONFIRM)
    assert payload["request_id"] == "dream-1"
    assert payload["phrase"] == "Alpha"


def test_phrase_is_case_and_space_insensitive(window):
    win, bus = window
    _prompt(win)

    assert win._try_confirm_life("  alpha  ") is True
    assert bus.last(Events.LIFE_CONFIRM) is not None


def test_confirmation_blocked_during_cooldown(window):
    win, bus = window
    _prompt(win, cooldown=10.0)

    # Фраза верная, но пауза ещё не выдержана.
    assert win._try_confirm_life("Alpha") is True
    assert Events.LIFE_CONFIRM not in bus.names()


def test_confirmation_allowed_after_cooldown(window):
    win, bus = window
    _prompt(win, cooldown=0.01)
    time.sleep(0.05)

    assert win._try_confirm_life("Alpha") is True
    assert bus.last(Events.LIFE_CONFIRM) is not None


def test_no_prompt_means_no_confirmation(window):
    win, bus = window
    assert win._try_confirm_life("Alpha") is False
    assert Events.LIFE_CONFIRM not in bus.names()


def test_cancel_life_publishes_request_id(window):
    win, bus = window
    _prompt(win)
    win._action_cancel_life()

    assert bus.last(Events.LIFE_CANCEL) == {"request_id": "dream-1"}


def test_life_result_clears_prompt(window):
    win, bus = window
    _prompt(win)
    assert win._life_prompt is not None

    win._apply_life_result({"ok": True, "message": "Агент уснул."})
    assert win._life_prompt is None


def test_failed_life_result_keeps_prompt(window):
    win, bus = window
    _prompt(win)

    win._apply_life_result({"ok": False, "message": "Слишком рано."})
    assert win._life_prompt is not None


# ============================================================
# Показатели
# ============================================================


def test_status_snapshot_is_stored(window):
    win, bus = window
    win.push_status({"cycle": 42, "energy": 100, "paused": False})
    win._poll_incoming()

    assert win._status_snapshot["cycle"] == 42


def test_status_tracks_life_state(window):
    win, bus = window
    win._apply_status({"life_state": "dormant"})
    assert win._last_life_state == "dormant"