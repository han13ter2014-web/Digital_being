import gzip
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core import checkpoint_serializer
from src.core.checkpoint_serializer import CheckpointSerializer


@pytest.fixture(params=[False, True], ids=["json", "gzip"])
def serializer(request, tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint_serializer, "get_logger", Mock())
    return CheckpointSerializer(str(tmp_path), max_checkpoints=2, compress=request.param)


def read_checkpoint(path, compress):
    opener = gzip.open if compress else open
    with opener(path, "rt", encoding="utf-8") as checkpoint:
        return json.load(checkpoint)


def test_successful_save_publishes_complete_file_before_pruning(serializer, monkeypatch):
    first = Path(serializer.save({"cycle": 1}, "agent", 1))
    second = Path(serializer.save({"cycle": 2}, "agent", 2))
    state = {"cycle": 3, "text": "Сохранено"}
    replace = os.replace
    published = []

    def inspect_replace(source, destination):
        source = Path(source)
        destination = Path(destination)
        assert source.parent == destination.parent
        assert source != destination
        assert source.suffix == ".tmp"
        assert first.exists()
        assert second.exists()
        assert not destination.exists()
        assert read_checkpoint(source, serializer.compress) == state
        replace(source, destination)
        published.append(destination)

    monkeypatch.setattr(checkpoint_serializer.os, "replace", inspect_replace)
    saved = Path(serializer.save(state, "agent", 3))

    assert published == [saved]
    assert read_checkpoint(saved, serializer.compress) == state
    assert not first.exists()
    assert second.exists()
    assert set(saved.parent.iterdir()) == {second, saved}
    assert serializer.list_checkpoints("agent") == [str(second), str(saved)]


@pytest.mark.parametrize("cycle", [2, 3], ids=["overwrite", "new-checkpoint"])
def test_replace_failure_preserves_all_checkpoints_and_removes_temp(serializer, monkeypatch, cycle):
    serializer.save({"cycle": 1}, "agent", 1)
    serializer.save({"cycle": 2}, "agent", 2)
    directory = Path(serializer.checkpoint_dir)
    before = {path: path.read_bytes() for path in directory.iterdir()}
    attempted_sources = []

    def fail_replace(source, destination):
        attempted_sources.append(Path(source))
        assert Path(source).exists()
        assert read_checkpoint(source, serializer.compress) == {"replacement": True}
        raise OSError("publication failed")

    monkeypatch.setattr(checkpoint_serializer.os, "replace", fail_replace)
    prune = Mock(wraps=serializer._prune_old_checkpoints)
    monkeypatch.setattr(serializer, "_prune_old_checkpoints", prune)

    with pytest.raises(OSError, match="publication failed"):
        serializer.save({"replacement": True}, "agent", cycle)

    assert attempted_sources
    assert all(not path.exists() for path in attempted_sources)
    assert {path: path.read_bytes() for path in directory.iterdir()} == before
    prune.assert_not_called()


def test_write_failure_cleans_temp_without_pruning(serializer, monkeypatch):
    serializer.save({"cycle": 1}, "agent", 1)
    serializer.save({"cycle": 2}, "agent", 2)
    directory = Path(serializer.checkpoint_dir)
    before = {path: path.read_bytes() for path in directory.iterdir()}

    def fail_open(*args, **kwargs):
        raise OSError("write failed")

    if serializer.compress:
        monkeypatch.setattr(checkpoint_serializer.gzip, "open", fail_open)
    else:
        monkeypatch.setattr(checkpoint_serializer, "open", fail_open, raising=False)

    with pytest.raises(OSError, match="write failed"):
        serializer.save({"cycle": 3}, "agent", 3)

    assert {path: path.read_bytes() for path in directory.iterdir()} == before


def test_overwrite_at_limit_does_not_prune_another_checkpoint(serializer):
    first = Path(serializer.save({"cycle": 1}, "agent", 1))
    second = Path(serializer.save({"cycle": 2}, "agent", 2))

    saved = serializer.save({"cycle": 2, "updated": True}, "agent", 2)

    assert Path(saved) == second
    assert read_checkpoint(second, serializer.compress) == {"cycle": 2, "updated": True}
    assert set(first.parent.iterdir()) == {first, second}


def test_single_checkpoint_limit_retains_new_publication(serializer):
    serializer.max_checkpoints = 1
    first = Path(serializer.save({"cycle": 1}, "agent", 1))
    second = Path(serializer.save({"cycle": 2}, "agent", 2))

    assert not first.exists()
    assert read_checkpoint(second, serializer.compress) == {"cycle": 2}
    assert list(second.parent.iterdir()) == [second]
