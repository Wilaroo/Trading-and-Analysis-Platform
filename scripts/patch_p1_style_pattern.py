#!/usr/bin/env python3
"""
patch_p1_style_pattern.py  —  P1: Style = Pattern, Liquidity = Feasibility.

Four anchored, idempotent edits (SHA-reported, .bak backups, reversible):

  1. setup_taxonomy.style_of   — pass RAW setup (not canonicalize(raw)) so the
     classifier's raw-first _setup_lookup honors explicit horizon entries
     (breakdown_confirmed->multi_day) before canonicalize() strips the suffix.
     Fixes the SSOT over-collapse (diag_style_reconcile SSOT_BUG = 1822 alerts).
  2. trade_style_classifier.SETUP_TO_STYLE — add 4 operator-ratified entries
     (approaching_breakout/range_break/orb -> intraday; carry_forward_watch -> swing)
     to clear the REVIEW bucket (style_of=unknown).
  3. tqs_engine.calculate_tqs — the TQS WEIGHTING lens now follows the pattern's
     intrinsic style (SSOT style_of), NOT the liquidity-inflated stamp.
     Reversible via env TQS_STYLE_FROM_PATTERN=false. Execution stamp untouched.
  4. enhanced_scanner._enrich_alert_with_tqs — persist float weights_used +
     scoring_style INSIDE tqs_breakdown for audit + UI drill.

Usage (run from repo root, e.g. ~/Trading-and-Analysis-Platform):
    python3 scripts/patch_p1_style_pattern.py --check     # dry-run, report
    python3 scripts/patch_p1_style_pattern.py --apply      # write + .bak
    python3 scripts/patch_p1_style_pattern.py --rollback   # restore .bak
After --apply: restart backend, then run diag_p1_verify.py.
"""
import os
import sys
import shutil
import hashlib
import argparse

EDITS = [
    {
        "id": "1-setup_taxonomy.style_of (raw-first)",
        "path": "backend/services/setup_taxonomy.py",
        "old": "    return style_bucket_for_setup(canonicalize(raw))\n",
        "new": (
            "    # P1 (2026-06): pass the RAW setup so trade_style_classifier._setup_lookup\n"
            "    # honors explicit horizon entries (e.g. breakdown_confirmed->multi_day)\n"
            "    # BEFORE canonicalize() strips the suffix; canonicalize stays the\n"
            "    # fall-through inside _setup_lookup. Fixes the SSOT over-collapse.\n"
            "    return style_bucket_for_setup(raw)\n"
        ),
        "applied_marker": "    return style_bucket_for_setup(raw)\n",
    },
    {
        "id": "2-SETUP_TO_STYLE (+4 ratified)",
        "path": "backend/services/trade_style_classifier.py",
        "old": "    \"two_hundred_day_loss\": \"position\",\n}\n",
        "new": (
            "    \"two_hundred_day_loss\": \"position\",\n"
            "    # \u2500\u2500 ANTICIPATORY / WATCH (P1 2026-06, operator-ratified) \u2500\u2500\u2500\u2500\u2500\u2500\n"
            "    \"approaching_breakout\": \"intraday\", \"approaching_range_break\": \"intraday\",\n"
            "    \"approaching_orb\": \"intraday\", \"carry_forward_watch\": \"swing\",\n"
            "}\n"
        ),
        "applied_marker": "\"approaching_range_break\": \"intraday\"",
    },
    {
        "id": "3-tqs_engine.calculate_tqs (pattern weighting)",
        "path": "backend/services/tqs/tqs_engine.py",
        "old": (
            "        # Get weights for this trade style\n"
            "        weights = self._get_weights_for_style(trade_style)\n"
        ),
        "new": (
            "        # P1 (2026-06) TQS_STYLE_FROM_PATTERN: the WEIGHTING lens follows the\n"
            "        # pattern's intrinsic style (SSOT setup_taxonomy.style_of), NOT the\n"
            "        # liquidity-inflated stamped trade_style. Liquidity stays a feasibility/\n"
            "        # size concern (brackets/TIF), never a silent relabel of the score lens.\n"
            "        import os as _os\n"
            "        _scoring_style = trade_style\n"
            "        if _os.environ.get(\"TQS_STYLE_FROM_PATTERN\", \"true\").strip().lower() not in (\"false\", \"0\", \"no\", \"off\"):\n"
            "            try:\n"
            "                from services.setup_taxonomy import style_of as _style_of\n"
            "                _ps = (_style_of(setup_type) or \"\").strip().lower()\n"
            "                if _ps and _ps != \"unknown\" and _ps in self.STYLE_WEIGHTS:\n"
            "                    _scoring_style = _ps\n"
            "            except Exception as _se:\n"
            "                logger.warning(\"[tqs-p1] style_of(%s) failed: %s\", setup_type, _se)\n"
            "        trade_style = _scoring_style\n"
            "\n"
            "        # Get weights for this (pattern-intrinsic) trade style\n"
            "        weights = self._get_weights_for_style(_scoring_style)\n"
        ),
        "applied_marker": "TQS_STYLE_FROM_PATTERN",
    },
    {
        "id": "4-enhanced_scanner persist weights_used+scoring_style",
        "path": "backend/services/enhanced_scanner.py",
        "old": (
            "                    alert.tqs_weights = tqs_result.weights_used or {}\n"
            "                except Exception:\n"
            "                    pass\n"
        ),
        "new": (
            "                    alert.tqs_weights = tqs_result.weights_used or {}\n"
            "                    # P1 (2026-06): persist float weight profile + the pattern\n"
            "                    # scoring lens INSIDE tqs_breakdown so audits (diag [D]) and\n"
            "                    # the UI Style-Lens / TQS drawer can verify which lens scored it.\n"
            "                    if isinstance(alert.tqs_breakdown, dict):\n"
            "                        alert.tqs_breakdown[\"weights_used\"] = dict(tqs_result.weights_used or {})\n"
            "                        alert.tqs_breakdown[\"scoring_style\"] = tqs_result.trade_style\n"
            "                except Exception:\n"
            "                    pass\n"
        ),
        "applied_marker": "alert.tqs_breakdown[\"scoring_style\"]",
    },
]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:12] if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(path)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    print("=" * 84)
    print("  P1 PATCH — Style = Pattern, Liquidity = Feasibility")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    if args.rollback:
        ok = True
        for e in EDITS:
            p = resolve(e["path"])
            bak = p + ".p1bak"
            if os.path.exists(bak):
                shutil.copy2(bak, p)
                print(f"  restored {e['path']}  sha={sha(p)}")
            else:
                print(f"  no backup for {e['path']} (skip)")
                ok = False
        print("\n  ROLLBACK", "complete." if ok else "partial (some .p1bak missing).")
        return

    plans = []
    for e in EDITS:
        p = resolve(e["path"])
        if not os.path.exists(p):
            print(f"  \u274c MISSING FILE: {e['path']}")
            sys.exit(2)
        src = open(p, encoding="utf-8").read()
        already = e["applied_marker"] in src
        anchor_n = src.count(e["old"])
        status = "ALREADY-APPLIED" if already else ("READY" if anchor_n == 1 else f"ANCHOR x{anchor_n}")
        print(f"\n  [{e['id']}]")
        print(f"    file   : {e['path']}  sha={sha(p)}")
        print(f"    status : {status}")
        if not already and anchor_n != 1:
            print("    \u274c anchor not uniquely found — ABORT (no files changed).")
            sys.exit(3)
        plans.append((e, p, src, already))

    if args.check:
        n_ready = sum(1 for _, _, _, a in plans if not a)
        print(f"\n  CHECK ok. {n_ready} edit(s) ready, {len(plans)-n_ready} already applied.")
        print("  Re-run with --apply to write (creates .p1bak backups).")
        return

    # apply
    changed = 0
    for e, p, src, already in plans:
        if already:
            print(f"  skip (applied): {e['path']}")
            continue
        bak = p + ".p1bak"
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        new_src = src.replace(e["old"], e["new"], 1)
        open(p, "w", encoding="utf-8").write(new_src)
        print(f"  patched {e['path']}  sha={sha(p)}  (.p1bak saved)")
        changed += 1
    print(f"\n  APPLY complete. {changed} file(s) changed.")
    print("  NEXT: restart backend, set TQS_STYLE_FROM_PATTERN=true (default on),")
    print("        then run diag_p1_verify.py to confirm pattern-scoring ~100%.")


if __name__ == "__main__":
    main()
