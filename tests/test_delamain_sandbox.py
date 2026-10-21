from pathlib import Path

import pytest

from src.delamain.sandbox import Sandbox, SandboxError


def test_write_read_roundtrip(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    info = sandbox.write_text("notes/a.txt", "привет\nмир\n")

    assert info["path"] == "notes/a.txt"
    assert info["created"] is True
    assert sandbox.read_text("notes/a.txt") == "привет\nмир\n"
    assert (tmp_path / "workspace" / "notes" / "a.txt").read_text(encoding="utf-8") == "привет\nмир\n"


def test_absolute_and_parent_paths_are_rejected(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")

    with pytest.raises(SandboxError):
        sandbox.read_text(str(tmp_path / "outside.txt"))
    with pytest.raises(SandboxError):
        sandbox.read_text("../outside.txt")
    with pytest.raises(SandboxError):
        sandbox.write_text("a/../../outside.txt", "x")


def test_write_is_confined_to_root(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    sandbox.write_text("a.txt", "inside")

    assert (tmp_path / "workspace" / "a.txt").is_file()
    assert not (tmp_path / "a.txt").exists()


def test_list_and_search(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    sandbox.write_text("one.txt", "hello world\nsecond line\n")
    sandbox.write_text("nested/two.py", "# TODO: fix this\n")
    sandbox.write_text("__pycache__/ignored.py", "TODO ignored\n")

    files = sandbox.list_files("**/*")
    paths = {item["path"] for item in files}
    assert "one.txt" in paths
    assert "nested/two.py" in paths
    assert "__pycache__/ignored.py" not in paths

    matches = sandbox.search_text("TODO")
    assert [match["path"] for match in matches] == ["nested/two.py"]
    assert matches[0]["line"] == 1


def test_size_and_binary_limits(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace", max_file_bytes=8)

    with pytest.raises(SandboxError):
        sandbox.write_text("big.txt", "123456789")

    target = tmp_path / "workspace" / "raw.bin"
    target.write_bytes(b"abc\x00def")
    with pytest.raises(SandboxError):
        sandbox.read_text("raw.bin")


def test_stat_and_missing_file(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    sandbox.write_text("a.txt", "abc")

    info = sandbox.stat("a.txt")
    assert info["bytes"] == 3
    assert info["is_file"] is True

    with pytest.raises(FileNotFoundError):
        sandbox.read_text("missing.txt")
