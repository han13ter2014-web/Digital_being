"""Bounded execution of small Python programs from the workspace.

This module is the *consciously chosen* extension of the Delamain sandbox:
the entity may write a small program into her workspace and run it. The file
sandbox itself (``sandbox.py``) stays file-only; execution lives here so the
boundary is visible in one place.

Honest limits — this is **not** a full OS sandbox:

* the child process runs as the same OS user as the agent;
* network access is **not** blocked at the OS level;
* a determined program can still touch the filesystem outside the workspace.

The guarantees this layer *does* give:

* only ``.py`` files inside the workspace can be started (the path goes
  through the same ``Sandbox`` policy as every other file operation);
* the child gets a cleaned environment (a small whitelist, no inherited
  secrets) plus ``-I`` (isolated mode: no user site-packages, no ``PYTHONPATH``);
* a hard timeout kills the process;
* stdout/stderr are captured and capped;
* the working directory is the workspace root.

Because of the honest limits above, the ``run_python`` action is marked
``dangerous=True`` and is meant to run behind the approval gate
(``DELAMAIN_APPROVAL_MODE=dangerous``): the entity proposes, the human
decides. Running it with the gate off is possible but not recommended.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .sandbox import Sandbox, SandboxError


class RunnerError(Exception):
    """An expected execution failure that should be shown to the planner."""


@dataclass
class RunOutcome:
    """The observable result of one finished (or killed) program run."""

    path: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
        }


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [truncated, {len(text)} chars total]"


def _tail(text: str, limit: int = 400) -> str:
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


class CodeRunner:
    """Run a workspace Python file under hard, visible limits."""

    # Only these variables are passed to the child. Everything else —
    # API keys, tokens, user-specific paths — stays with the parent.
    ENV_WHITELIST: Tuple[str, ...] = (
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "PATH",
    )

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        timeout_sec: float = 10.0,
        output_chars: int = 4000,
        max_code_bytes: int = 100_000,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        if output_chars <= 0:
            raise ValueError("output_chars must be positive")
        if max_code_bytes <= 0:
            raise ValueError("max_code_bytes must be positive")
        self.sandbox = sandbox
        self.timeout_sec = float(timeout_sec)
        self.output_chars = int(output_chars)
        self.max_code_bytes = int(max_code_bytes)

    def _clean_env(self) -> Dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key in self.ENV_WHITELIST
        }
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONNOUSERSITE"] = "1"
        # Do not litter her workspace with __pycache__ directories.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def _resolve_script(self, path: str) -> Tuple[str, bytes]:
        """Return ``(relative_path, source_bytes)`` for a runnable script."""

        if not str(path).lower().endswith(".py"):
            raise RunnerError(f"only .py files can be executed: {path!r}")
        target = self.sandbox.resolve(path)
        if target == self.sandbox.root:
            raise SandboxError("the workspace root is not a file")
        if not target.exists():
            raise FileNotFoundError(f"file not found: {path}")
        if not target.is_file():
            raise SandboxError(f"not a regular file: {path}")
        size = target.stat().st_size
        if size > self.max_code_bytes:
            raise RunnerError(
                f"script is too large: {size} bytes > {self.max_code_bytes}"
            )
        raw = target.read_bytes()
        if b"\x00" in raw[:4096]:
            raise SandboxError(f"binary files are not supported: {path}")
        return self.sandbox.relative(target), raw

    def run(self, path: str) -> RunOutcome:
        """Execute one workspace script and return its capped outcome.

        A non-zero exit code is a normal outcome, not an exception: the
        caller decides whether it means the step failed. A timeout kills the
        process and returns ``timed_out=True``.
        """

        relative, _source = self._resolve_script(path)
        target = self.sandbox.resolve(relative)
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                # -I implies -E, so PYTHONIOENCODING would be ignored;
                # -X utf8 survives and keeps her Cyrillic output readable.
                [sys.executable, "-I", "-X", "utf8", str(target)],
                cwd=str(self.sandbox.root),
                env=self._clean_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
            stdout = (exc.stdout or b"") if isinstance(exc.stdout, (bytes, type(None))) else b""
            stderr = (exc.stderr or b"") if isinstance(exc.stderr, (bytes, type(None))) else b""
            return RunOutcome(
                path=relative,
                exit_code=-1,
                stdout=_cap(stdout.decode("utf-8", errors="replace"), self.output_chars),
                stderr=_cap(stderr.decode("utf-8", errors="replace"), self.output_chars),
                duration_ms=duration_ms,
                timed_out=True,
            )

        duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return RunOutcome(
            path=relative,
            exit_code=int(completed.returncode),
            stdout=_cap(completed.stdout.decode("utf-8", errors="replace"), self.output_chars),
            stderr=_cap(completed.stderr.decode("utf-8", errors="replace"), self.output_chars),
            duration_ms=duration_ms,
            timed_out=False,
        )


__all__ = ["CodeRunner", "RunOutcome", "RunnerError"]
