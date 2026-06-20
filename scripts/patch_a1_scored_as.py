#!/usr/bin/env python3
r"""
patch_a1_scored_as.py — UI Track A · A1 "Scored as" (P1 Style=Pattern surfacing).

Makes the P1 fix visible: every scanner row + the TQS drawer now show the
PATTERN-INTRINSIC grading style TQS used to weight the score, distinct from the
liquidity horizon stamp. A breakdown_confirmed on a liquid name reads
horizon=INTRA but SCORED M-DAY.

Adds 2 NEW files (whole-file) + 9 anchored, idempotent edits (.a1bak backups):
  NEW  frontend/src/components/sentcom/v5/ScoredAsChip.jsx
  NEW  frontend/src/utils/__tests__/gradingStyle.smoke.js
  EDIT utils/tradeStyleMeta.js          (+gradingStyleKey/getGradingStyleMeta;
                                          static breakdown_confirmed -> multi_day)
  EDIT v5/TqsPillarPanel.jsx            (Grading-style header line + tone map)
  EDIT v5/TqsDrillDownDrawer.jsx        (derive + pass scoringStyle)
  EDIT v5/ScannerCardsV5.jsx            (render <ScoredAsChip/> on each row)

Usage (repo root, e.g. ~/Trading-and-Analysis-Platform):
    python3 scripts/patch_a1_scored_as.py --check
    python3 scripts/patch_a1_scored_as.py --apply
    python3 scripts/patch_a1_scored_as.py --rollback
After --apply:  cd frontend && yarn build   (then hard-refresh the cockpit)
Optional logic check:  node frontend/src/utils/__tests__/gradingStyle.smoke.js
"""
import os
import sys
import shutil
import hashlib
import argparse

NEW_FILES = [
    {
        "path": "frontend/src/components/sentcom/v5/ScoredAsChip.jsx",
        "marker": "ScoredAsChip — v19.34.272",
        "content": r"""/**
 * ScoredAsChip — v19.34.272 (UI Track A / P1 "Scored as")
 *
 * Surfaces the PATTERN-INTRINSIC grading style TQS used to WEIGHT the score
 * (mirrors backend services/setup_taxonomy.style_of) — deliberately DISTINCT
 * from the liquidity horizon stamp shown by <TradeStyleChip/>.
 *
 * This makes the P1 Style=Pattern fix visible on every row/drawer: e.g. a
 * `breakdown_confirmed` on a highly-liquid name reads horizon = INTRA but is
 * SCORED M-DAY (fundamentals weighted heavier) because the pattern is multi-day.
 *
 * Source precedence (see utils/tradeStyleMeta.gradingStyleKey):
 *   persisted tqs_breakdown.scoring_style → setup-derived pattern style
 *   (via the live SSOT taxonomy bridge). Renders nothing when unknown.
 */
import React from 'react';

import { getGradingStyleMeta, gradingStyleKey } from '../../../utils/tradeStyleMeta';
import { useTaxonomyVersion } from '../../../utils/useTaxonomy';

const TONE_CLASS = {
  fuchsia: 'bg-fuchsia-950/50 text-fuchsia-300 border-fuchsia-800/70',
  sky:     'bg-sky-950/50 text-sky-300 border-sky-800/70',
  emerald: 'bg-emerald-950/50 text-emerald-300 border-emerald-800/70',
  amber:   'bg-amber-950/50 text-amber-300 border-amber-800/70',
  rose:    'bg-rose-950/50 text-rose-300 border-rose-800/70',
  slate:   'bg-slate-900/60 text-slate-400 border-slate-700',
};

/**
 * Props:
 *   row          : object with scoring_style / tqs_breakdown / setup_type
 *   size         : 'xs' | 'sm' (default 'xs')
 *   testIdSuffix : appended to data-testid for uniqueness in lists
 */
export default function ScoredAsChip({ row, size = 'xs', testIdSuffix }) {
  // Re-render once the live SSOT taxonomy hydrates so the style never stays stale.
  useTaxonomyVersion();
  if (!row) return null;

  const key = gradingStyleKey(row);
  if (!key || key === 'unknown') return null;

  const meta = getGradingStyleMeta(row);
  const tone = TONE_CLASS[meta.tone] || TONE_CLASS.slate;
  const pad = size === 'sm' ? 'px-2 py-0.5 text-[12px]' : 'px-1.5 py-0 text-[11px]';
  const testId = `scored-as-chip${testIdSuffix ? `-${testIdSuffix}` : ''}`;
  const label = String(meta.label || '').toLowerCase();
  const title =
    `Scored as ${meta.label} — TQS weighted this trade for a ${label} hold (${meta.horizon}) ` +
    `because the setup pattern is ${label}. Liquidity sets the horizon; the pattern sets the grade.`;

  return (
    <span
      data-testid={testId}
      data-grading-style={key}
      title={title}
      className={`inline-flex items-center gap-1 uppercase tracking-wider border rounded font-bold ${pad} ${tone}`}
    >
      <span className="opacity-60 text-[9px]">SCORED</span>
      <span>{meta.shortKey}</span>
    </span>
  );
}
""",
    },
    {
        "path": "frontend/src/utils/__tests__/gradingStyle.smoke.js",
        "marker": "gradingStyle.smoke:",
        "content": r"""/**
 * Offline smoke test for v19.34.272 gradingStyleKey / getGradingStyleMeta
 * (UI Track A / P1 "Scored as"). Pattern-intrinsic grading style — must
 * IGNORE the liquidity trade_style stamp and prefer persisted scoring_style.
 *
 * Run: cd frontend && node src/utils/__tests__/gradingStyle.smoke.js
 *
 * Note: runs under CommonJS with NO live taxonomy fetch, so it validates the
 * STATIC SETUP_TO_STYLE fallback (which must agree with the backend SSOT).
 */
const assert = require('assert');
const path = require('path');
const fs = require('fs');

const src = fs.readFileSync(path.join(__dirname, '../tradeStyleMeta.js'), 'utf8');
const cjsSrc = src
  .replace(/export const /g, 'const ')
  .replace(/export default /g, 'module.exports.default = ')
  .replace(/export \{[^}]+\};?/g, '');
const exports_ = {};
const module_ = { exports: exports_ };
const wrapped = new Function(
  'module', 'exports',
  cjsSrc +
  '\nmodule.exports.gradingStyleKey = gradingStyleKey;' +
  '\nmodule.exports.getGradingStyleMeta = getGradingStyleMeta;',
);
wrapped(module_, exports_);
const { gradingStyleKey, getGradingStyleMeta } = module_.exports;

const cases = [
  // persisted scoring_style ALWAYS wins
  [{ scoring_style: 'multi_day', setup_type: 'orb' }, 'multi_day'],
  [{ tqs_breakdown: { scoring_style: 'position' }, setup_type: 'vwap_fade' }, 'position'],
  // IGNORES the liquidity trade_style stamp — pattern only
  [{ trade_style: 'intraday', setup_type: 'breakdown_confirmed' }, 'multi_day'],
  [{ trade_style: 'scalp', setup_type: 'daily_breakout' }, 'multi_day'],
  [{ trade_style: 'intraday', setup_type: 'stage_2_breakout' }, 'position'],
  // setup-derived pattern (no stamp)
  [{ setup_type: 'orb' }, 'intraday'],
  [{ setup_type: 'vwap_fade' }, 'scalp'],
  [{ setup_type: 'weekly_breakout' }, 'investment'],
  // directional suffix stripping
  [{ setup_type: 'vwap_fade_long' }, 'scalp'],
  // unknown / empty
  [{ setup_type: 'totally_made_up_setup' }, 'unknown'],
  [{}, 'unknown'],
];

let pass = 0;
for (const [row, expect] of cases) {
  const got = gradingStyleKey(row);
  assert.strictEqual(got, expect,
    `gradingStyleKey(${JSON.stringify(row)}) = ${got}, expected ${expect}`);
  pass += 1;
}

// meta resolves & never throws
assert.ok(getGradingStyleMeta({ setup_type: 'breakdown_confirmed' }).label === 'Multi-day');
assert.ok(getGradingStyleMeta({}).label === 'Unknown');

console.log(`gradingStyle.smoke: ${pass}/${cases.length} cases PASS + meta OK`);
""",
    },
]

EDITS = [
    {
        "id": "1a-tradeStyleMeta +gradingStyleKey",
        "path": "frontend/src/utils/tradeStyleMeta.js",
        "old": """export const getTradeStyleMeta = (row) => {
  const key = resolveTradeStyle(row);
  return TRADE_STYLE_META[key] || TRADE_STYLE_META.unknown;
};
""",
        "new": """export const getTradeStyleMeta = (row) => {
  const key = resolveTradeStyle(row);
  return TRADE_STYLE_META[key] || TRADE_STYLE_META.unknown;
};

/**
 * v19.34.272 (UI Track A / P1) — PATTERN-INTRINSIC grading style.
 *
 * The style TQS used to WEIGHT the score (mirrors backend
 * services/setup_taxonomy.style_of) — deliberately IGNORES the liquidity
 * `trade_style` horizon stamp (that drives brackets/TIF, not the score lens).
 *
 * Precedence: persisted `scoring_style` (tqs_breakdown.scoring_style) →
 * setup-derived pattern style via the live SSOT bridge (`setupLookup`).
 * Returns a TRADE_STYLE_META key or 'unknown'.
 */
export const gradingStyleKey = (row = {}) => {
  const ss = String(
    row.scoring_style || (row.tqs_breakdown && row.tqs_breakdown.scoring_style) || ''
  ).trim().toLowerCase();
  if (ss && TRADE_STYLE_META[ss]) return ss;
  return setupLookup(row.setup_variant) || setupLookup(row.setup_type) || 'unknown';
};

export const getGradingStyleMeta = (row) =>
  TRADE_STYLE_META[gradingStyleKey(row)] || TRADE_STYLE_META.unknown;
""",
        "applied_marker": "export const gradingStyleKey",
    },
    {
        "id": "1b-tradeStyleMeta breakdown_confirmed->multi_day",
        "path": "frontend/src/utils/tradeStyleMeta.js",
        "old": "  breakdown_confirmed: 'intraday',                   // SSOT: breakdown family → intraday (was 'multi_day')\n",
        "new": "  breakdown_confirmed: 'multi_day',                  // v19.34.271 P1: SSOT style_of (raw-first) → multi_day (was stale 'intraday')\n",
        "applied_marker": "breakdown_confirmed: 'multi_day',",
    },
    {
        "id": "2a-TqsPillarPanel import+tone",
        "path": "frontend/src/components/sentcom/v5/TqsPillarPanel.jsx",
        "old": "import { gradeFromScore } from './TqsBadge';\n",
        "new": """import { gradeFromScore } from './TqsBadge';
import { TRADE_STYLE_META } from '../../../utils/tradeStyleMeta';

// v19.34.272 (UI Track A / P1) — grading-style chip tone by style key.
const GRADING_STYLE_TONE = {
  fuchsia: 'text-fuchsia-300 border-fuchsia-800/70 bg-fuchsia-950/40',
  sky:     'text-sky-300 border-sky-800/70 bg-sky-950/40',
  emerald: 'text-emerald-300 border-emerald-800/70 bg-emerald-950/40',
  amber:   'text-amber-300 border-amber-800/70 bg-amber-950/40',
  rose:    'text-rose-300 border-rose-800/70 bg-rose-950/40',
  slate:   'text-slate-400 border-slate-700 bg-slate-900/60',
};
""",
        "applied_marker": "GRADING_STYLE_TONE",
    },
    {
        "id": "2b-TqsPillarPanel signature",
        "path": "frontend/src/components/sentcom/v5/TqsPillarPanel.jsx",
        "old": "const TqsPillarPanel = ({ tqs, testIdSuffix = '' }) => {\n",
        "new": "const TqsPillarPanel = ({ tqs, scoringStyle = null, testIdSuffix = '' }) => {\n",
        "applied_marker": "({ tqs, scoringStyle = null, testIdSuffix",
    },
    {
        "id": "2c-TqsPillarPanel grading-style line",
        "path": "frontend/src/components/sentcom/v5/TqsPillarPanel.jsx",
        "old": """        </span>
      </div>

      <div>
        {PILLAR_ORDER.map((key) => {
""",
        "new": """        </span>
      </div>

      {scoringStyle && TRADE_STYLE_META[scoringStyle] && (
        <div
          className="flex items-center gap-1.5 mb-2 -mt-0.5"
          data-testid={`tqs-grading-style-${testIdSuffix}`}
        >
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">Grading style</span>
          <span
            className={`px-1.5 py-0 text-[11px] uppercase rounded-sm border font-bold tracking-wide ${GRADING_STYLE_TONE[TRADE_STYLE_META[scoringStyle].tone] || GRADING_STYLE_TONE.slate}`}
            title={`TQS weighted this trade as ${TRADE_STYLE_META[scoringStyle].label} (${TRADE_STYLE_META[scoringStyle].horizon}) — pattern, not liquidity.`}
          >
            {TRADE_STYLE_META[scoringStyle].label}
          </span>
          <span className="text-[10px] text-zinc-600">weights below — pattern, not liquidity</span>
        </div>
      )}

      <div>
        {PILLAR_ORDER.map((key) => {
""",
        "applied_marker": "tqs-grading-style-",
    },
    {
        "id": "3a-TqsDrillDownDrawer import",
        "path": "frontend/src/components/sentcom/v5/TqsDrillDownDrawer.jsx",
        "old": "import TqsPillarPanel from './TqsPillarPanel';\n",
        "new": "import TqsPillarPanel from './TqsPillarPanel';\nimport { gradingStyleKey } from '../../../utils/tradeStyleMeta';\n",
        "applied_marker": "import { gradingStyleKey }",
    },
    {
        "id": "3b-TqsDrillDownDrawer derive scoringStyle",
        "path": "frontend/src/components/sentcom/v5/TqsDrillDownDrawer.jsx",
        "old": """  const pillarTqs = detail
    ? {
        score: detail.tqs_score,
        unified_grade: detail.tqs_grade,
        weights: detail.weights || {},
        breakdown: detail.breakdown || {},
      }
    : null;
""",
        "new": """  const pillarTqs = detail
    ? {
        score: detail.tqs_score,
        unified_grade: detail.tqs_grade,
        weights: detail.weights || {},
        breakdown: detail.breakdown || {},
      }
    : null;

  // v19.34.272 (UI Track A / P1) — grading style (pattern, not liquidity).
  // Prefer the persisted scoring_style; fall back to the setup-derived pattern.
  const scoringStyle = detail
    ? gradingStyleKey({ scoring_style: detail.scoring_style, setup_type: detail.setup_type })
    : null;
""",
        "applied_marker": "const scoringStyle = detail",
    },
    {
        "id": "3c-TqsDrillDownDrawer pass prop",
        "path": "frontend/src/components/sentcom/v5/TqsDrillDownDrawer.jsx",
        "old": "              {pillarTqs && <TqsPillarPanel tqs={pillarTqs} testIdSuffix=\"drawer\" />}\n",
        "new": "              {pillarTqs && <TqsPillarPanel tqs={pillarTqs} scoringStyle={scoringStyle} testIdSuffix=\"drawer\" />}\n",
        "applied_marker": "scoringStyle={scoringStyle}",
    },
    {
        "id": "4a-ScannerCardsV5 import",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": "import TqsBadge from './TqsBadge';\n",
        "new": "import TqsBadge from './TqsBadge';\nimport ScoredAsChip from './ScoredAsChip';\n",
        "applied_marker": "import ScoredAsChip from './ScoredAsChip'",
    },
    {
        "id": "4b-ScannerCardsV5 render chip",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": """          <TqsBadge
            symbol={card.symbol}
            score={card.tqs_score}
            gradeFallback={card.tqs_grade}
            source={card.source || 'alert'}
            testIdSuffix={`scanner-${card.symbol}`}
          />
""",
        "new": """          <TqsBadge
            symbol={card.symbol}
            score={card.tqs_score}
            gradeFallback={card.tqs_grade}
            source={card.source || 'alert'}
            testIdSuffix={`scanner-${card.symbol}`}
          />
          {/* v19.34.272 (UI Track A / P1) — grading style TQS scored with
              (pattern, not liquidity). Distinct from the horizon chip above. */}
          {(card.setup_type || card.trade_style) && (
            <ScoredAsChip
              row={{ trade_style: card.trade_style, setup_type: card.setup_type }}
              size="xs"
              testIdSuffix={`scanner-${card.symbol}`}
            />
          )}
""",
        "applied_marker": "<ScoredAsChip",
    },
]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:12] if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(os.path.join(".", path))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    print("=" * 84)
    print("  A1 PATCH — UI Track A 'Scored as' (P1 Style=Pattern surfacing)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    if args.rollback:
        for e in EDITS:
            p = resolve(e["path"])
            bak = p + ".a1bak"
            if os.path.exists(bak):
                shutil.copy2(bak, p)
                print(f"  restored {e['path']}  sha={sha(p)}")
        for nf in NEW_FILES:
            p = resolve(nf["path"])
            if os.path.exists(p) and nf["marker"] in open(p, encoding="utf-8").read():
                os.remove(p)
                print(f"  removed  {nf['path']} (A1 new file)")
        print("\n  ROLLBACK complete.")
        return

    # NEW FILES plan
    nf_plan = []
    for nf in NEW_FILES:
        p = resolve(nf["path"])
        exists = os.path.exists(p)
        applied = exists and (nf["marker"] in open(p, encoding="utf-8").read())
        status = "ALREADY-APPLIED" if applied else ("EXISTS-CONFLICT" if exists else "READY-NEW")
        print(f"\n  [NEW {nf['path']}]\n    status : {status}")
        if status == "EXISTS-CONFLICT":
            print("    \u274c file exists without A1 marker — ABORT (no files changed).")
            sys.exit(3)
        nf_plan.append((nf, p, applied))

    # EDITS plan
    ed_plan = []
    for e in EDITS:
        p = resolve(e["path"])
        if not os.path.exists(p):
            print(f"  \u274c MISSING FILE: {e['path']}")
            sys.exit(2)
        src = open(p, encoding="utf-8").read()
        applied = e["applied_marker"] in src
        n = src.count(e["old"])
        status = "ALREADY-APPLIED" if applied else ("READY" if n == 1 else f"ANCHOR x{n}")
        print(f"\n  [{e['id']}]\n    file   : {e['path']}  sha={sha(p)}\n    status : {status}")
        if not applied and n != 1:
            print("    \u274c anchor not uniquely found — ABORT (no files changed).")
            sys.exit(3)
        ed_plan.append((e, p, src, applied))

    if args.check:
        nready = sum(1 for _, _, a in nf_plan if not a) + sum(1 for _, _, _, a in ed_plan if not a)
        print(f"\n  CHECK ok. {nready} change(s) ready. Re-run with --apply.")
        return

    # APPLY
    changed = 0
    for nf, p, applied in nf_plan:
        if applied:
            print(f"  skip (applied): {nf['path']}")
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(nf["content"])
        print(f"  created {nf['path']}  sha={sha(p)}")
        changed += 1
    for e, p, _src, applied in ed_plan:
        if applied:
            print(f"  skip (applied): {e['path']}")
            continue
        cur = open(p, encoding="utf-8").read()
        if e["old"] not in cur:
            print(f"  \u274c anchor vanished at apply for {e['id']} — ABORT.")
            sys.exit(4)
        bak = p + ".a1bak"
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        open(p, "w", encoding="utf-8").write(cur.replace(e["old"], e["new"], 1))
        print(f"  patched {e['path']}  sha={sha(p)}  (.a1bak saved)")
        changed += 1
    print(f"\n  APPLY complete. {changed} change(s).")
    print("  NEXT: cd frontend && yarn build   (then hard-refresh the cockpit)")
    print("  CHECK: node frontend/src/utils/__tests__/gradingStyle.smoke.js")


if __name__ == "__main__":
    main()
