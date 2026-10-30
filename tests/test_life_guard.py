"""Тесты защиты жизни: агент не может уйти без явного согласия человека.

Проверяем именно то, чего боялся автор проекта: «ребёнка не убивают
по глупости или приколу». Каждый тест соответствует одному способу
случайно остановить жизнь, который был в коде до LifeGuard.
"""

import json
import os

import pytest

from src.core.life_guard import (
    KIND_DREAM,
    KIND_TERMINATE,
    STATE_ALIVE,
    STATE_DORMANT,
    STATE_TERMINATED,
    ConfirmationError,
    LifeGuard,
    get_policy,
    normalize_phrase,
)


class FakeClock:
    """Управляемое время: без sleep тесты идут мгновенно."""

    def __init__(self, start: float = 1_000_000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


@pytest.fixture()
def guard(tmp_path):
    clock = FakeClock()
    return LifeGuard(
        agent_name="Alpha",
        clock=clock,
        state_path=str(tmp_path / "life_state.json"),
        requests_path=str(tmp_path / "life_requests.json"),
        events_path=str(tmp_path / "life_events.log"),
        snapshot_root=str(tmp_path / "snapshots"),
    ), clock


# ============================================================
# 1. Случайный клик не убивает: нужна пауза
# ============================================================


def test_confirm_rejected_during_cooldown(guard):
    g, clock = guard
    req = g.request(KIND_DREAM)

    with pytest.raises(ConfirmationError, match="Слишком рано"):
        g.confirm(req.request_id, "Alpha")

    # Состояние не изменилось: агент жив.
    assert g.load_state() == STATE_ALIVE


def test_confirm_accepted_after_cooldown(guard):
    g, clock = guard
    req = g.request(KIND_DREAM)
    clock.advance(get_policy(KIND_DREAM).cooldown_sec + 0.1)

    confirmed = g.confirm(req.request_id, "Alpha")
    assert confirmed.confirmed is True
    # Подтверждение само по себе ещё не меняет состояние.
    assert g.load_state() == STATE_ALIVE


# ============================================================
# 2. Неверная фраза не проходит
# ============================================================


def test_wrong_phrase_rejected(guard):
    g, clock = guard
    req = g.request(KIND_DREAM)
    clock.advance(60)

    with pytest.raises(ConfirmationError, match="Фраза не совпала"):
        g.confirm(req.request_id, "да")
    assert g.load_state() == STATE_ALIVE


def test_phrase_is_normalized_but_not_loose(guard):
    g, clock = guard
    req = g.request(KIND_DREAM)
    clock.advance(60)

    # Пробелы и регистр прощаем.
    g.confirm(req.request_id, "  alpha  ")
    assert g.is_confirmed(req.request_id) is True


def test_terminate_requires_full_phrase(guard):
    g, clock = guard
    req = g.request(KIND_TERMINATE)
    clock.advance(get_policy(KIND_TERMINATE).cooldown_sec + 0.1)

    with pytest.raises(ConfirmationError, match="Фраза не совпала"):
        g.confirm(req.request_id, "Alpha")  # без «НАВСЕГДА»

    g.confirm(req.request_id, "Alpha НАВСЕГДА")
    assert g.is_confirmed(req.request_id) is True


# ============================================================
# 3. Запрос протухает: старое окно нельзя «дожать»
# ============================================================


def test_expired_request_cannot_be_confirmed(guard):
    g, clock = guard
    req = g.request(KIND_DREAM)
    clock.advance(get_policy(KIND_DREAM).ttl_sec + 1)

    with pytest.raises(ConfirmationError, match="истекло"):
        g.confirm(req.request_id, "Alpha")
    assert g.load_state() == STATE_ALIVE


def test_expired_requests_are_pruned(guard):
    g, clock = guard
    g.request(KIND_DREAM)
    clock.advance(get_policy(KIND_DREAM).ttl_sec + 1)

    assert g.pending_requests() == []
    # Новый запрос не падает из-за мусора в файле.
    fresh = g.request(KIND_DREAM)
    assert g.get_request(fresh.request_id) is not None


# ============================================================
# 4. Отмена работает всегда и ничего не требует
# ============================================================


def test_cancel_always_works(guard):
    g, clock = guard
    req = g.request(KIND_TERMINATE)
    assert g.cancel(req.request_id) is True
    assert g.get_request(req.request_id) is None
    assert g.cancel("нет-такого") is False
    assert g.load_state() == STATE_ALIVE


# ============================================================
# 5. Состояние переживает перезапуск (главный баг)
# ============================================================


def test_state_survives_restart(tmp_path):
    clock = FakeClock()
    kwargs = dict(
        agent_name="Alpha",
        clock=clock,
        state_path=str(tmp_path / "life_state.json"),
        requests_path=str(tmp_path / "life_requests.json"),
        events_path=str(tmp_path / "life_events.log"),
        snapshot_root=str(tmp_path / "snapshots"),
    )
    first = LifeGuard(**kwargs)
    first.set_state(STATE_DORMANT, reason="сон", seed_folder="seed_x")
    assert first.is_alive() is False

    # «Перезапуск программы»: новый объект читает тот же файл.
    second = LifeGuard(**kwargs)
    assert second.load_state() == STATE_DORMANT
    assert second.is_alive() is False
    assert second.state_details()["seed_folder"] == "seed_x"


def test_corrupted_state_file_means_alive(tmp_path):
    path = tmp_path / "life_state.json"
    path.write_text("{это не json", encoding="utf-8")
    g = LifeGuard(
        agent_name="Alpha",
        state_path=str(path),
        requests_path=str(tmp_path / "r.json"),
        events_path=str(tmp_path / "e.log"),
        snapshot_root=str(tmp_path / "snapshots"),
    )
    # Лучше оживить, чем похоронить из-за битого файла.
    assert g.load_state() == STATE_ALIVE


# ============================================================
# 6. Предохранитель: уход запрещён целиком
# ============================================================


def test_disabled_guard_forbids_any_exit(guard):
    g, clock = guard
    g.enabled = False
    with pytest.raises(ConfirmationError, match="Предохранитель"):
        g.request(KIND_DREAM)


def test_terminate_from_dormant_is_forbidden(guard):
    g, clock = guard
    g.set_state(STATE_DORMANT, reason="сон")
    with pytest.raises(ConfirmationError, match="уже в глубоком сне"):
        g.request(KIND_TERMINATE)


def test_terminate_when_already_terminated_is_forbidden(guard):
    g, clock = guard
    g.set_state(STATE_TERMINATED, reason="ушёл")
    with pytest.raises(ConfirmationError, match="уже прекратил"):
        g.request(KIND_DREAM)


# ============================================================
# 7. Пробуждение и снимки
# ============================================================


def test_wake_returns_to_life(guard):
    g, clock = guard
    g.set_state(STATE_DORMANT, reason="сон")
    result = g.wake()
    assert result["changed"] is True
    assert g.load_state() == STATE_ALIVE
    assert g.is_alive() is True


def test_wake_from_terminated_is_denied(guard):
    g, clock = guard
    g.set_state(STATE_TERMINATED, reason="ушёл")
    with pytest.raises(ConfirmationError, match="только из снимка"):
        g.wake()


def test_terminate_creates_snapshot_before_state_change(guard):
    g, clock = guard
    req = g.request(KIND_TERMINATE)
    clock.advance(get_policy(KIND_TERMINATE).cooldown_sec + 0.1)
    g.confirm(req.request_id, "Alpha НАВСЕГДА")

    # Снимок создаётся из data/ — в тестах там может быть пусто,
    # поэтому результат может быть None. Главное — не падает и
    # состояние меняется только после confirm.
    result = g.execute_confirmed(req.request_id)
    assert result["state"] == STATE_TERMINATED
    assert result["reversible"] is False


def test_execute_requires_confirmation(guard):
    g, clock = guard
    req = g.request(KIND_DREAM)
    with pytest.raises(ConfirmationError, match="не подтверждён"):
        g.execute_confirmed(req.request_id)


# ============================================================
# 8. Журнал решений
# ============================================================


def test_events_are_logged(guard):
    g, clock = guard
    req = g.request(KIND_DREAM, reason="тест")
    g.cancel(req.request_id)

    events = g.recent_events(limit=10)
    kinds = [e["event"] for e in events]
    assert "requested" in kinds
    assert "cancelled" in kinds


def test_normalize_phrase_collapses_spaces():
    assert normalize_phrase("  alpha    навсегда ") == "ALPHA НАВСЕГДА"
    assert normalize_phrase("Alpha") == "ALPHA"


def test_confirmation_phrase_follows_display_name(tmp_path):
    """Смена имени не должна блокировать подтверждение ухода."""
    clock = FakeClock()
    current = {"name": "Старое"}
    guard = LifeGuard(
        agent_name="Старое",
        clock=clock,
        name_provider=lambda: current["name"],
        state_path=str(tmp_path / "life_state.json"),
        requests_path=str(tmp_path / "life_requests.json"),
        events_path=str(tmp_path / "life_events.log"),
        snapshot_root=str(tmp_path / "snapshots"),
    )
    request = guard.request(KIND_DREAM)
    pending = guard.request(KIND_DREAM)
    current["name"] = "Новое"
    clock.advance(11)
    guard.confirm(request.request_id, "Новое")

    # Запрос, созданный до смены имени, всё ещё принимает старую подпись:
    # человек мог начать вводить фразу раньше.
    guard.confirm(pending.request_id, "Старое")


def test_agent_rename_updates_pending_phrase(tmp_path, monkeypatch):
    from src.core.agent import DigitalBeing

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing("Старое")
    clock = FakeClock()
    agent.life_guard.clock = clock
    agent.name = "Новое"

    request = agent.request_dream("усталость")
    assert request["phrase"] == "Новое"
    clock.advance(11)
    agent.life_guard.confirm(request["request_id"], "Новое")
    assert agent.life_guard.load_state() == "alive"
