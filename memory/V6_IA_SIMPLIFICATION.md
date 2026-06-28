# V6 IA Simplification — Source of Truth (started 2026-06-26)

Companion to `V6_NEXT_LOCKED_SPEC.md` (the locked cockpit visual spec). This doc
captures the **whole-app information-architecture** simplification the operator
asked for: fewer destinations, one cockpit, all data still trackable but depth
moved into purposeful "dig-deeper" drawers.

## Operator's goals (verbatim, 2026-06-26)
> "simplify the user interface a bit … but still be able to track all the data we
> need to keep making this system better. easy for a user to understand and easy to
> dig deeper into data where needed. visually appealing, reliable, AI-forward
> self-trading stock-picking and trading system, that explains itself, and most
> importantly learns from its decisions, adjusts and makes money and stays profitable."

## Operator decisions
- **Mission Control → FOLD into the cockpit/command-center.** (biggest single simplification)
- **Brain merge (NIA + Diagnostics): UNDECIDED** — design phase to propose; keep both
  surfaces' functionality regardless.
- **Sequence: B then A** — B (delete orphaned pages) DONE; A (design blueprint) in progress.

## Non-negotiables — must stay front-and-center (operator)
1. Complete **trade trails** (full lifecycle audit).
2. The full flow: **scan → symbol find → (scan) → trade trail**.
3. **Market regime / market conditions.**
4. **AI chat / decision / logic** (explains itself).
5. **Trade evaluations + current portfolio.**
6. **Pre- and post-market learnings & analyses.**
7. **System health.**

## Audit findings (current state)
- **8 live tabs** (sidebar): command-center, nia, mission-control, trade-journal,
  chart, glossary, settings, diagnostics.
- **13 ORPHANED pages** never rendered (removed 2026-06-26, 7,346 LOC): Dashboard,
  Scanner, Strategies, Watchlist, Portfolio, Fundamentals, Insider, COTData, Alerts,
  EarningsCalendar, MarketContext, TradingRules, TradeOpportunities. Barrel slimmed
  to ChartsPage + TradeJournalPage. Compiles clean, app boots.
- **Two competing cockpits**: command-center (`SentComV5View`, ~90 sub-components) and
  mission-control → confusing; fold MC into the cockpit.
- Cockpit density problems → to collapse: ~20 scattered status chips → ONE state
  machine (cyan/amber/rose) + System Health drawer; **two activity streams**
  (`UnifiedStreamV5` + `DeepFeedV5`) → ONE timeline.

## Proposed target IA — 5 destinations
| Destination | Replaces / absorbs | Notes |
|---|---|---|
| **Cockpit** (default) | command-center + **mission-control** | V6 glass shell; Scanner · Chart+Verdict · Thinking · Open Positions; Heartbeat + RiskRail + one state pill + KPI ribbon |
| **Brain** | nia (+ diagnostics? TBD) | live AI intelligence + decision audit / learning loop |
| **Journal** | trade-journal | trade trails / P&L / review |
| **Charts** | chart | deep charting |
| **Settings** | settings | config + bot params |
| _Glossary_ | → slide-in **drawer**, not a tab | the "explains itself" reference, one keystroke away |

## "Explains itself + learns + profits" surfaces (wire today's backend work)
- Provenance ring + "why" (TQS/Edge factors) on every auto-decision.
- **Edge & Learning** strip/drawer: EV by setup, what the bot disabled/enabled & why
  (`/api/diagnostic/disabled-setups-audit`, `/api/slow-learning/strategy-autonomy/report`),
  entry-edge status, tape-confirm health (`/api/scanner/tape-confirm/history`).
- P&L + Daily-Loss-Protection always-on (KPI ribbon + RiskRail).

## Phase plan (cockpit-only scope; V5 stays fallback throughout)
- **C0** ✅ `/v6` route + symbol search (2026-06-26).
- **B**  ✅ delete 13 orphaned pages (2026-06-26).
- **A**  → design blueprint (design_agent) for the 5-destination V6 — IN PROGRESS.
- **C1** wire cockpit real data + strip preview scaffolding (KPIs/pipeline/account/risk).
- **C2** safety-critical controls in V6: bot start/stop/mode, kill-switch, pending-trade
  approve/reject, IB connect, settings access → testing_agent on DGX.
- **C3** parity sweep of AICoachTab/SentComV5View → wire must-haves, defer rest to drawers.
- **C4** 1B layout tuning + modals (QuickTrade, TickerDetail, MorningBriefing, CloseTrade).
- **C5** fold Mission Control in; flip command-center tab → V6 with one-click `?legacy=v5`
  fallback; full test; bake-in; retire V5.
