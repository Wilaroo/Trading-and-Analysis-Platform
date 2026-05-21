# Copilot — repo instructions

See `AGENTS.md` in the repo root. That is the canonical context file
for this repository — read it first before making any code suggestion.

If you only read one section, read **§0 TL;DR** (top of file) — it
lists the 5 rules whose violation has cost real money or required
emergency patches in production:

1. `close_trade` / `submit_with_bracket` / kill-switch are
   safety-critical — fork via `_custom` siblings, never patch in place.
2. Never send an IB close without `_cancel_ib_bracket_orders` + the
   8s + 5s retry wait.
3. `_open_trades` is keyed by `trade_id`, not symbol — iterate
   `.values()` and filter.
4. `position_reconciler` must skip `entered_by="reconciled_excess_*"`
   on the orphan path.
5. Always project `{"_id": 0}` on Mongo reads.

This file exists so GitHub Copilot auto-loads project context. It
contains no rules of its own — single source of truth lives in
`AGENTS.md` to prevent drift.
