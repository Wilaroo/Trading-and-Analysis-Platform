# Future: Local Coder Model + AGENT.md Playbook

**Status:** Deferred — revisit after bot is running stable on live capital.
**Saved:** 2026-04-23

## Context
Erik researched adding a second local Ollama model (`qwen3-coder` / `qwen2.5-coder`) alongside the existing `qwen3:30b` for code-understanding / diff-generation work, plus formalizing agent behavior in a `CLAUDE.md`-style playbook.

## Verdict (from prior analysis)
- `qwen3-coder` as a **second** model → worth it, but start with `qwen2.5-coder:14b` for Spark memory headroom, not 30b.
- `CLAUDE.md` playbook → we already implement ~70% of it via handoff summaries + PRD.md, but a formal repo-root file would help local agents (not just Emergent fork agents).

## Not a model replacement
| Use case | Model |
|---|---|
| SentCom chat, trade rationale, autopsy narratives | Keep `qwen3:30b` |
| Code edits, diff gen, "explain this file", tool-call loops | NEW: `qwen2.5-coder:14b` |

Do NOT swap out `qwen3:30b` — different job, different optimization target.

## Spark-specific cautions
1. **Memory pressure**: Ollama (qwen3:30b) + 4 IB turbo collectors + backend + chat server + Mongo + training. Adding a second 30b coder model means model-swap latency or no simultaneous use.
2. **LMSys benchmark on Spark** shows memory-bandwidth bound, not compute bound → 14B beats 30B for interactive loops on this hardware.
3. **Isolation**: Coder OOM must not take down chat model or live-trading loop.

## Proposed architecture (when ready)

```
DGX Spark
├── Ollama :11434
│   ├── qwen3:30b          (existing — SentCom chat)
│   └── qwen2.5-coder:14b  (NEW — code assist)
│
├── Backend :8001
│   └── /api/agent/code-assist  (NEW endpoint)
│       - Reads /app/AGENT.md + /app/risk_zones.yml
│       - Routes to qwen2.5-coder
│       - Proposes diffs, never auto-applies
│
└── Chat :8002  (unchanged, qwen3:30b)

/app/
├── AGENT.md              (NEW — operating manual for local agents)
├── risk_zones.yml        (NEW — machine-readable high-risk paths)
└── memory/
    ├── PRD.md            (exists)
    ├── PUSHER_BRACKET_SPEC.md (exists)
    └── experiments_log.md (NEW — what was tried + outcome)
```

## Priority implementation order (when resumed)
1. **`/app/AGENT.md`** — operating manual (~1-2 hrs, zero risk)
2. **`/app/risk_zones.yml`** — high-risk file manifest (e.g., `trade_execution.py`, `position_reconciler.py`, `order_queue_service.py`, `risk_service.py`, `risk_management_service.py`, strategy configs)
3. **`/app/memory/experiments_log.md`** — backfill last 5 failed experiments from PRD.md
4. **`ollama pull qwen2.5-coder:14b`** on Spark; verify token/sec and memory headroom alongside qwen3:30b
5. **Thin `/api/agent/code-assist` endpoint** — read-only mode first (explain / diagnose only)
6. **Diff-proposal mode** — only after read-only mode proven stable

## Real-world payoff example
"Why did big_dog fail 3 times on KRG?"
→ Local coder reads recent KRG trade docs, big_dog config, scan-loop logs
→ Grounded explanation + proposed diff to disable/tune big_dog
→ Gated behind human approval because `strategy_configs.py` is in risk_zones.yml

That leverage is where this pays off — not replacing the chat model.

## Key snippets from Erik's research (saved verbatim)
- Starter recommendation: `qwen3-coder:30b` (or smaller 7B–14B coder if headroom tight)
- Source: Ollama coding-models blog + LMSys DGX Spark perf notes
- CLAUDE.md template structure: project overview, allowed zones, safety rules,
  backtest-vs-live discipline, memory policy, high-risk tagging
- Key rules to adopt verbatim in `/app/AGENT.md`:
  - "No live-trading changes without explicit approval"
  - "Never expose API keys / secrets"
  - "Push only when explicitly told"
  - "Tag high-risk changes with ⚠️"
  - "Backtest ≠ live performance — remind on every strategy change"

## Decision
Deferring until after:
- [ ] Bracket queue passthrough fix VERIFIED on live Spark (done on 2026-04-23 pytest; needs live curl)
- [ ] `confirm_trade` false-negative fixed (IN PROGRESS)
- [ ] `big_dog` KRG autopsy decision made
- [ ] TradeExecutionHealthCard + BotHealthBanner frontend shipped
- [ ] Bot running live with real capital for ≥1 week, stable

Then resume this file and execute the priority order above.
