"""Self-check of verify_*.py stands.

Auto-discovers ``verify_*.py`` in local historical evidence folders.
Verifiers anchored to ``git show HEAD:...`` are historical one-shot
instruments; verifiers without a HEAD anchor are eternal and must pass
honestly and must fail on semantic corruption of the product modules they
exercise. All checks run in an isolated git worktree at HEAD; the live
tree, historical evidence and live data/ stay untouched. Environments
without the local evidence folders (for example a fresh CI checkout)
skip these tests honestly.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEAD_ANCHOR_RE = re.compile(r"[\"']HEAD:")
SRC_FILE_RE = re.compile(r"[\"'](src/[A-Za-z0-9_./-]+\.py)[\"']")
RUN_TIMEOUT = 300


def discover_verifiers():
    discovered = []
    paths = list(ROOT.glob("k*_decomposition_*/verify_*.py"))
    # Локальный архив не является checkout-зависимостью, но если владелец
    # убрал туда исторические доказательства, self-check обязан их найти,
    # а не молча превратить пять проверок в skipped.
    paths += list(ROOT.glob("_archive/*/history/k*_decomposition_*/verify_*.py"))
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8")
        discovered.append(
            {
                "name": path.name,
                # В изолированном worktree verifier остаётся на исходном
                # уровне: исторические скрипты сами вычисляют ROOT по
                # parents[1]. source — отдельный путь к архивной копии.
                "evidence": path.parent.name,
                "source": path.parent,
                "eternal": not HEAD_ANCHOR_RE.search(source),
            }
        )
    return discovered


def _git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def verification_surface(source):
    files = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src."):
                    files.add(alias.name.replace(".", "/") + ".py")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "src."
        ):
            files.add(node.module.replace(".", "/") + ".py")
    for match in SRC_FILE_RE.finditer(source):
        files.add(match.group(1))
    return sorted(files)


def _module_file(wt, rel_path):
    return wt.joinpath(*rel_path.split("/"))


def _pick_target_name(source, verifier_source):
    functions = [
        node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
    ]
    for node in functions:
        if node.name in verifier_source:
            return node.name
    return functions[0].name if functions else None


def _mutated_source(source, kind, target_name=None):
    if kind == "extra_import":
        return source + "\nimport statistics\n"
    if kind == "reorder_functions":
        tree = ast.parse(source)
        indexes = [
            i for i, node in enumerate(tree.body) if isinstance(node, ast.FunctionDef)
        ]
        if len(indexes) < 2:
            return source
        first, second = indexes[0], indexes[1]
        tree.body[first], tree.body[second] = tree.body[second], tree.body[first]
        ast.fix_missing_locations(tree)
        return ast.unparse(tree)
    if kind == "remove_import":
        tree = ast.parse(source)
        imports = [
            node
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
        ]
        if not imports:
            return source
        tree.body.remove(imports[-1])
        ast.fix_missing_locations(tree)
        return ast.unparse(tree)
    if kind == "substitute_body":
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == target_name:
                node.body = [ast.Return(value=ast.Constant(value=""))]
                ast.fix_missing_locations(tree)
                return ast.unparse(tree)
        return source
    raise AssertionError(f"unknown corruption kind: {kind}")


@contextmanager
def corrupted_module(wt, module, kind, verifier_source):
    target = _module_file(wt, module)
    original = target.read_bytes()
    text = original.decode("utf-8")
    target_name = None
    if kind == "substitute_body":
        target_name = _pick_target_name(text, verifier_source)
        if target_name is None:
            yield False
            return
    mutated = _mutated_source(text, kind, target_name)
    if mutated == text:
        yield False
        return
    try:
        target.write_text(mutated, encoding="utf-8", newline="\n")
        yield True
    finally:
        target.write_bytes(original)


def run_verifier(wt, row, case):
    evidence = wt / row["evidence"]
    sandbox = evidence / f"selfcheck_{case}_{uuid.uuid4().hex[:8]}"
    env = os.environ.copy()
    env["DIGITAL_BEING_DATA_DIR"] = str(sandbox)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(evidence / row["name"])],
        cwd=str(wt),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=RUN_TIMEOUT,
    )


@pytest.fixture(scope="module")
def isolated_worktree():
    base = Path(tempfile.mkdtemp(prefix="k15_t2_selfcheck_"))
    eternal = [row for row in discover_verifiers() if row["eternal"]]
    if not eternal:
        shutil.rmtree(base, ignore_errors=True)
        pytest.skip("no eternal verifiers in this checkout")
    wt = base / "wt"
    done = _git("worktree", "add", "--detach", str(wt), "HEAD")
    if done.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        pytest.skip(f"git worktree unavailable: {(done.stderr or done.stdout).strip()}")
    for row in eternal:
        target = wt / row["evidence"]
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row["source"] / row["name"], target / row["name"])
    yield wt
    _git("worktree", "remove", "--force", str(wt))
    _git("worktree", "prune")
    shutil.rmtree(base, ignore_errors=True)


def eternal_rows():
    rows = [row for row in discover_verifiers() if row["eternal"]]
    if not rows:
        pytest.skip("no eternal verifiers discovered")
    return rows


def test_classification_discovers_known_verifiers():
    rows = discover_verifiers()
    if not rows:
        pytest.skip("no k*_decomposition_* verifier evidence in this checkout")
    by_name = {row["name"]: row for row in rows}
    assert "verify_persistence_paths.py" in by_name
    assert by_name["verify_persistence_paths.py"]["eternal"] is True
    historical = {row["name"] for row in rows if not row["eternal"]}
    assert historical >= {
        "verify_goals_move.py",
        "verify_persistence_move.py",
        "verify_creation_move.py",
        "verify_evolution_runtime.py",
    }


def test_eternal_verifiers_pass_honestly(isolated_worktree):
    for row in eternal_rows():
        proc = run_verifier(isolated_worktree, row, "honest")
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]


def test_eternal_verifiers_catch_substituted_body(isolated_worktree):
    caught = []
    for row in eternal_rows():
        source = (row["source"] / row["name"]).read_text(encoding="utf-8")
        for rel in verification_surface(source):
            target = _module_file(isolated_worktree, rel)
            if not target.exists():
                continue
            with corrupted_module(
                isolated_worktree, rel, "substitute_body", source
            ) as applied:
                if not applied:
                    continue
                proc = run_verifier(
                    isolated_worktree, row, f"body_{rel.replace('/', '_')}"
                )
                if proc.returncode != 0:
                    caught.append(rel)
                    break
    assert caught, "no eternal verifier caught substituted body"


def test_eternal_verifiers_catch_removed_import(isolated_worktree):
    caught = []
    for row in eternal_rows():
        source = (row["source"] / row["name"]).read_text(encoding="utf-8")
        for rel in verification_surface(source):
            target = _module_file(isolated_worktree, rel)
            if not target.exists():
                continue
            with corrupted_module(
                isolated_worktree, rel, "remove_import", source
            ) as applied:
                if not applied:
                    continue
                proc = run_verifier(
                    isolated_worktree, row, f"import_{rel.replace('/', '_')}"
                )
                if proc.returncode != 0:
                    caught.append(rel)
                    break
    assert caught, "no eternal verifier caught removed import"


def test_eternal_verifiers_record_cosmetic_corruptions(isolated_worktree):
    verdicts = {}
    for row in eternal_rows():
        source = (row["source"] / row["name"]).read_text(encoding="utf-8")
        surface = [
            rel
            for rel in verification_surface(source)
            if _module_file(isolated_worktree, rel).exists()
        ]
        assert surface
        for kind in ("extra_import", "reorder_functions"):
            applied_rel = None
            for rel in surface:
                with corrupted_module(isolated_worktree, rel, kind, source) as applied:
                    if not applied:
                        continue
                    proc = run_verifier(
                        isolated_worktree,
                        row,
                        f"{kind}_{rel.replace('/', '_')}",
                    )
                    verdicts[kind] = proc.returncode
                    applied_rel = rel
                    break
            assert applied_rel, kind
    assert set(verdicts) == {"extra_import", "reorder_functions"}
