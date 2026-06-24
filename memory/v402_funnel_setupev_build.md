# v402 — Horizon-funnel verdict + quick wins (sector/EV) + setup-EV audit — 2026-06-24

Same-session follow-on to v401. Ran the horizon-funnel on the DGX and shipped 3 quick wins + 1 new
read-only diagnostic.

## Horizon-funnel run (DGX, days=30, 26,801 evals) — VERDICT
| horizon | evalShr | apprRate | taken | avgR | choke |
|---|---|---|---|---|---|
| scalp | 25.2% | 0.40 | 304 | -0.063 | healthy |
| intraday | 24.8% | 0.347 | 323 | -0.081 | gate_veto |
| swing | 35.9% | 0.343 | 505 | -0.215 | gate_veto |
| position | 14.0% | 0.68 | 466 | -0.048 | healthy |

- ✅ **"Scalp/intraday under-firing" P1 = RESOLVED.** Fast = ~50% of evals (old "0.6%" premise dead);
  `capacity_rejections: 0` (25-cap not biting). Closed in ROADMAP.
- ⚠️ `gate_veto` on intraday/swing is a **red herring** — post-gate R is negative there, so loosening
  the gate would add negative-EV flow. Do NOT loosen.
- 🔴 Real problem: whole book mildly -EV, **worst on SWING (-0.215R, 505 taken)**. Edge problem, not
  routing — tied to the deferred TQS scalp re-audit (2026-07-08).

## Shipped (preview-tested; need Save-to-GitHub → DGX pull)
- **(c) growth metric** — VERIFIED already complete (no change): ib_fundamentals_parser.py:168 parses
  `ProjLTGrowthRate`; fundamental_quality.py:192/512 consumes it. Prior "forgot to fix" note was stale.
- **(d) Sector fallback** [services/tqs/context_quality.py `_symbol_sector_etf`]: when
  `symbol_adv_cache.sector` is empty, fall back to `sector_tag_service.tag_symbol()` (static ~500-symbol
  map, sync, no network). NOTE: the deep coverage win for the ~6.4k "untaggable" names needs
  `POST /api/scanner/sector-backfill/deep?max_symbols=4000` (IB-industry → SPDR ETF).
- **(e) EV threshold 5→3** [services/tqs/setup_quality.py:274]: contextual-EV sample gate lowered so real
  EV displaces the R:R proxy faster now that outcomes log+backfilled.
- **NEW — setup-EV audit** [services/setup_ev.py + GET /api/slow-learning/setup-ev/report]:
  realized R by setup_type for a horizon, long/short split, winsorized R, verdict
  (bleeding|marginal|healthy|thin), sorted worst total-R first. Seeds the long-backlogged setup-ev-audit.
  Tested: tests/test_setup_ev.py (pass).

## NEXT (operator, after pull)
Chase the swing bleed:
```
curl -s "http://localhost:8001/api/slow-learning/setup-ev/report?horizon=swing&days=30" -o /tmp/sev.json
python3 -c "
import json
d = json.load(open('/tmp/sev.json'))['report']
print('HEADLINE:', d.get('headline'))
print('%-20s %5s %7s %8s %9s %8s  %s' % ('setup','n','win%','avgR','winsorR','totR','verdict'))
for r in d.get('setups',[]):
    print('%-20s %5s %7s %8s %9s %8s  %s' % (r['setup_type'], r['n'], r['win_rate'], r['avg_r'], r['winsor_avg_r'], r['total_r'], r['verdict']))
"
```
Suppress/tighten the `bleeding` rows (v353–v363 playbook). Also note `mfe-mae/report` already exists
(item b partially built) — run it next to separate bad-entries from bad-exits by horizon.
