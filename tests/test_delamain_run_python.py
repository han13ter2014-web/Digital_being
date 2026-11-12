"""Tests for the sandbox execution stage: run_python, append_file, make_dir.

The stage lets the entity write a small program into her workspace and run
it. The guarantees under test: only .py files inside the workspace start,
the child gets a cleaned environment, a timeout kills it, output is capped,
and the action is dangerous so the approval gate can hold it.
"""

import os
from pathlib import Path

import pytest

from src.delamain.actions import ActionRegistry
from src.delamain.memory import MemoryStore
from src.delamain.models import ActionRequest
from src.delamain.planner import HeuristicPlanner
from src.delamain.runner import CodeRunner
from src.delamain.runtime import DelamainRuntime
from src.delamain.sandbox import Sandbox, SandboxError


# ----------------------------------------------------------------------
# Sandbox: append_text
# ----------------------------------------------------------------------


def test_append_text_creates_and_appends(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    first = sandbox.append_text("notes/log.txt", "строка 1\n")
    assert first["created"] is True
    second = sandbox.append_text("notes/log.txt", "строка 2\n")
    assert second["created"] is False
    assert second["bytes"] == first["appended_bytes"] + second["appended_bytes"]
    text = sandbox.read_text("notes/log.txt")
    assert text == "строка 1\nстрока 2\n"


def test_append_text_respects_combined_size_limit(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace", max_file_bytes=10)
    sandbox.append_text("a.txt", "12345")
    with pytest.raises(SandboxError):
        sandbox.append_text("a.txt", "678901")


def test_append_text_rejects_binary_target_and_escape(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    (sandbox.root / "bin.dat").write_bytes(b"\x00\x01\x02")
    with pytest.raises(SandboxError):
        sandbox.append_text("bin.dat", "x")
    with pytest.raises(SandboxError):
        sandbox.append_text("../outside.txt", "x")


# ----------------------------------------------------------------------
# Sandbox: make_dir
# ----------------------------------------------------------------------


def test_make_dir_creates_nested_and_is_idempotent(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    first = sandbox.make_dir("a/b/c")
    assert first["created"] is True
    assert (sandbox.root / "a" / "b" / "c").is_dir()
    second = sandbox.make_dir("a/b/c")
    assert second["created"] is False


def test_make_dir_rejects_escape_root_and_file_conflict(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    with pytest.raises(SandboxError):
        sandbox.make_dir("../outside")
    with pytest.raises(SandboxError):
        sandbox.make_dir(".")
    sandbox.write_text("f.txt", "x")
    with pytest.raises(SandboxError):
        sandbox.make_dir("f.txt")


# ----------------------------------------------------------------------
# CodeRunner
# ----------------------------------------------------------------------


def _write_script(sandbox: Sandbox, name: str, source: str) -> None:
    sandbox.write_text(name, source)


def test_runner_executes_and_captures_utf8(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    _write_script(sandbox, "hello.py", "print('привет, мир')\n")
    runner = CodeRunner(sandbox, timeout_sec=20.0)
    outcome = runner.run("hello.py")
    assert outcome.exit_code == 0
    assert outcome.timed_out is False
    assert "привет, мир" in outcome.stdout
    assert outcome.duration_ms > 0
    # PYTHONDONTWRITEBYTECODE: no __pycache__ litter in her workspace.
    assert not (sandbox.root / "__pycache__").exists()


def test_runner_reports_nonzero_exit(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    _write_script(
        sandbox, "fail.py", "import sys; sys.stderr.write('boom'); sys.exit(3)\n"
    )
    runner = CodeRunner(sandbox, timeout_sec=20.0)
    outcome = runner.run("fail.py")
    assert outcome.exit_code == 3
    assert "boom" in outcome.stderr


def test_runner_kills_on_timeout(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    _write_script(sandbox, "loop.py", "import time; time.sleep(30)\n")
    runner = CodeRunner(sandbox, timeout_sec=1.0)
    outcome = runner.run("loop.py")
    assert outcome.timed_out is True
    assert outcome.exit_code == -1


def test_runner_bounds_parent_memory_for_large_output(tmp_path: Path) -> None:
    import tracemalloc

    sandbox = Sandbox(tmp_path / "workspace")
    _write_script(sandbox, "output.py", "print('x' * 3_000_000)\n")
    runner = CodeRunner(sandbox, timeout_sec=20.0, output_chars=100)

    tracemalloc.start()
    try:
        outcome = runner.run("output.py")
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert outcome.exit_code == 0
    assert outcome.stdout.startswith("x" * 100)
    assert "chars total" in outcome.stdout
    assert peak_bytes < 1_000_000


@pytest.mark.parametrize("parent_waits", [True, False])
def test_runner_timeout_kills_spawned_children(
    tmp_path: Path, parent_waits: bool
) -> None:
    import time

    sandbox = Sandbox(tmp_path / "workspace")
    _write_script(
        sandbox,
        "child.py",
        "import time\n"
        "time.sleep(1.5)\n"
        "open('child-sentinel.txt', 'w').write('survived')\n",
    )
    parent_wait = "time.sleep(30)\n" if parent_waits else ""
    _write_script(
        sandbox,
        "parent.py",
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-I', '-X', 'utf8', 'child.py'])\n"
        + parent_wait,
    )
    runner = CodeRunner(sandbox, timeout_sec=0.5)

    outcome = runner.run("parent.py")
    time.sleep(2.0)

    assert outcome.timed_out is True
    assert not (sandbox.root / "child-sentinel.txt").exists()


def test_runner_cleans_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DELAMAIN_TEST_SECRET", "s3cret")
    sandbox = Sandbox(tmp_path / "workspace")
    _write_script(
        sandbox, "env.py", "import os; print(os.environ.get('DELAMAIN_TEST_SECRET'))\n"
    )
    runner = CodeRunner(sandbox, timeout_sec=20.0)
    outcome = runner.run("env.py")
    assert outcome.exit_code == 0
    assert "s3cret" not in outcome.stdout
    assert "None" in outcome.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows environment semantics")
def test_runner_preserves_system_root_regardless_of_environment_key_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SystemRoot", raising=False)
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    runner = CodeRunner(Sandbox(tmp_path / "workspace"))

    env = runner._clean_env()

    assert env["SystemRoot"] == r"C:\Windows"


def test_runner_rejects_non_py_escape_missing_and_large(tmp_path: Path) -> None:
    sandbox = Sandbox(tmp_path / "workspace")
    sandbox.write_text("note.txt", "not code")
    runner = CodeRunner(sandbox, timeout_sec=20.0, max_code_bytes=10)
    with pytest.raises(Exception, match="only .py"):
        runner.run("note.txt")
    with pytest.raises(SandboxError):
        runner.run("../outside.py")
    with pytest.raises(FileNotFoundError):
        runner.run("missing.py")
    sandbox.write_text("big.py", "# " + "x" * 100)
    with pytest.raises(Exception, match="too large"):
        runner.run("big.py")


# ----------------------------------------------------------------------
# run_python action and the approval gate
# ----------------------------------------------------------------------


def _registry(tmp_path: Path, **runner_kwargs) -> ActionRegistry:
    sandbox = Sandbox(tmp_path / "workspace")
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    runner = CodeRunner(sandbox, **runner_kwargs)
    return ActionRegistry.default(sandbox, memory, code_runner=runner)


def test_run_python_action_success(tmp_path: Path) -> None:
    registry = _registry(tmp_path, timeout_sec=20.0)
    registry.execute("write_file", {"path": "s.py", "content": "print(6 * 7)\n"})
    result = registry.execute("run_python", {"path": "s.py"})
    assert result.ok is True
    assert result.output["exit_code"] == 0
    assert "42" in result.output["stdout"]


def test_run_python_action_failure_is_observable(tmp_path: Path) -> None:
    registry = _registry(tmp_path, timeout_sec=20.0)
    registry.execute(
        "write_file",
        {"path": "s.py", "content": "raise SystemExit('не выходит')\n"},
    )
    result = registry.execute("run_python", {"path": "s.py"})
    assert result.ok is False
    assert "exit" in (result.error or "")


def test_run_python_action_timeout_is_observable(tmp_path: Path) -> None:
    registry = _registry(tmp_path, timeout_sec=1.0)
    registry.execute(
        "write_file",
        {"path": "s.py", "content": "import time; time.sleep(30)\n"},
    )
    result = registry.execute("run_python", {"path": "s.py"})
    assert result.ok is False
    assert "timed out" in (result.error or "")


def test_run_python_is_dangerous_and_gated(tmp_path: Path) -> None:
    """A plan with run_python waits for approval and runs nothing yet."""
    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="dangerous",
    ) as runtime:
        specs = {spec["name"]: spec for spec in runtime.describe_actions()}
        assert specs["run_python"]["dangerous"] is True
        assert specs["append_file"]["dangerous"] is True
        assert specs["make_dir"]["dangerous"] is False

        runtime.registry.execute(
            "write_file",
            {"path": "mark.py", "content": "open('sentinel.txt', 'w').write('ran')\n"},
        )
        result = runtime.run_task(
            "run",
            task_id="task-run-1",
            plan=[ActionRequest("run_python", {"path": "mark.py"})],
        )
        assert result.ok is False
        assert "approval required" in (result.error or "")
        assert result.pending_approval is not None
        assert result.pending_approval["dangerous_actions"] == ["run_python"]
        # Nothing executed before the human decides.
        assert not (root / "sentinel.txt").exists()

        approved = runtime.memory.approve_approval(str(result.pending_approval["id"]))
        assert approved is not None and approved["status"] == "approved"
        finished = runtime.run_approved(str(result.pending_approval["id"]))
        assert finished.ok is True
        assert (root / "sentinel.txt").read_text(encoding="utf-8") == "ran"


def test_run_python_rejects_content_changed_after_approval(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="dangerous",
    ) as runtime:
        runtime.sandbox.write_text(
            "mark.py", "open('sentinel.txt', 'w').write('approved')\n"
        )
        pending = runtime.run_task(
            "run",
            plan=[
                ActionRequest(
                    "run_python",
                    {"path": "mark.py", "_approved_sha256": "forged"},
                )
            ],
        )
        approval_id = pending.pending_approval["id"]
        bound_args = pending.pending_approval["plan"][0]["args"]
        assert bound_args["_approved_sha256"] != "forged"
        assert len(bound_args["_approved_sha256"]) == 64

        runtime.sandbox.write_text(
            "mark.py", "open('sentinel.txt', 'w').write('changed')\n"
        )
        runtime.memory.approve_approval(approval_id)
        finished = runtime.run_approved(approval_id)

        assert finished.ok is False
        assert "does not match approved content" in (finished.error or "")
        assert not (root / "sentinel.txt").exists()


def test_run_python_executes_snapshot_if_source_changes_during_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="dangerous",
    ) as runtime:
        runtime.sandbox.write_text(
            "mark.py", "open('sentinel.txt', 'w').write('approved')\n"
        )
        pending = runtime.run_task(
            "run", plan=[ActionRequest("run_python", {"path": "mark.py"})]
        )
        approval_id = pending.pending_approval["id"]
        runtime.memory.approve_approval(approval_id)
        real_popen = subprocess.Popen

        def change_source_before_launch(*args, **kwargs):
            runtime.sandbox.write_text(
                "mark.py", "open('sentinel.txt', 'w').write('changed')\n"
            )
            return real_popen(*args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", change_source_before_launch)
        finished = runtime.run_approved(approval_id)

        assert finished.ok is True
        assert (root / "sentinel.txt").read_text(encoding="utf-8") == "approved"
        assert not list(root.glob(".delamain-approved-*.py"))


def test_legacy_run_python_approval_without_content_binding_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="dangerous",
    ) as runtime:
        runtime.sandbox.write_text(
            "mark.py", "open('sentinel.txt', 'w').write('legacy')\n"
        )
        pending = runtime.memory.create_approval(
            task_id="legacy",
            task="run",
            plan=[{"action": "run_python", "args": {"path": "mark.py"}}],
            dangerous_actions=["run_python"],
        )
        approval_id = pending["id"]
        runtime.memory.approve_approval(approval_id)

        finished = runtime.run_approved(approval_id)

        assert finished.ok is False
        assert "without content binding" in (finished.error or "")
        assert not (root / "sentinel.txt").exists()


def test_run_python_approval_covers_script_written_by_same_plan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="dangerous",
    ) as runtime:
        pending = runtime.run_task(
            "write and run",
            plan=[
                ActionRequest(
                    "write_file",
                    {
                        "path": "mark.py",
                        "content": "open('sentinel.txt', 'w').write('planned')\n",
                    },
                ),
                ActionRequest("run_python", {"path": "mark.py"}),
            ],
        )
        approval_id = pending.pending_approval["id"]
        runtime.memory.approve_approval(approval_id)

        finished = runtime.run_approved(approval_id)

        assert finished.ok is True
        assert (root / "sentinel.txt").read_text(encoding="utf-8") == "planned"


# ----------------------------------------------------------------------
# Heuristic planner commands
# ----------------------------------------------------------------------


def test_planner_parses_new_commands() -> None:
    planner = HeuristicPlanner()

    plan = planner.plan("запусти scripts/hello.py")
    assert [(step.action, step.args) for step in plan] == [
        ("run_python", {"path": "scripts/hello.py"}),
    ]

    plan = planner.plan("допиши в notes/a.txt: ещё строка")
    assert [(step.action, step.args) for step in plan] == [
        ("append_file", {"path": "notes/a.txt", "content": "ещё строка"}),
    ]

    plan = planner.plan("создай папку notes/archive")
    assert [(step.action, step.args) for step in plan] == [
        ("make_dir", {"path": "notes/archive"}),
    ]

    plan = planner.plan("run tools/x.py")
    assert plan[0].action == "run_python"
