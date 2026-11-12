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
* a hard timeout kills the process tree;
* stdout/stderr are drained with bounded parent-memory capture and capped;
* the working directory is the workspace root.

Because of the honest limits above, the ``run_python`` action is marked
``dangerous=True`` and is meant to run behind the approval gate
(``DELAMAIN_APPROVAL_MODE=dangerous``): the entity proposes, the human
decides. Running it with the gate off is possible but not recommended.
"""

from __future__ import annotations

import codecs
import hashlib
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Dict, Optional, Tuple

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


class _OutputCapture:
    """Drain one binary pipe while retaining only a bounded text prefix."""

    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._parts: list[str] = []
        self._prefix_chars = 0
        self._total_chars = 0

    def _feed(self, data: bytes, *, final: bool = False) -> None:
        text = self._decoder.decode(data, final=final)
        self._total_chars += len(text)
        remaining = self._limit - self._prefix_chars
        if remaining > 0:
            prefix = text[:remaining]
            self._parts.append(prefix)
            self._prefix_chars += len(prefix)

    def drain(self) -> None:
        try:
            while True:
                chunk = self._stream.read(64 * 1024)
                if not chunk:
                    break
                self._feed(chunk)
            self._feed(b"", final=True)
        except (OSError, ValueError):
            # Forced pipe closure is expected when a timed-out reader is stuck.
            return
        finally:
            self.close()

    def close(self) -> None:
        try:
            self._stream.close()
        except OSError:
            pass

    def text(self) -> str:
        prefix = "".join(self._parts)
        if self._total_chars <= self._limit:
            return prefix
        return prefix + f"… [truncated, {self._total_chars} chars total]"


class _WindowsJob:
    """A Win32 job that retains descendants after their direct parent exits."""

    def __init__(self, process: subprocess.Popen) -> None:
        self._kernel32 = None
        self._handle = None
        if os.name != "nt":
            return

        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        if not kernel32.AssignProcessToJobObject(handle, int(process._handle)):
            kernel32.CloseHandle(handle)
            return
        self._kernel32 = kernel32
        self._handle = handle

    def terminate(self) -> bool:
        if self._kernel32 is None or self._handle is None:
            return False
        return bool(self._kernel32.TerminateJobObject(self._handle, 1))

    def close(self) -> None:
        if self._kernel32 is not None and self._handle is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


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
        # os.environ.get is case-insensitive on Windows, unlike comparing the
        # original keys with this whitelist. Keep canonical names in the child.
        env = {}
        for key in self.ENV_WHITELIST:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
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

    def source_sha256(self, path: str, source: Optional[bytes] = None) -> str:
        """Fingerprint current or planned source for an approval decision."""

        if source is None:
            _, source = self._resolve_script(path)
        return hashlib.sha256(source).hexdigest()

    @staticmethod
    def _kill_process_tree(
        process: subprocess.Popen, job: Optional[_WindowsJob] = None
    ) -> None:
        """Kill the child and its descendants on the supported host OS."""

        if os.name == "nt":
            if job is None or not job.terminate():
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5.0,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def run(self, path: str, *, expected_sha256: Optional[str] = None) -> RunOutcome:
        """Execute one workspace script and return its capped outcome.

        A non-zero exit code is a normal outcome, not an exception: the
        caller decides whether it means the step failed. A timeout kills the
        process and returns ``timed_out=True``. Approved runs execute the exact
        source snapshot whose digest was stored with the approval.
        """

        relative, source = self._resolve_script(path)
        if expected_sha256 is not None:
            actual_sha256 = self.source_sha256(path, source)
            if actual_sha256 != expected_sha256:
                raise RunnerError(f"script does not match approved content: {path}")

        target = self.sandbox.resolve(relative)
        snapshot: Optional[Path] = None
        if expected_sha256 is not None:
            fd, snapshot_name = tempfile.mkstemp(
                prefix=".delamain-approved-", suffix=".py", dir=str(target.parent)
            )
            snapshot = Path(snapshot_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(source)
            except Exception:
                try:
                    snapshot.unlink()
                except OSError:
                    pass
                raise
            target = snapshot

        started = time.perf_counter()
        job: Optional[_WindowsJob] = None
        try:
            process = subprocess.Popen(
                # -I implies -E, so PYTHONIOENCODING would be ignored;
                # -X utf8 survives and keeps her Cyrillic output readable.
                [sys.executable, "-I", "-X", "utf8", str(target)],
                cwd=str(self.sandbox.root),
                env=self._clean_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name != "nt",
            )
            job = _WindowsJob(process)
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_capture = _OutputCapture(process.stdout, self.output_chars)
            stderr_capture = _OutputCapture(process.stderr, self.output_chars)
            threads = [
                threading.Thread(target=stdout_capture.drain, daemon=True),
                threading.Thread(target=stderr_capture.drain, daemon=True),
            ]
            for thread in threads:
                thread.start()

            deadline = started + self.timeout_sec
            timed_out = False
            exit_code = -1
            try:
                exit_code = int(process.wait(timeout=self.timeout_sec))
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_process_tree(process, job)

            # A descendant can inherit a pipe after the direct child exits.
            # Keep the same deadline for readers instead of joining forever.
            for thread in threads:
                thread.join(max(0.0, deadline - time.perf_counter()))
            if any(thread.is_alive() for thread in threads):
                if not timed_out:
                    self._kill_process_tree(process, job)
                timed_out = True
                for thread in threads:
                    thread.join(5.0)
            if any(thread.is_alive() for thread in threads):
                stdout_capture.close()
                stderr_capture.close()
                for thread in threads:
                    thread.join(1.0)

            if process.poll() is None:
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._kill_process_tree(process, job)
                    process.wait()
            if timed_out:
                exit_code = -1

            duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
            return RunOutcome(
                path=relative,
                exit_code=exit_code,
                stdout=stdout_capture.text(),
                stderr=stderr_capture.text(),
                duration_ms=duration_ms,
                timed_out=timed_out,
            )
        finally:
            if job is not None:
                job.close()
            if snapshot is not None:
                try:
                    snapshot.unlink()
                except OSError:
                    pass


APPROVED_SHA256_ARG = "_approved_sha256"

__all__ = ["APPROVED_SHA256_ARG", "CodeRunner", "RunOutcome", "RunnerError"]
