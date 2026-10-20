"""Статический сканер гигиены кода Digital Being.

Ищет то, что не ловит ``compileall``, но что реально мешает:

* неиспользуемые импорты (кроме реэкспорта через ``__all__``);
* ``except:`` без типа (перехватывает и KeyboardInterrupt);
* изменяемые значения по умолчанию (``def f(x=[])``);
* повторные определения функций/классов в одной области (второе молча
  перекрывает первое);
* ``except ...: pass`` — молчаливое проглатывание ошибок;
* TODO/FIXME.

Запуск:

    python tools/hygiene_scan.py
    python tools/hygiene_scan.py --json report.json
    python tools/hygiene_scan.py --path src --path config

Сканер не является линтером и не претендует на полноту: он ищет только
перечисленные выше классы проблем.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Set


@dataclass
class Issue:
    path: str
    line: int
    kind: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.kind}] {self.message}"


@dataclass
class FileReport:
    path: str
    issues: List[Issue] = field(default_factory=list)


def _iter_py_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            yield path
            continue
        if path.is_dir():
            for candidate in sorted(path.rglob("*.py")):
                if "__pycache__" in candidate.parts:
                    continue
                yield candidate


def _imported_names(tree: ast.AST) -> Dict[str, int]:
    """Собирает имена, которые связывают импорты: {имя: строка}."""
    names: Dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                names[bound] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                names[alias.asname or alias.name] = node.lineno
    return names


def _used_names(tree: ast.AST) -> Set[str]:
    used: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # os.path.join -> базовое имя os
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
    return used


def _all_exported(tree: ast.AST) -> Set[str]:
    exported: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "__all__" in targets and isinstance(node.value, (ast.List, ast.Tuple)):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        exported.add(elt.value)
    return exported


def _mutable_defaults(tree: ast.AST, path: str) -> List[Issue]:
    issues: List[Issue] = []
    mutable_literals = (ast.List, ast.Dict, ast.Set)
    mutable_calls = {"list", "dict", "set", "bytearray", "OrderedDict", "deque"}

    def check_args(args: ast.arguments, path: str):
        for default in list(args.defaults) + [d for d in args.kw_defaults if d]:
            if isinstance(default, mutable_literals):
                issues.append(Issue(path, default.lineno, "mutable-default",
                                    "Изменяемое значение по умолчанию"))
            elif (isinstance(default, ast.Call)
                  and isinstance(default.func, ast.Name)
                  and default.func.id in mutable_calls):
                issues.append(Issue(path, default.lineno, "mutable-default",
                                    f"Изменяемое значение по умолчанию: {default.func.id}()"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            check_args(node.args, path=path)
    return issues


def _duplicate_defs(tree: ast.AST, path: str) -> List[Issue]:
    issues: List[Issue] = []

    def is_overload_or_accessor(node) -> bool:
        for decorator in getattr(node, "decorator_list", []):
            # @property / @x.setter / @x.getter / @x.deleter
            if isinstance(decorator, ast.Attribute) and decorator.attr in {
                "setter", "getter", "deleter",
            }:
                return True
            if isinstance(decorator, ast.Name) and decorator.id == "overload":
                return True
        return False

    def scan_scope(body: List[ast.stmt], scope: str) -> None:
        seen: Dict[str, int] = {}
        overloaded: Set[str] = set()
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_overload = any(
                    isinstance(decorator, ast.Name) and decorator.id == "overload"
                    for decorator in getattr(node, "decorator_list", [])
                )
                if (node.name in seen
                        and not is_overload_or_accessor(node)
                        and node.name not in overloaded):
                    issues.append(Issue(
                        path, node.lineno, "duplicate-def",
                        f"Повторное определение {scope}{node.name} "
                        f"(первое — строка {seen[node.name]})",
                    ))
                seen[node.name] = node.lineno
                if is_overload:
                    overloaded.add(node.name)
                if isinstance(node, ast.ClassDef):
                    scan_scope(node.body, f"{scope}{node.name}.")

    scan_scope(tree.body, "")
    return issues


def _error_handling(tree: ast.AST, path: str) -> List[Issue]:
    issues: List[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            issues.append(Issue(path, node.lineno, "bare-except",
                                "except без типа перехватывает всё, включая SystemExit"))
        body = node.body
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            issues.append(Issue(path, node.lineno, "silent-except",
                                "except ...: pass — ошибка исчезает бесследно"))
    return issues


def _todos(path: Path) -> List[Issue]:
    issues: List[Issue] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return issues
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#") and ("TODO" in line or "FIXME" in line):
            issues.append(Issue(str(path), number, "todo", stripped[:120]))
    return issues


def scan_file(path: Path) -> FileReport:
    report = FileReport(path=str(path))
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as exc:
        report.issues.append(Issue(str(path), 0, "parse-error", str(exc)))
        return report

    # В __init__.py импорт часто реэкспорт, его нельзя считать мёртвым.
    if path.name != "__init__.py":
        source_lines = source.splitlines()
        imports = _imported_names(tree)
        used = _used_names(tree) | _all_exported(tree)
        for name, line in sorted(imports.items(), key=lambda item: item[1]):
            if name in used or name.startswith("_"):
                continue
            # Явная пометка "импорт нужен ради побочного эффекта/проверки".
            text = source_lines[line - 1] if 0 < line <= len(source_lines) else ""
            if "# noqa" in text:
                continue
            report.issues.append(Issue(str(path), line, "unused-import",
                                      f"Импорт '{name}' не используется"))

    report.issues.extend(_mutable_defaults(tree, str(path)))
    report.issues.extend(_duplicate_defs(tree, str(path)))
    report.issues.extend(_error_handling(tree, str(path)))
    report.issues.extend(_todos(path))
    return report


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", default=None,
                        help="Файл или каталог (можно несколько раз)")
    parser.add_argument("--json", default=None, help="Сохранить отчёт в JSON")
    parser.add_argument("--kind", action="append", default=None,
                        help="Показывать только эти типы проблем")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    paths = [Path(p) if Path(p).is_absolute() else root / p
             for p in (args.path or ["src", "config", "tools", "main.py",
                                     "main_tray.py", "tests"])]

    reports = [scan_file(path) for path in _iter_py_files(paths)]
    issues = [issue for report in reports for issue in report.issues]
    if args.kind:
        allowed = set(args.kind)
        issues = [issue for issue in issues if issue.kind in allowed]

    issues.sort(key=lambda issue: (issue.path, issue.line, issue.kind))
    by_kind: Dict[str, int] = {}
    for issue in issues:
        by_kind[issue.kind] = by_kind.get(issue.kind, 0) + 1

    for issue in issues:
        print(issue)

    print()
    print(f"Файлов: {len(reports)}; проблем: {len(issues)}")
    for kind, count in sorted(by_kind.items(), key=lambda item: -item[1]):
        print(f"  {kind}: {count}")

    if args.json:
        payload = {
            "files": len(reports),
            "issues": [asdict(issue) for issue in issues],
            "by_kind": by_kind,
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON: {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
