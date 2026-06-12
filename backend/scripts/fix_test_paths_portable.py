#!/usr/bin/env python3
"""
fix_test_paths_portable.py — v322w portable-test-paths sweep
============================================================
Rewrites hardcoded "/app/..." path literals in backend/tests/*.py to be
repo-relative. "/app" only exists in the dev container; on the DGX the
repo lives at ~/Trading-and-Analysis-Platform, so every test that did
`Path("/app/backend/services/x.py").read_text()` raised
FileNotFoundError (bit us in v322t-t1 AND v322u-t1).

Transform (per affected file):
  1. Inserts once, after the module docstring / __future__ imports:
         import pathlib as _pl
         _REPO_ROOT = str(_pl.Path(__file__).resolve().parents[2])
  2. Replaces string literals  "/app/<rest>"  with  (_REPO_ROOT + "/<rest>")
     — valid wherever a string literal is (Path(...), open(...), args,
     assignments).

Skips (left untouched):
  - comment lines
  - `sys.path.insert(...)` lines (harmless no-op paths)
  - literals containing "..." (docstring examples)
  - this script itself / non-test files

Safety: ast.parse() verification per file; any parse failure reverts
that file and reports. --check is a dry run.

USAGE (from repo root):
    .venv/bin/python backend/scripts/fix_test_paths_portable.py --check
    .venv/bin/python backend/scripts/fix_test_paths_portable.py --apply
"""
import ast
import re
import sys
from pathlib import Path

LITERAL_RE = re.compile(r"""(["'])/app/([^"']+)\1""")

HELPER = (
    "\n# v322w — portable test paths: this file previously hardcoded"
    ' "/app/..."\n'
    "# (dev-container path) which crashes on the DGX. Auto-fixed by\n"
    "# scripts/fix_test_paths_portable.py.\n"
    "import pathlib as _pl\n"
    "_REPO_ROOT = str(_pl.Path(__file__).resolve().parents[2])\n"
)


def _insert_line(src: str) -> int:
    """Line index (0-based, insert BEFORE it) after module docstring and
    any __future__ imports."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0
    line = 0
    for node in tree.body:
        if (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            line = node.end_lineno  # module docstring
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            line = node.end_lineno
            continue
        break
    return line


def transform(src: str):
    out_lines, n_replaced = [], 0
    for line in src.splitlines(keepends=True):
        stripped = line.lstrip()
        if (stripped.startswith("#") or "sys.path" in line
                or "..." in line and "/app/" in line):
            out_lines.append(line)
            continue

        def _sub(m):
            nonlocal n_replaced
            n_replaced += 1
            q, rest = m.group(1), m.group(2)
            return f'(_REPO_ROOT + {q}/{rest}{q})'

        out_lines.append(LITERAL_RE.sub(_sub, line))
    if n_replaced == 0:
        return src, 0
    new = "".join(out_lines)
    if "_REPO_ROOT = " not in new:
        lines = new.splitlines(keepends=True)
        at = _insert_line(src)
        lines.insert(at, HELPER)
        new = "".join(lines)
    return new, n_replaced


def main():
    apply = "--apply" in sys.argv
    root = Path.cwd()
    tests_dir = root / "backend" / "tests"
    if not tests_dir.is_dir():
        print("ABORT: run from the repo root"); sys.exit(2)

    total_files, total_repl, failures = 0, 0, []
    for f in sorted(tests_dir.glob("test_*.py")):
        src = f.read_text(encoding="utf-8")
        new, n = transform(src)
        if n == 0:
            continue
        total_files += 1
        total_repl += n
        if not apply:
            print(f"  would fix {f.name}: {n} literal(s)")
            continue
        try:
            ast.parse(new)
        except SyntaxError as e:
            failures.append(f"{f.name}: {e}")
            continue
        f.write_text(new, encoding="utf-8")
        print(f"  fixed {f.name}: {n} literal(s)")

    print(f"\n{'APPLY' if apply else 'CHECK'}: {total_files} file(s), "
          f"{total_repl} literal(s)")
    if failures:
        print("PARSE FAILURES (files left untouched):")
        for x in failures:
            print(f"  x {x}")
        sys.exit(1)
    if not apply:
        print("dry run — re-run with --apply to write")


if __name__ == "__main__":
    main()
