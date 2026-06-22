#!/usr/bin/env python3
r"""
patch_a2c_sticky_grades_cache.py — UI Track A · A2 bugfix (v19.34.274).

Fixes the "provenance rings pop up then revert to no rings" flicker. Root
cause: `buildCards()` rebuilds the scanner cards on every render. WS `alerts`
carry `tqs_pillar_grades`; REST `setups` do NOT. When an alert turned over and
only the REST payload remained for a symbol, the rebuilt card dropped the
grades and the provenance ring vanished.

Fix (FRONTEND-ONLY, no backend/payload change): a sticky per-symbol grades
cache (in-memory useRef + localStorage). Cards that arrive WITH grades teach
the cache; cards that arrive WITHOUT grades are backfilled from it. The ring
now persists across REST/WS payload turnover AND full page reloads (24h TTL).

APPLIES ON TOP OF A2 (v19.34.273). 2 anchored, idempotent edits to ONE file
(.a2cbak backups, reversible). No new files.
  EDIT v5/ScannerCardsV5.jsx  (module helpers + sticky reconcile in cards memo)

Usage (repo root):
    python3 scripts/patch_a2c_sticky_grades_cache.py --check
    python3 scripts/patch_a2c_sticky_grades_cache.py --apply
    python3 scripts/patch_a2c_sticky_grades_cache.py --rollback
After --apply:  cd frontend && yarn build   (then hard-refresh the cockpit)
"""
import os
import sys
import shutil
import hashlib
import argparse

BAK = ".a2cbak"

EDITS = [
    {
        "id": "1-ScannerCardsV5 module grades-cache helpers",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": "export const ScannerCardsV5 = ({\n  setups,",
        "new": r"""// v19.34.274 (UI Track A / A2 bugfix) — sticky per-symbol TQS pillar-grades
// cache. REST `setups` lack `tqs_pillar_grades`; WS `alerts` carry them. When
// an alert turned over and only the REST payload remained, the rebuilt card
// dropped the grades and the provenance ring flashed away. Cache grades per
// symbol (memory + localStorage) and backfill any scanner card that arrives
// without them so the ring persists across payload turnover AND page reloads.
const GRADES_CACHE_KEY = 'v5_tqs_grades_cache_v1';
const GRADES_CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24h — drop stale symbols

const hasPillarGrades = (g) =>
  !!g && typeof g === 'object' && Object.values(g).some(Boolean);

const loadGradesCache = () => {
  const map = new Map();
  try {
    const raw = localStorage.getItem(GRADES_CACHE_KEY);
    if (!raw) return map;
    const obj = JSON.parse(raw);
    const now = Date.now();
    Object.entries(obj || {}).forEach(([sym, v]) => {
      if (v && hasPillarGrades(v.grades) && (!v.ts || now - v.ts < GRADES_CACHE_TTL_MS)) {
        map.set(sym, v);
      }
    });
  } catch (_) { /* corrupt / disabled storage — start empty */ }
  return map;
};

const saveGradesCache = (map) => {
  try {
    const now = Date.now();
    const obj = {};
    map.forEach((v, sym) => {
      if (v && hasPillarGrades(v.grades) && (!v.ts || now - v.ts < GRADES_CACHE_TTL_MS)) {
        obj[sym] = v;
      }
    });
    localStorage.setItem(GRADES_CACHE_KEY, JSON.stringify(obj));
  } catch (_) { /* quota / disabled — non-fatal */ }
};

export const ScannerCardsV5 = ({
  setups,""",
        "applied_marker": "const GRADES_CACHE_KEY = 'v5_tqs_grades_cache_v1'",
    },
    {
        "id": "2-ScannerCardsV5 sticky reconcile in cards memo",
        "path": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "old": "  const cards = useMemo(\n    () => buildCards({ setups, alerts, positions, messages }),\n    [setups, alerts, positions, messages]\n  );",
        "new": r"""  // v19.34.274 — sticky grades cache (seeded from localStorage on first
  // render so rings render instantly after a reload).
  const gradesCacheRef = useRef(null);
  if (gradesCacheRef.current === null) gradesCacheRef.current = loadGradesCache();

  const rawCards = useMemo(
    () => buildCards({ setups, alerts, positions, messages }),
    [setups, alerts, positions, messages]
  );

  // Reconcile pillar grades: learn from any scanner card that carries them,
  // backfill any that arrived without them. Targets `source === 'alert'`
  // (setups + alerts) — the only rows that flicker between REST/WS payloads.
  const cards = useMemo(() => {
    const cache = gradesCacheRef.current;
    const now = Date.now();
    for (const c of rawCards) {
      if (c.source !== 'alert') continue;
      if (hasPillarGrades(c.tqs_pillar_grades)) {
        cache.set(c.symbol, {
          grades: c.tqs_pillar_grades,
          grade: c.tqs_grade ?? null,
          score: c.tqs_score ?? null,
          ts: now,
        });
      } else {
        const cached = cache.get(c.symbol);
        if (cached && hasPillarGrades(cached.grades)) {
          c.tqs_pillar_grades = cached.grades;
          if (c.tqs_grade == null) c.tqs_grade = cached.grade;
          if (c.tqs_score == null) c.tqs_score = cached.score;
        }
      }
    }
    return rawCards;
  }, [rawCards]);

  // Persist the learned grades cache (debounced) so rings survive a reload.
  useEffect(() => {
    const t = setTimeout(() => saveGradesCache(gradesCacheRef.current), 800);
    return () => clearTimeout(t);
  }, [cards]);""",
        "applied_marker": "// v19.34.274 — sticky grades cache",
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
    print("  A2c PATCH — sticky provenance-ring grades cache (fixes ring flicker)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    if args.rollback:
        for e in EDITS:
            p = resolve(e["path"])
            bak = p + BAK
            if os.path.exists(bak):
                shutil.copy2(bak, p)
                print(f"  restored {e['path']}  sha={sha(p)}")
        print("\n  ROLLBACK complete.  NEXT: cd frontend && yarn build")
        return

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
        ed_plan.append((e, p, applied))

    if args.check:
        nready = sum(1 for _, _, a in ed_plan if not a)
        print(f"\n  CHECK ok. {nready} change(s) ready. Re-run with --apply.")
        return

    changed = 0
    for e, p, applied in ed_plan:
        if applied:
            print(f"  skip (applied): {e['path']}")
            continue
        cur = open(p, encoding="utf-8").read()
        if e["old"] not in cur:
            print(f"  \u274c anchor vanished at apply for {e['id']} — ABORT.")
            sys.exit(4)
        bak = p + BAK
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        open(p, "w", encoding="utf-8").write(cur.replace(e["old"], e["new"], 1))
        print(f"  patched {e['path']}  sha={sha(p)}  ({BAK} saved)")
        changed += 1
    print(f"\n  APPLY complete. {changed} change(s).")
    print("  NEXT: cd frontend && yarn build   (then hard-refresh the cockpit)")


if __name__ == "__main__":
    main()
