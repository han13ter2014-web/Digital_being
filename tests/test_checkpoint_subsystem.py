"""Failure-safety tests for the legacy CheckpointSubsystem public API."""

import json
from pathlib import Path
from unittest.mock import patch

from src.core.subsystems.checkpoint_manager import CheckpointSubsystem


class _Agent:
    name = "Probe"
    intelligence = 2
    success_streak = 0
    cycle_count = 2
    energy = 50.0
    completed_goals = 0


def _seed_checkpoint(directory: Path, cycle: int) -> Path:
    path = directory / f"Probe_cycle_{cycle}.json"
    path.write_text(json.dumps({"cycle_count": cycle}), encoding="utf-8")
    return path


def test_failed_save_preserves_previous_checkpoints(tmp_path: Path) -> None:
    oldest = _seed_checkpoint(tmp_path, 0)
    latest = _seed_checkpoint(tmp_path, 1)
    subsystem = CheckpointSubsystem(str(tmp_path), interval=10, max_checkpoints=1)

    with patch(
        "src.core.subsystems.checkpoint_manager.json.dump",
        side_effect=OSError("disk full"),
    ):
        result = subsystem.save(_Agent())

    assert result is None
    assert json.loads(oldest.read_text(encoding="utf-8")) == {"cycle_count": 0}
    assert json.loads(latest.read_text(encoding="utf-8")) == {"cycle_count": 1}
    assert not (tmp_path / "Probe_cycle_2.json").exists()
    assert not (tmp_path / "Probe_cycle_2.json.tmp").exists()
    assert subsystem.find_latest("Probe") == str(latest)


def test_successful_save_rotates_old_checkpoints(tmp_path: Path) -> None:
    oldest = _seed_checkpoint(tmp_path, 0)
    latest = _seed_checkpoint(tmp_path, 1)
    subsystem = CheckpointSubsystem(str(tmp_path), interval=10, max_checkpoints=1)

    result = subsystem.save(_Agent())

    assert result == str(tmp_path / "Probe_cycle_2.json")
    assert Path(result).exists()
    assert not oldest.exists()
    assert not latest.exists()
    assert subsystem.find_latest("Probe") == result


def test_non_numeric_checkpoint_name_does_not_break_legacy_save(tmp_path: Path) -> None:
    _seed_checkpoint(tmp_path, 1)
    unrelated = tmp_path / "Probe_cycle_notes.json"
    unrelated.write_text("keep me", encoding="utf-8")
    subsystem = CheckpointSubsystem(str(tmp_path), interval=10, max_checkpoints=2)

    result = subsystem.save(_Agent())

    assert result == str(tmp_path / "Probe_cycle_2.json")
    assert Path(result).is_file()
    assert subsystem.find_latest("Probe") == result
    assert unrelated.read_text(encoding="utf-8") == "keep me"


def test_legacy_checkpoint_path_cannot_escape_checkpoint_directory(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "checkpoints"
    subsystem = CheckpointSubsystem(str(directory), interval=10)
    agent = _Agent()
    agent.name = "../escaped"

    assert subsystem.save(agent) is None
    assert list(tmp_path.glob("escaped_cycle_*")) == []
