"""Тесты слоя приложения: снимок состояния для окна.

Функции чистые, поэтому проверяются без Tk и без агента.
"""

from src.app.status import (
    build_status_snapshot,
    energy_bar,
    format_duration,
    format_status_lines,
)


# ============================================================
# Полоска и длительность
# ============================================================


def test_energy_bar_full_and_empty():
    assert energy_bar(200, 200, 10) == "▓" * 10
    assert energy_bar(0, 200, 10) == "░" * 10
    assert energy_bar(100, 200, 10) == "▓" * 5 + "░" * 5


def test_energy_bar_clamps_out_of_range():
    # Перелив и отрицательное значение не должны ломать вид.
    assert energy_bar(400, 200, 10) == "▓" * 10
    assert energy_bar(-5, 200, 10) == "░" * 10


def test_energy_bar_zero_maximum_is_safe():
    assert energy_bar(50, 0, 4) == "░" * 4


def test_format_duration():
    assert format_duration(45) == "45с"
    assert format_duration(90) == "1м 30с"
    assert format_duration(3600 + 12 * 60) == "1ч 12м"


# ============================================================
# Снимок
# ============================================================


class FakeMentalModels:
    concepts = {"a": 1, "b": 2, "c": 3}


class FakeAgent:
    name = "Alpha"
    cycle_count = 1234
    intelligence = 47
    energy = 138.0
    parent_name = "Parent"

    class _Goals:
        def __init__(self):
            self.calls = 0

    def __init__(self):
        self.mental_models = FakeMentalModels()
        self.life_guard = None

    def get_goals_status(self):
        return {"total": 7, "completed": 3, "active": "Изучить время"}


def test_snapshot_has_all_keys():
    snapshot = build_status_snapshot(FakeAgent(), None)
    for key in (
        "name",
        "cycle",
        "intelligence",
        "energy",
        "max_energy",
        "concepts",
        "goals_total",
        "goals_completed",
        "goals_active",
        "uptime_sec",
        "rss_mb",
        "speed_mode",
        "speed_interval_sec",
        "paused",
        "life_state",
        "seed_folder",
        "parent_name",
        "pending_life_request",
    ):
        assert key in snapshot, f"нет ключа {key}"


def test_snapshot_reads_agent_values():
    snapshot = build_status_snapshot(FakeAgent(), None, started_at=1000.0, now=1120.0)
    assert snapshot["name"] == "Alpha"
    assert snapshot["cycle"] == 1234
    assert snapshot["intelligence"] == 47
    assert snapshot["energy"] == 138.0
    assert snapshot["concepts"] == 3
    assert snapshot["goals_total"] == 7
    assert snapshot["goals_completed"] == 3
    assert snapshot["uptime_sec"] == 120.0
    assert snapshot["parent_name"] == "Parent"


def test_snapshot_survives_broken_agent():
    """Окно не должно падать из-за отсутствующего поля у агента."""

    class Broken:
        name = "B"
        cycle_count = 0
        energy = 0
        intelligence = 0

        def get_goals_status(self):
            raise RuntimeError("нет целей")

    snapshot = build_status_snapshot(Broken(), None)
    assert snapshot["name"] == "B"
    assert snapshot["goals_total"] == 0


class FakeSpeedRunner:
    def get_speed_status(self):
        return {
            "mode": "fast",
            "interval_sec": 0.5,
            "paused": True,
        }


def test_snapshot_includes_speed():
    snapshot = build_status_snapshot(FakeAgent(), FakeSpeedRunner())
    assert snapshot["speed_mode"] == "fast"
    assert snapshot["speed_interval_sec"] == 0.5
    assert snapshot["paused"] is True


# ============================================================
# Строки панели
# ============================================================


def test_status_lines_are_readable():
    snapshot = build_status_snapshot(
        FakeAgent(), FakeSpeedRunner(), started_at=0.0, now=4320.0
    )
    snapshot["life_state"] = "alive"
    lines = format_status_lines(snapshot)
    text = "\n".join(lines)

    assert "Цикл         1234" in text
    assert "Интеллект    47" in text
    assert "Концепций    3" in text
    assert "Цели         3/7" in text
    assert "Ускорение" in text          # режим fast
    assert "пауза" in text
    assert "жив" in text
    assert "Родитель     Parent" in text


def test_status_lines_labels_dormant():
    snapshot = build_status_snapshot(FakeAgent(), None)
    snapshot["life_state"] = "dormant"
    text = "\n".join(format_status_lines(snapshot))
    assert "спит" in text

# ============================================================
# Контур в панели
# ============================================================

class FakeLoopCloser:
    def status(self):
        return {
            "last_action": "explore",
            "last_effect": True,
            "stuck_actions": [],
        }


class AgentWithLoop(FakeAgent):
    def __init__(self):
        super().__init__()
        self.loop_closer = FakeLoopCloser()


def test_snapshot_reports_loop_state():
    snapshot = build_status_snapshot(AgentWithLoop(), None)
    assert snapshot["last_action"] == "explore"
    assert snapshot["last_effect"] is True
    assert snapshot["stuck_actions"] == []


def test_status_lines_show_action_effect():
    snapshot = build_status_snapshot(AgentWithLoop(), None)
    text = "\n".join(format_status_lines(snapshot))
    assert "Действие     explore" in text
    assert "✓ есть" in text


def test_status_lines_show_stuck_actions():
    snapshot = build_status_snapshot(FakeAgent(), None)
    snapshot["last_action"] = "explore"
    snapshot["last_effect"] = False
    snapshot["stuck_actions"] = ["explore", "synthesis"]
    text = "\n".join(format_status_lines(snapshot))
    assert "— нет" in text
    assert "Тупики" in text


def test_status_lines_show_maturity():
    snapshot = build_status_snapshot(FakeAgent(), None)
    snapshot["maturity_met"] = 2
    snapshot["maturity_total"] = 6
    snapshot["maturity_is_mature"] = False
    text = "\n".join(format_status_lines(snapshot))
    assert "Зрелость     2/6" in text


def test_status_lines_mark_mature_agent():
    snapshot = build_status_snapshot(FakeAgent(), None)
    snapshot["maturity_met"] = 6
    snapshot["maturity_total"] = 6
    snapshot["maturity_is_mature"] = True
    text = "\n".join(format_status_lines(snapshot))
    assert "можно раздавать" in text
