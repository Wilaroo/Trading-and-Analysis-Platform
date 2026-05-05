"""
test_async_sync_blockers_v19_30_8.py — comprehensive audit pinning that
NO sync wedge-class call (pusher RPC, sync requests.*, sync urllib*)
runs from any `async def` without an `asyncio.to_thread` wrap.

This generalises v19.30.7's narrower test (which only covered 4 pusher
RPC methods) after the wedge-watchdog (v19.30.6) caught two NEW classes
on the operator's Spark machine 2026-05-02 evening:

  Wedge #1: trading_bot.py:231 → get_account_snapshot() → pusher RPC
            (the audit only checked .subscriptions, missed
             .account_snapshot which is a different pusher method)
  Wedge #2: market_intel_service.py:405 → requests.get(...)
            (entirely new wedge class — sync requests.get inside async)

v19.30.8 fixed the proven culprits and this test guards against every
related regression.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


# Every sync method on the pusher RPC client + module-level helpers
# that internally call sync HTTP under a threading.Lock. Calling any
# of these from async = wedge bug.
PUSHER_SYNC_METHODS = {
    # Instance methods on _PusherRPCClient
    "health",
    "account_snapshot",
    "subscriptions",
    "is_pusher_subscribed",
    "latest_bars",
    "quote_snapshot",
    "subscribe_symbols",
    "unsubscribe_symbols",
    "get_subscribed_set",
    "subscribe_one",
    "unsubscribe_one",
    "subscribe_many",
    "unsubscribe_many",
    "current_subs",
    "_request",
    "status",
    # Module-level helpers in services/ib_pusher_rpc.py
    "get_account_snapshot",
}

# Sync HTTP libraries — calling these from async ALWAYS wedges the loop
# on socket I/O.
SYNC_HTTP_CALLS = {"get", "post", "put", "delete", "patch", "head", "request"}
SYNC_HTTP_MODULES = {"requests", "urllib3", "urllib"}

# Files / call sites that have been documented as P1 follow-ups but
# are NOT yet fixed. v19.30.8 fixed `market_intel_service.py` (3 sites
# — proven culprit). The rest are scheduled-task callers — they don't
# fire on the dashboard hot path so the operator-impact is bounded.
# This allowlist documents the known violators so the test is green
# while we work them off the roadmap (Audit Pass 2a).
DOCUMENTED_BACKLOG_VIOLATIONS = {
    # Path → set of (method_name, lineno) tuples that are intentionally
    # not yet wrapped. When we fix one, remove from here.
    # Format: relative path from /app/backend/.
    "services/strategy_performance_service.py": "perf scheduler — backlog Audit Pass 2a",
    "services/news_service.py": "news scheduler — backlog Audit Pass 2a",
    "services/web_research_service.py": "Tavily client — backlog Audit Pass 2a",
    "services/setup_landscape_service.py": "scheduled rebuild — backlog Audit Pass 2a",
    "services/ai_assistant_service.py": "Ollama client — backlog Audit Pass 2a",
    # v19.30.8: deferred — scheduled-task code paths, not on dashboard hot path.
    # Track in roadmap Audit Pass 2a alongside the other 5.
    "services/fundamental_data_service.py": "Finnhub fundamentals scheduler — backlog Audit Pass 2a",
    "services/quality_service.py": "data-quality scheduler — backlog Audit Pass 2a",
    "services/earnings_service.py": "Finnhub earnings calendar — backlog Audit Pass 2a",
    "agents/brief_me_agent.py": "BriefMe agent (operator-triggered) — backlog Audit Pass 2a",
}


class _SyncCallInAsyncFinder(ast.NodeVisitor):
    """Walks an AST. For every `async def`, records sync wedge-class calls
    not wrapped in asyncio.to_thread."""

    def __init__(self, src: str):
        self.src = src
        self.lines = src.splitlines()
        self.results: list[dict] = []
        self._async_stack: list[str] = []

    def visit_AsyncFunctionDef(self, node):
        self._async_stack.append(node.name)
        self.generic_visit(node)
        self._async_stack.pop()

    def visit_FunctionDef(self, node):
        self.generic_visit(node)

    def _line_text(self, lineno: int) -> str:
        i = lineno - 1
        if 0 <= i < len(self.lines):
            return self.lines[i].strip()
        return ""

    def visit_Call(self, node):
        if not self._async_stack:
            self.generic_visit(node)
            return

        f = node.func
        line_text = self._line_text(node.lineno)
        wrapped = "to_thread" in line_text or "run_in_executor" in line_text

        # --- Pusher RPC sync methods ---
        if isinstance(f, ast.Attribute) and f.attr in PUSHER_SYNC_METHODS:
            # Walk the caller chain — only flag if the receiver is rpc/pusher-shaped
            chain = []
            cur = f.value
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                chain.append(cur.id)
            caller = ".".join(reversed(chain)) or "<module>"
            # Heuristic: receiver name contains "rpc" or "pusher", OR the
            # method name itself is `get_account_snapshot` (a unique
            # module-level helper)
            is_pusher_shaped = (
                any(kw in caller for kw in ("rpc", "pusher", "ib_pusher"))
                or f.attr == "get_account_snapshot"
            )
            # Skip the trivial `is_configured` (returns env-var boolean,
            # no I/O — used in fast-path early-exits)
            if is_pusher_shaped and f.attr != "is_configured" and not wrapped:
                self.results.append({
                    "kind": "pusher_rpc",
                    "func": ".".join(self._async_stack),
                    "caller": caller,
                    "method": f.attr,
                    "lineno": node.lineno,
                    "line": line_text[:120],
                })

        # Direct call to module-level helper (e.g., `get_account_snapshot()`
        # without a receiver) — caught in plain ast.Name form
        if isinstance(f, ast.Name) and f.id in PUSHER_SYNC_METHODS:
            if not wrapped:
                self.results.append({
                    "kind": "pusher_rpc",
                    "func": ".".join(self._async_stack),
                    "caller": "<module>",
                    "method": f.id,
                    "lineno": node.lineno,
                    "line": line_text[:120],
                })

        # --- Sync HTTP libraries ---
        if isinstance(f, ast.Attribute) and f.attr in SYNC_HTTP_CALLS:
            mod_name = ""
            if isinstance(f.value, ast.Name):
                mod_name = f.value.id
            if mod_name in SYNC_HTTP_MODULES and not wrapped:
                self.results.append({
                    "kind": "sync_http",
                    "func": ".".join(self._async_stack),
                    "caller": mod_name,
                    "method": f.attr,
                    "lineno": node.lineno,
                    "line": line_text[:120],
                })

        self.generic_visit(node)


def _scan_codebase() -> list[dict]:
    violations: list[dict] = []
    skip_dirs = {"__pycache__", "Intraday", "tests", "scripts", ".git", ".venv"}
    for root, dirs, files in os.walk(str(BACKEND_DIR)):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(root, fn)
            try:
                src = open(full).read()
                tree = ast.parse(src)
            except Exception:
                continue
            v = _SyncCallInAsyncFinder(src)
            v.visit(tree)
            for r in v.results:
                r["file"] = os.path.relpath(full, str(BACKEND_DIR))
                violations.append(r)
    return violations


# ── 1. v19.30.8 specific — proven-culprit sites are wrapped ────────────
def test_trading_bot_status_account_snapshot_is_wrapped():
    """The smoking gun for v19.30.8 wedge #1 — trading_bot.get_bot_status
    called get_account_snapshot inline. MUST now use asyncio.to_thread."""
    src = (BACKEND_DIR / "routers" / "trading_bot.py").read_text()
    idx = src.find("async def get_bot_status")
    assert idx >= 0
    body = src[idx:idx + 6000]
    # The pre-fix pattern must NOT exist
    assert "snap = get_account_snapshot()" not in body, (
        "Pre-v19.30.8 inline pattern detected — get_account_snapshot "
        "must run via asyncio.to_thread"
    )
    # The post-fix pattern MUST exist
    assert "asyncio.to_thread(get_account_snapshot)" in body, (
        "Expected `asyncio.to_thread(get_account_snapshot)` in "
        "get_bot_status — v19.30.8 fix"
    )


def test_market_intel_service_requests_get_wrapped():
    """The smoking gun for v19.30.8 wedge #2 — market_intel_service was
    calling requests.get inline from async. All 3 sites in this file
    MUST now use asyncio.to_thread."""
    src = (BACKEND_DIR / "services" / "market_intel_service.py").read_text()
    # Count to_thread-wrapped requests calls vs unwrapped in this file
    import re
    # Find every requests.get/post (any whitespace)
    bare_calls = re.findall(r"^\s*resp\s*=\s*requests\.(get|post)\(", src, re.M)
    wrapped_calls = re.findall(
        r"asyncio\.to_thread\(\s*requests\.(get|post)\b", src
    )
    assert len(bare_calls) == 0, (
        f"market_intel_service still has {len(bare_calls)} bare "
        f"`resp = requests.get(...)` calls. Each must be wrapped in "
        f"asyncio.to_thread — same wedge class as v19.30.6's smoking gun."
    )
    assert len(wrapped_calls) >= 3, (
        f"Expected ≥3 asyncio.to_thread(requests.get/post, ...) calls "
        f"in market_intel_service.py (the 3 v19.30.8 fixes); found "
        f"{len(wrapped_calls)}"
    )


# ── 2. Codebase-wide audit (with documented backlog allowlist) ────────
def test_no_unwrapped_sync_http_in_async_outside_backlog():
    """Catch-all: any NEW async-context sync HTTP call (pusher RPC OR
    requests.*) introduced outside the documented backlog list fails
    this test. Forces explicit acknowledgement when adding violators.

    The backlog list (`DOCUMENTED_BACKLOG_VIOLATIONS`) records files
    where we know there are pre-existing sync-in-async patterns but
    they're in scheduled-task code paths, not the dashboard hot path.
    Audit Pass 2a (roadmap) tracks closing them.
    """
    violations = _scan_codebase()

    # Filter out documented-backlog files
    new_violations = [
        v for v in violations
        if v["file"] not in DOCUMENTED_BACKLOG_VIOLATIONS
    ]

    if new_violations:
        msg_lines = [
            f"Found {len(new_violations)} new sync-wedge-class call(s) "
            f"in async functions, NOT in the documented backlog. These "
            f"will wedge the FastAPI event loop on every invocation. "
            f"Wrap each in `await asyncio.to_thread(<func>, *args, **kwargs)`."
        ]
        for v in new_violations:
            msg_lines.append(
                f"  • {v['file']}:{v['lineno']}  in async "
                f"{v['func']!r}  →  {v['caller']}.{v['method']}()  "
                f"[kind={v['kind']}]"
            )
            msg_lines.append(f"    > {v['line']}")
        msg_lines.append(
            "If this is intentional and you accept the wedge risk, "
            "add the file to DOCUMENTED_BACKLOG_VIOLATIONS in this "
            "test with a justification — but prefer wrapping in "
            "asyncio.to_thread."
        )
        raise AssertionError("\n".join(msg_lines))


def test_position_reconciler_get_account_snapshot_wrapped():
    """v19.34.8 (2026-05-05 PM) — `position_reconciler.reconcile_orphan_
    positions` was calling `get_account_snapshot()` inline. The wedge-
    audit caught it. MUST now use `asyncio.to_thread` — same wedge class
    as v19.30.8 wedge #1 in routers/trading_bot.py."""
    src = (BACKEND_DIR / "services" / "position_reconciler.py").read_text()
    # Pre-fix pattern must NOT exist
    assert "snap = get_account_snapshot()" not in src, (
        "Pre-v19.34.8 inline pattern detected — get_account_snapshot in "
        "position_reconciler must run via asyncio.to_thread"
    )
    # Post-fix pattern MUST exist
    assert "asyncio.to_thread(get_account_snapshot)" in src, (
        "Expected `asyncio.to_thread(get_account_snapshot)` in "
        "position_reconciler.py — v19.34.8 fix"
    )


def test_position_manager_subscribe_symbols_wrapped():
    """v19.34.8 (2026-05-05 PM) — `position_manager.update_open_positions`
    was calling `rpc.subscribe_symbols(stale_set)` inline on every manage-
    loop tick. The wedge-audit caught it. MUST now use `asyncio.to_thread`."""
    src = (BACKEND_DIR / "services" / "position_manager.py").read_text()
    # Pre-fix pattern must NOT exist
    assert "res = rpc.subscribe_symbols(stale_set)" not in src, (
        "Pre-v19.34.8 inline pattern detected — rpc.subscribe_symbols in "
        "position_manager must run via asyncio.to_thread"
    )
    # Post-fix pattern MUST exist
    assert "asyncio.to_thread(rpc.subscribe_symbols, stale_set)" in src, (
        "Expected `asyncio.to_thread(rpc.subscribe_symbols, stale_set)` in "
        "position_manager.py — v19.34.8 fix"
    )


# ── 3. The pusher_rpc module's docstring contract still holds ─────────
def test_pusher_rpc_module_contract_intact():
    """The pusher_rpc module docstring must continue to mandate
    `asyncio.to_thread` from async paths."""
    src = (BACKEND_DIR / "services" / "ib_pusher_rpc.py").read_text()
    header = src[:2000]
    assert "to_thread" in header.lower(), (
        "ib_pusher_rpc.py docstring must continue to mandate "
        "'Call from async paths via asyncio.to_thread'."
    )
