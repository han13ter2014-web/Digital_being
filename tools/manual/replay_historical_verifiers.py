"""Replay the sixteen one-shot K14 verifiers at their original pins.

For every step the detached worktree HEAD stays at the parent commit while
its index and working tree receive exactly that step's diff. This recreates
the pre-commit context expected by the unmodified historical verifiers.
Honest and semantic-corruption runs use separate data sandboxes. Logs and a
JSON report live below tmp/ in the current repository; worktrees are removed
in ``finally`` and the live source tree and data/ are never used as targets.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = "k14_decomposition_2026-11-07"
RUN_TIMEOUT = 300

# parent = expected HEAD; step = expected working tree. The corruption target
# is a real extracted function whose semantic change each verifier must catch.
MANIFEST = (
    {
        "verifier": "verify_reflection_move.py",
        "parent": "5fd4604",
        "step": "e00151b",
        "module": "src/core/agent_reflection.py",
        "function": "reflect_impl",
    },
    {
        "verifier": "verify_goals_move.py",
        "parent": "e00151b",
        "step": "e17170c",
        "module": "src/core/agent_goals.py",
        "function": "_generate_initial_goals_impl",
    },
    {
        "verifier": "verify_body_move.py",
        "parent": "e17170c",
        "step": "d5b53d3",
        "module": "src/core/agent_body.py",
        "function": "_get_adaptive_cost_impl",
    },
    {
        "verifier": "verify_persistence_move.py",
        "parent": "d5b53d3",
        "step": "3903e92",
        "module": "src/core/agent_persistence.py",
        "function": "save_state_impl",
    },
    {
        "verifier": "verify_effector_move.py",
        "parent": "3903e92",
        "step": "c39c4da",
        "module": "src/core/agent_effector.py",
        "function": "_record_core_life_episode_impl",
    },
    {
        "verifier": "verify_selection_move.py",
        "parent": "c39c4da",
        "step": "3cc8ba1",
        "module": "src/core/agent_selection.py",
        "function": "_social_candidates_impl",
    },
    {
        "verifier": "verify_communication_move.py",
        "parent": "3cc8ba1",
        "step": "16bd920",
        "module": "src/core/agent_communication.py",
        "function": "tick_communication_impl",
    },
    {
        "verifier": "verify_handlers_move.py",
        "parent": "16bd920",
        "step": "497109d",
        "module": "src/core/agent_handlers.py",
        "function": "_act_explore_impl",
    },
    {
        "verifier": "verify_creative_exploration_move.py",
        "parent": "497109d",
        "step": "87d4e2a",
        "module": "src/core/agent_exploration.py",
        "function": "_is_learnable_impl",
    },
    {
        "verifier": "verify_emotional_move.py",
        "parent": "87d4e2a",
        "step": "de79580",
        "module": "src/core/agent_emotional.py",
        "function": "_emotions_from_death_risk_impl",
    },
    {
        "verifier": "verify_evolution_move.py",
        "parent": "de79580",
        "step": "e7eaf31",
        "module": "src/core/agent_evolution.py",
        "function": "_evolution_tick_impl",
    },
    {
        "verifier": "verify_evolution_runtime.py",
        "parent": "de79580",
        "step": "e7eaf31",
        "module": "src/core/agent_evolution.py",
        "function": "_evolution_tick_impl",
    },
    {
        "verifier": "verify_properties_move.py",
        "parent": "e7eaf31",
        "step": "b9241a2",
        "module": "src/core/agent_properties.py",
        "function": "energy_get_impl",
    },
    {
        "verifier": "verify_act_move.py",
        "parent": "b9241a2",
        "step": "2d53629",
        "module": "src/core/agent_act.py",
        "function": "act_impl",
    },
    {
        "verifier": "verify_autonomous_tick_move.py",
        "parent": "2d53629",
        "step": "54ec3f5",
        "module": "src/core/agent_autonomous_tick.py",
        "function": "autonomous_tick_impl",
    },
    {
        "verifier": "verify_creation_move.py",
        "parent": "54ec3f5",
        "step": "d6a3c3e",
        "module": "src/core/agent_creation.py",
        "function": "init_impl",
    },
)


def discover_evidence():
    """Find local read-only verifier evidence, including the archived copy."""
    candidates = [ROOT / EVIDENCE_DIR]
    candidates.extend(sorted((ROOT / "_archive").glob(f"*/history/{EVIDENCE_DIR}")))
    for candidate in candidates:
        if all((candidate / row["verifier"]).is_file() for row in MANIFEST):
            return candidate
    return None


def _git(*args, cwd=ROOT, input_bytes=None, check=True):
    return subprocess.run(
        ["git", *map(str, args)],
        cwd=str(cwd),
        input=input_bytes,
        capture_output=True,
        check=check,
    )


def _resolve_output(value):
    output = (
        Path(value).resolve()
        if value
        else ROOT / "tmp" / f"t2b_replay_{uuid.uuid4().hex[:10]}"
    )
    sandbox_root = (ROOT / "tmp").resolve()
    if output == sandbox_root or sandbox_root not in output.parents:
        raise ValueError("output must be a new directory inside the repository tmp/")
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    output.mkdir(parents=True)
    return output


def _prepare_worktree(path, parent, step, evidence, verifiers):
    """Create parent HEAD plus the exact post-step index and working tree."""
    _git("worktree", "add", "--detach", path, parent)
    patch = _git("diff", "--binary", parent, step, "--", ".").stdout
    _git("apply", "--index", "-", cwd=path, input_bytes=patch)
    actual_head = _git("rev-parse", "HEAD", cwd=path).stdout.decode().strip()
    expected_head = _git("rev-parse", parent).stdout.decode().strip()
    if actual_head != expected_head:
        raise AssertionError(f"HEAD pin mismatch: {actual_head} != {expected_head}")
    remaining = _git("diff", "--exit-code", step, "--", ".", cwd=path, check=False)
    if remaining.returncode != 0:
        raise AssertionError("working tree does not match the historical step")
    target_evidence = path / EVIDENCE_DIR
    target_evidence.mkdir(parents=True, exist_ok=True)
    for verifier in verifiers:
        shutil.copy2(evidence / verifier, target_evidence / verifier)
    # Two historical guards hash an outside-sandbox knowledge file before and
    # after the probe. A clean worktree has no ignored data/, so provide a
    # deterministic local sentinel instead of reading the owner's live data.
    live_data_sentinel = path / "data" / "knowledge_base.json"
    live_data_sentinel.parent.mkdir(parents=True, exist_ok=True)
    live_data_sentinel.write_text(
        '{"t2b": "outside-sandbox sentinel"}\n', encoding="utf-8"
    )


# The original creation verifier constructs four beings in one process. Its
# noise detector compares only the first two, so an accidental match there
# followed by a different random quest in runs three/four fails an honest
# replay. Reset the legacy global RNG at the same boundary in every genesis;
# the evidence file and the implementation under test remain byte-identical.
_CREATION_REPLAY_BOOTSTRAP = r"""
import random
import runpy
import sys

from src.core.subsystems.soul_controller import SoulController

_historical_tick = SoulController.tick


def _deterministic_historical_tick(self, *args, **kwargs):
    random.seed(1501)
    return _historical_tick(self, *args, **kwargs)


SoulController.tick = _deterministic_historical_tick
_verifier_path = sys.argv[1]
sys.argv = [_verifier_path]
runpy.run_path(_verifier_path, run_name="__main__")
"""


def _run_verifier(worktree, verifier, case, log_dir):
    evidence = worktree / EVIDENCE_DIR
    sandbox = evidence / f"sandbox_{case}_{Path(verifier).stem}"
    env = os.environ.copy()
    env["DIGITAL_BEING_DATA_DIR"] = str(sandbox.resolve())
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    verifier_path = str(evidence / verifier)
    command = [sys.executable, verifier_path]
    if verifier == "verify_creation_move.py":
        command = [sys.executable, "-c", _CREATION_REPLAY_BOOTSTRAP, verifier_path]
    try:
        proc = subprocess.run(
            command,
            cwd=str(worktree),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RUN_TIMEOUT,
            check=False,
        )
        exit_code = proc.returncode
        output = proc.stdout + proc.stderr
        error = ""
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        output = (exc.stdout or "") + (exc.stderr or "")
        error = f"timeout after {RUN_TIMEOUT}s"
    log_path = log_dir / f"{Path(verifier).stem}_{case}.log"
    log_path.write_text(f"exit_code={exit_code}\n{error}\n{output}", encoding="utf-8")
    return {
        "exit_code": exit_code,
        "log": str(log_path.relative_to(ROOT)),
        "timed_out": exit_code is None,
    }


def _corrupt_function(path, function_name):
    """Insert an early raise without reformatting the historical module."""
    original = path.read_bytes()
    source = original.decode("utf-8")
    tree = ast.parse(source)
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if target is None or not target.body:
        raise AssertionError(f"corruption target not found: {path}:{function_name}")
    lines = source.splitlines(keepends=True)
    first_statement = target.body[0]
    indent = " " * first_statement.col_offset
    lines.insert(
        first_statement.lineno - 1,
        f'{indent}raise AssertionError("T2b semantic corruption: {function_name}")\n',
    )
    path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return original


def replay(evidence=None, output=None, only=None, corruption=True):
    """Run selected replay rows and return a machine-readable report."""
    evidence = Path(evidence).resolve() if evidence else discover_evidence()
    if evidence is None:
        raise FileNotFoundError("all sixteen historical verifier files are required")
    selected = [row for row in MANIFEST if not only or row["verifier"] in only]
    unknown = set(only or ()) - {row["verifier"] for row in MANIFEST}
    if unknown:
        raise ValueError(f"unknown verifiers: {sorted(unknown)}")
    if not selected:
        raise ValueError("no verifiers selected")
    output = _resolve_output(output)
    log_dir = output / "logs"
    log_dir.mkdir()
    report = {
        "ok": False,
        "evidence": str(evidence),
        "evidence_sha256": {},
        "rows": [],
    }
    groups = {}
    for row in selected:
        groups.setdefault((row["parent"], row["step"]), []).append(row)

    try:
        for (parent, step), rows in groups.items():
            worktree = output / f"worktree_{step}"
            try:
                _prepare_worktree(
                    worktree,
                    parent,
                    step,
                    evidence,
                    [row["verifier"] for row in rows],
                )
                for row in rows:
                    verifier = row["verifier"]
                    report["evidence_sha256"][verifier] = hashlib.sha256(
                        (evidence / verifier).read_bytes()
                    ).hexdigest()
                    honest = _run_verifier(worktree, verifier, "honest", log_dir)
                    corrupted = None
                    if corruption:
                        target = worktree.joinpath(*row["module"].split("/"))
                        original = _corrupt_function(target, row["function"])
                        try:
                            corrupted = _run_verifier(
                                worktree, verifier, "corruption", log_dir
                            )
                        finally:
                            target.write_bytes(original)
                    row_ok = honest["exit_code"] == 0 and (
                        not corruption
                        or (
                            corrupted["exit_code"] is not None
                            and corrupted["exit_code"] != 0
                        )
                    )
                    report["rows"].append(
                        {
                            **row,
                            "honest": honest,
                            "corruption": corrupted,
                            "ok": row_ok,
                        }
                    )
            finally:
                _git("worktree", "remove", "--force", worktree, check=False)
                _git("worktree", "prune", check=False)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    honest_passed = sum(row["honest"]["exit_code"] == 0 for row in report["rows"])
    corruption_caught = sum(
        row["corruption"] is not None
        and row["corruption"]["exit_code"] is not None
        and row["corruption"]["exit_code"] != 0
        for row in report["rows"]
    )
    report["summary"] = {
        "selected": len(selected),
        "completed": len(report["rows"]),
        "honest_passed": honest_passed,
        "corruption_caught": corruption_caught,
    }
    report["ok"] = (
        not report.get("error")
        and len(report["rows"]) == len(selected)
        and all(row["ok"] for row in report["rows"])
    )
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report["report_path"] = str(report_path)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", help="directory with original verify_*.py")
    parser.add_argument("--output", help="new report directory below repository tmp/")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="run only this verifier; may be repeated",
    )
    parser.add_argument("--honest-only", action="store_true")
    parser.add_argument("--list", action="store_true", help="print the replay manifest")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps(MANIFEST, ensure_ascii=False, indent=2))
        return 0
    try:
        report = replay(
            evidence=args.evidence,
            output=args.output,
            only=set(args.only),
            corruption=not args.honest_only,
        )
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"T2b setup failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": report["ok"], **report["summary"]}, ensure_ascii=False))
    print(report["report_path"])
    if report.get("error"):
        print(report["error"], file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
