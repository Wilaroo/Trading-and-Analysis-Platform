#!/usr/bin/env python3
r"""
patch_a2_provenance_ring.py — UI Track A · A2 "provenance ring".

Adds a compact SVG ring on each scanner row: 5 equal arcs (one per TQS pillar:
setup · technical · fundamental · context · execution), each colored by that
pillar's grade, with the overall TQS grade in the center. Composition at a
glance; the TQS badge still shows the number. Click opens the TQS drawer.
Frontend-only — the scanner payload already carries `tqs_pillar_grades`.

APPLIES ON TOP OF A1 (v19.34.272). Adds 1 NEW file + 5 anchored, idempotent
edits (.a2bak backups, reversible):
  NEW  frontend/src/components/sentcom/v5/ProvenanceRing.jsx
  EDIT v5/ScannerCardsV5.jsx  (import + map tqs_pillar_grades into setup/alert/
                               position cards + render <ProvenanceRing/>)

Usage (repo root):
    python3 scripts/patch_a2_provenance_ring.py --check
    python3 scripts/patch_a2_provenance_ring.py --apply
    python3 scripts/patch_a2_provenance_ring.py --rollback
After --apply:  cd frontend && yarn build   (then hard-refresh the cockpit)
"""
import os
import sys
import shutil
import hashlib
import argparse

NEW_FILES = [
    {
        "path": "frontend/src/components/sentcom/v5/ProvenanceRing.jsx",
        "marker": "ProvenanceRing — v19.34.273",
        "content": r"""/**
 * ProvenanceRing — v19.34.273 (UI Track A / A2)
 *
 * Compact SVG "provenance ring": 5 equal arcs, one per TQS pillar
 * (setup · technical · fundamental · context · execution), each colored by
 * that pillar's grade. The overall TQS grade letter sits in the center.
 *
 * It answers "where does this score come from?" at a glance — the
 * <TqsBadge/> still shows the precise number; this shows its composition.
 * Click opens the shared <TqsDrillDownDrawer/> (via tqsDrawerBus).
 *
 * Renders nothing when no per-pillar grades were captured (legacy rows).
 * Data source: alert/position `tqs_pillar_grades` (asdict from the backend).
 */
import React from 'react';

import { openTqsDrawer } from './tqsDrawerBus';
import { gradeFromScore } from './TqsBadge';

// Canonical pillar order — matches services/tqs/tqs_engine.py + TqsPillarPanel.
const PILLAR_ORDER = ['setup', 'technical', 'fundamental', 'context', 'execution'];
const PILLAR_LABEL = {
  setup: 'Setup',
  technical: 'Technical',
  fundamental: 'Fundamental',
  context: 'Context',
  execution: 'Execution',
};

// Grade → stroke color (mirrors TqsBadge.gradeTone families).
const GRADE_STROKE = {
  'A+': '#10b981', A: '#10b981',
  'B+': '#0ea5e9', B: '#0ea5e9',
  'C+': '#f59e0b', C: '#f59e0b',
  D: '#f97316',
  F: '#f43f5e',
};
const MISSING = '#3f3f46'; // zinc-700 — pillar with no grade
const strokeFor = (g) => GRADE_STROKE[String(g || '').toUpperCase()] || MISSING;

const polar = (cx, cy, r, deg) => {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
};
const arcPath = (cx, cy, r, startDeg, endDeg) => {
  const [x1, y1] = polar(cx, cy, r, startDeg);
  const [x2, y2] = polar(cx, cy, r, endDeg);
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
};

/**
 * Props:
 *   symbol, source           : for the drawer
 *   pillarGrades             : { setup, technical, fundamental, context, execution }
 *   grade                    : overall TQS grade (center letter); falls back to score
 *   score                    : overall TQS score (used if grade missing)
 *   size                     : px diameter (default 28)
 *   testIdSuffix
 */
export default function ProvenanceRing({
  symbol,
  source = 'alert',
  pillarGrades,
  grade = '',
  score = null,
  size = 28,
  testIdSuffix,
}) {
  const grades = pillarGrades && typeof pillarGrades === 'object' ? pillarGrades : null;
  const hasAny = grades && PILLAR_ORDER.some((k) => grades[k]);
  if (!hasAny) return null;

  const centerGrade = String(grade || (score != null ? gradeFromScore(score) : '') || '').toUpperCase();
  const sw = Math.max(2.5, size * 0.11);
  const c = size / 2;
  const r = c - sw / 2 - 0.5;
  const gap = 9; // degrees between segments
  const seg = 360 / PILLAR_ORDER.length;
  const testId = `provenance-ring${testIdSuffix ? `-${testIdSuffix}` : ''}`;

  const title =
    'Provenance — ' +
    PILLAR_ORDER.map((k) => `${PILLAR_LABEL[k]} ${grades[k] || '—'}`).join(' · ');

  const handleClick = (e) => {
    e.stopPropagation();
    if (symbol) openTqsDrawer({ symbol, source });
  };

  return (
    <button
      type="button"
      data-testid={testId}
      onClick={handleClick}
      title={title}
      aria-label={title}
      className="shrink-0 rounded-full transition-transform hover:scale-110 focus:outline-none"
      style={{ width: size, height: size, lineHeight: 0 }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* track */}
        <circle cx={c} cy={c} r={r} fill="none" stroke="#18181b" strokeWidth={sw} />
        {/* pillar arcs */}
        {PILLAR_ORDER.map((k, i) => {
          const start = i * seg + gap / 2;
          const end = (i + 1) * seg - gap / 2;
          return (
            <path
              key={k}
              d={arcPath(c, c, r, start, end)}
              fill="none"
              stroke={strokeFor(grades[k])}
              strokeWidth={sw}
              strokeLinecap="round"
              data-pillar={k}
              data-grade={grades[k] || ''}
            />
          );
        })}
        {/* center grade letter */}
        {centerGrade && (
          <text
            x={c}
            y={c}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={size * 0.34}
            fontWeight="700"
            fill={strokeFor(centerGrade)}
            fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          >
            {centerGrade}
          </text>
        )}
      </svg>
    </button>
  );
}
""",
    },
]

EDITS = [
    {
        "id": "1-ScannerCardsV5 import ProvenanceRing",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": "import ScoredAsChip from './ScoredAsChip';\n",
        "new": "import ScoredAsChip from './ScoredAsChip';\nimport ProvenanceRing from './ProvenanceRing';\n",
        "applied_marker": "import ProvenanceRing from './ProvenanceRing'",
    },
    {
        "id": "2-setups card +tqs_pillar_grades",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": "      tqs_score: s.tqs_score ?? s.confidence ?? null,\n      source: 'alert',\n",
        "new": "      tqs_score: s.tqs_score ?? s.confidence ?? null,\n      tqs_grade: s.tqs_grade ?? null,\n      tqs_pillar_grades: s.tqs_pillar_grades || null,\n      source: 'alert',\n",
        "applied_marker": "s.tqs_pillar_grades || null",
    },
    {
        "id": "3-alerts card +tqs_pillar_grades",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": "      tqs_score: a.tqs_score ?? a.confidence ?? null,\n      source: 'alert',\n",
        "new": "      tqs_score: a.tqs_score ?? a.confidence ?? null,\n      tqs_grade: a.tqs_grade ?? null,\n      tqs_pillar_grades: a.tqs_pillar_grades || null,\n      source: 'alert',\n",
        "applied_marker": "a.tqs_pillar_grades || null",
    },
    {
        "id": "4-positions card +tqs_pillar_grades",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": "      tqs_score: p.tqs_score ?? null,\n      tqs_grade: p.tqs_grade ?? null,\n      source: 'position',\n",
        "new": "      tqs_score: p.tqs_score ?? null,\n      tqs_grade: p.tqs_grade ?? null,\n      tqs_pillar_grades: p.tqs_pillar_grades || (p.entry_context && p.entry_context.tqs && p.entry_context.tqs.pillar_grades) || null,\n      source: 'position',\n",
        "applied_marker": "p.tqs_pillar_grades || (p.entry_context",
    },
    {
        "id": "5-ScannerCardsV5 render ProvenanceRing",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": """        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          <span
            className="v5-mono font-bold text-sm text-zinc-100 hover:text-cyan-300 hover:underline transition-colors cursor-pointer"
            data-testid={`scanner-card-symbol-${card.symbol}`}
""",
        "new": """        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          {/* v19.34.273 (UI Track A / A2) — provenance ring: 5 pillar arcs
              colored by grade, TQS grade in center. Composition at a glance;
              the TQS badge still shows the number. Click opens the drawer. */}
          {card.tqs_pillar_grades && (
            <ProvenanceRing
              symbol={card.symbol}
              source={card.source || 'alert'}
              pillarGrades={card.tqs_pillar_grades}
              grade={card.tqs_grade}
              score={card.tqs_score}
              size={28}
              testIdSuffix={`scanner-${card.symbol}`}
            />
          )}
          <span
            className="v5-mono font-bold text-sm text-zinc-100 hover:text-cyan-300 hover:underline transition-colors cursor-pointer"
            data-testid={`scanner-card-symbol-${card.symbol}`}
""",
        "applied_marker": "<ProvenanceRing",
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
    print("  A2 PATCH — UI Track A 'provenance ring'")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    if args.rollback:
        for e in EDITS:
            p = resolve(e["path"])
            bak = p + ".a2bak"
            if os.path.exists(bak):
                shutil.copy2(bak, p)
                print(f"  restored {e['path']}  sha={sha(p)}")
        for nf in NEW_FILES:
            p = resolve(nf["path"])
            if os.path.exists(p) and nf["marker"] in open(p, encoding="utf-8").read():
                os.remove(p)
                print(f"  removed  {nf['path']} (A2 new file)")
        print("\n  ROLLBACK complete.")
        return

    nf_plan = []
    for nf in NEW_FILES:
        p = resolve(nf["path"])
        exists = os.path.exists(p)
        applied = exists and (nf["marker"] in open(p, encoding="utf-8").read())
        status = "ALREADY-APPLIED" if applied else ("EXISTS-CONFLICT" if exists else "READY-NEW")
        print(f"\n  [NEW {nf['path']}]\n    status : {status}")
        if status == "EXISTS-CONFLICT":
            print("    \u274c file exists without A2 marker — ABORT.")
            sys.exit(3)
        nf_plan.append((nf, p, applied))

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
        bak = p + ".a2bak"
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        open(p, "w", encoding="utf-8").write(cur.replace(e["old"], e["new"], 1))
        print(f"  patched {e['path']}  sha={sha(p)}  (.a2bak saved)")
        changed += 1
    print(f"\n  APPLY complete. {changed} change(s).")
    print("  NEXT: cd frontend && yarn build   (then hard-refresh the cockpit)")


if __name__ == "__main__":
    main()
