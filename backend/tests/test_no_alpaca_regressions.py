"""
Regression guard — prevents Alpaca from silently creeping back into the
live-data path.

If any NEW file ever:
  • imports the alpaca SDK (`from alpaca.... import ...`)
  • calls `alpaca_service.get_quote / get_bars / ...` outside the approved
    shim file

…this test fails loudly in CI before the change lands.

The shim at `services/alpaca_service.py` is the ONE approved home for
legacy BC — it just delegates everything to IBDataProvider. New code must
use `from services.ib_data_provider import get_live_data_service` instead.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # /app/backend

# Files that are allowed to mention Alpaca (the shim, legacy executor shim,
# these tests themselves, and docs). Everything else must be Alpaca-free.
ALLOWED_FILES = {
    "services/alpaca_service.py",            # shim — delegates to IB
    "services/trade_executor_service.py",    # executor shim — raises on Alpaca
    "tests/test_no_alpaca_regressions.py",   # this file
}

# Additional read-only reference locations that aren't part of the runtime.
SKIP_DIRS = {
    "tests",
    "archive",
    "old_",
    "backup",
    "__pycache__",
    ".pytest_cache",
    "venv",
    ".venv",
    "node_modules",
}


def _iter_py_files():
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if str(rel).replace(os.sep, "/") in ALLOWED_FILES:
            continue
        yield path, rel


FORBIDDEN_PATTERNS = [
    # Direct Alpaca SDK imports — only the executor shim is allowed, and it
    # now raises instead of importing, so nothing should match.
    re.compile(r"^\s*from\s+alpaca\.", re.MULTILINE),
    re.compile(r"^\s*import\s+alpaca\b", re.MULTILINE),
    # Direct references to the Alpaca HTTP base URL — nobody should be
    # reconstructing this anywhere.
    re.compile(r"alpaca\.markets", re.IGNORECASE),
]


def test_no_alpaca_sdk_imports_outside_shim():
    """No non-shim file may import the Alpaca SDK or hit alpaca.markets."""
    violations = []
    for path, rel in _iter_py_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in FORBIDDEN_PATTERNS:
            for m in pat.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                violations.append(f"{rel}:{line_no}: {m.group(0).strip()}")

    assert not violations, (
        "Alpaca has crept back into the live-data path. Offending lines:\n  "
        + "\n  ".join(violations)
        + "\n\nFix: use `from services.ib_data_provider import get_live_data_service`"
        " instead. If you truly need to touch Alpaca, add the file to"
        " ALLOWED_FILES in this test (and justify in the PR description)."
    )
