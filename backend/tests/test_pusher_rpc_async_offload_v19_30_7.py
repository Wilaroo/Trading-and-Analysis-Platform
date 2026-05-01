"""
test_pusher_rpc_async_offload_v19_30_7.py — pins the contract that
NO async function calls pusher RPC sync methods inline. v19.30.7
(2026-05-02 evening) closed the last 2 violations: hybrid_data_service
and pusher_rotation_service. This test prevents regressions by
walking the entire codebase via AST.

Background
----------
The wedge-watchdog (v19.30.6) caught the smoking-gun stack 2026-05-02
evening:

    MAIN/LOOP THREAD stuck for 5.0s in:
      sentcom_chart.py:862  get_chart_tail
      sentcom_chart.py:527  get_chart_bars
      hybrid_data_service.py:678  fetch_latest_session_bars
      → rpc.subscriptions(force_refresh=False)        # SYNC HTTP CALL
      → ib_pusher_rpc.py:124  _request
      → with self._lock:                              # blocked on lock

`fetch_latest_session_bars` is `async def` but called the sync
`rpc.subscriptions()` inline. Same wedge class as v19.30.2 (bar_poll)
but a different call site — which means the contract violation
pattern is recurring and we need a guard against the next instance.

The pusher_rpc module's own header docstring explicitly says
"Call from async paths via asyncio.to_thread". This test enforces
that contract code-wide.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path


# Sync methods on the pusher RPC client that block on its threading.Lock
# and/or do sync HTTP. Any async function that calls these MUST wrap in
# asyncio.to_thread.
SYNC_RPC_METHODS = {
    "subscriptions",
    "get_subscribed_set",
    "subscribe_one",
    "unsubscribe_one",
    "subscribe_many",
    "unsubscribe_many",
    "current_subs",
    "_request",
}

BACKEND_DIR = Path(__file__).resolve().parents[1]


class _AsyncRPCViolationFinder(ast.NodeVisitor):
    """Walks an AST and records every call to a SYNC_RPC_METHOD made
    inside an async def, NOT wrapped in asyncio.to_thread."""

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
        # Sync funcs don't have the async-wedge problem — recurse but
        # don't push to async_stack
        self.generic_visit(node)

    def visit_Call(self, node):
        if not self._async_stack:
            self.generic_visit(node)
            return

        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in SYNC_RPC_METHODS:
            # Walk caller chain to identify rpc/pusher-shaped callers
            chain = []
            cur = f.value
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                chain.append(cur.id)
            caller = ".".join(reversed(chain))
            # Filter to clearly pusher-RPC-shaped callers (avoid false
            # positives on unrelated code that happens to call .subscribe
            # on a websocket / event bus / etc.)
            if any(kw in caller for kw in ("rpc", "pusher", "ib_pusher")):
                line_text = (
                    self.lines[node.lineno - 1].strip()
                    if 0 <= node.lineno - 1 < len(self.lines)
                    else ""
                )
                wrapped = "to_thread" in line_text
                if not wrapped:
                    self.results.append({
                        "func": ".".join(self._async_stack),
                        "caller": caller,
                        "method": f.attr,
                        "lineno": node.lineno,
                        "line": line_text[:120],
                    })
        self.generic_visit(node)


def _scan_codebase() -> list[dict]:
    """Walk the backend tree and return every async-context pusher-RPC
    call NOT wrapped in asyncio.to_thread."""
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
            v = _AsyncRPCViolationFinder(src)
            v.visit(tree)
            for r in v.results:
                r["file"] = os.path.relpath(full, str(BACKEND_DIR))
                violations.append(r)
    return violations


# ── 1. ZERO violations across the whole backend tree ──────────────────
def test_no_async_function_calls_pusher_rpc_inline():
    """The pusher_rpc module's docstring mandates 'Call from async paths
    via asyncio.to_thread'. This pins that contract codebase-wide.

    v19.30.2 closed the bar_poll_service violation. v19.30.7 closed
    the hybrid_data_service + pusher_rotation_service violations
    after the wedge-watchdog (v19.30.6) caught the smoking-gun stack.
    Subsequent regressions would re-introduce the wedge — this test
    fails them at PR time.
    """
    violations = _scan_codebase()
    if violations:
        msg_lines = [
            f"Found {len(violations)} async-context pusher RPC call(s) "
            f"NOT wrapped in asyncio.to_thread. These are wedge-class "
            f"bugs — the pusher RPC holds a threading.Lock + does sync "
            f"HTTP, blocking the event loop for the full timeout window."
        ]
        for v in violations:
            msg_lines.append(
                f"  • {v['file']}:{v['lineno']}  in async "
                f"{v['func']!r}  →  {v['caller']}.{v['method']}()"
            )
            msg_lines.append(f"    > {v['line']}")
        msg_lines.append(
            "Fix: wrap in `await asyncio.to_thread(<callable>, *args)`. "
            "See services/hybrid_data_service.py:678 (v19.30.7) for the pattern."
        )
        raise AssertionError("\n".join(msg_lines))


# ── 2. v19.30.7 specific call sites are wrapped ───────────────────────
def test_hybrid_data_service_subscriptions_wrapped():
    """Pin the exact line that triggered v19.30.7 — the smoking gun
    captured by wedge-watchdog 2026-05-02 evening."""
    src = (BACKEND_DIR / "services" / "hybrid_data_service.py").read_text()
    # Find fetch_latest_session_bars body and verify the subscriptions
    # call is via asyncio.to_thread
    idx = src.find("async def fetch_latest_session_bars")
    assert idx >= 0
    body = src[idx:idx + 5000]
    assert "rpc.subscriptions(" not in body or "to_thread" in body, (
        "fetch_latest_session_bars must call rpc.subscriptions via "
        "asyncio.to_thread — this was the v19.30.7 smoking-gun fix"
    )
    # Stronger assertion: the to_thread wrap exists
    assert "asyncio.to_thread(rpc.subscriptions" in body, (
        "Expected `asyncio.to_thread(rpc.subscriptions, ...)` in "
        "fetch_latest_session_bars — v19.30.7 fix"
    )


def test_pusher_rotation_get_subscribed_set_wrapped():
    """Pin the second v19.30.7 fix — pusher_rotation_service._loop_body
    was calling get_subscribed_set inline on every tick."""
    src = (BACKEND_DIR / "services" / "pusher_rotation_service.py").read_text()
    idx = src.find("async def _loop_body")
    assert idx >= 0
    body = src[idx:idx + 6000]
    # The pinning-loop call site must use to_thread
    assert "asyncio.to_thread(\n                        self.pusher.get_subscribed_set" in body or \
           "asyncio.to_thread(self.pusher.get_subscribed_set" in body, (
        "_loop_body must call get_subscribed_set via asyncio.to_thread "
        "(v19.30.7 fix)"
    )


# ── 3. The pusher_rpc module's contract is still in place ─────────────
def test_pusher_rpc_module_docstring_contract():
    """The contract test exists, but in case the module docstring is
    ever weakened, fail loud."""
    src = (BACKEND_DIR / "services" / "ib_pusher_rpc.py").read_text()
    # Header docstring (first 2000 chars) must mention the contract
    header = src[:2000]
    assert "to_thread" in header.lower(), (
        "ib_pusher_rpc.py module docstring must continue to mandate "
        "'Call from async paths via asyncio.to_thread'. If you removed "
        "that text, this test is the only thing protecting the "
        "wedge-class invariant."
    )
