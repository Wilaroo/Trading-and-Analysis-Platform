#!/usr/bin/env python3
"""
deploy_v19_34_214.py — EV reload fix + no-data (0.0) guard. Builds on v213.

Idempotent, anchor-based, abort-safe. 3 edits across 2 files:

  E1. enhanced_scanner._load_strategy_stats():
      also reload r_outcomes / avg_win_r / avg_loss_r / expected_value_r
      (they were saved via asdict but never reloaded -> EV reset to 0 every
       restart, zeroing the Setup pillar's EV sub-component for 100% of alerts).
  E2. enhanced_scanner scanner-side TQS call:
      coerce strategy_win_rate / strategy_ev_r 0.0 -> None so a no-data setup
      falls back to the 0.5 neutral instead of scoring a real "0% / 0 EV".
  E3. opportunity_evaluator post-gate TQS call: same 0.0 -> None guard.

Run from repo root (~/Trading-and-Analysis-Platform). Commits + pushes on success.
"""
import os
import sys

REPO = os.getcwd()

EDITS = [
    ("backend/services/enhanced_scanner.py", "E1-load-ev",
     """                            avg_rr_achieved=doc.get("avg_rr_achieved", 0.0),
                            last_updated=doc.get("last_updated", "")
                        )""",
     """                            avg_rr_achieved=doc.get("avg_rr_achieved", 0.0),
                            last_updated=doc.get("last_updated", ""),
                            # v19.34.214 — the EV / R-multiple fields were SAVED
                            # (via asdict) but never reloaded here, so
                            # expected_value_r reset to 0.0 on every restart —
                            # zeroing the Setup pillar's EV sub-component for
                            # 100% of alerts. Reload them so EV survives restarts.
                            r_outcomes=doc.get("r_outcomes", []) or [],
                            avg_win_r=doc.get("avg_win_r", 0.0),
                            avg_loss_r=doc.get("avg_loss_r", 1.0),
                            expected_value_r=doc.get("expected_value_r", 0.0),
                        )"""),

    ("backend/services/enhanced_scanner.py", "E2-scanner-guard",
     """                alert_priority=alert.priority.value if hasattr(alert.priority, 'value') else str(alert.priority),
                win_rate=getattr(alert, 'strategy_win_rate', None),
                expected_value_r=getattr(alert, 'strategy_ev_r', None),
                ai_model_direction=ai_dir,""",
     """                alert_priority=alert.priority.value if hasattr(alert.priority, 'value') else str(alert.priority),
                # v19.34.214 — coerce the no-data default (0.0) to None so the
                # Setup pillar falls back to its neutral 0.5, instead of scoring
                # a real "0% win rate" / "0 EV" that tanks setups lacking stats.
                win_rate=(getattr(alert, 'strategy_win_rate', None) or None),
                expected_value_r=(getattr(alert, 'strategy_ev_r', None) or None),
                ai_model_direction=ai_dir,"""),

    ("backend/services/opportunity_evaluator.py", "E3-postgate-guard",
     """                        alert_priority=alert.get("priority", "medium"),
                        win_rate=alert.get("strategy_win_rate"),
                        expected_value_r=alert.get("strategy_ev_r"),
                        ai_model_direction=pred_dir,""",
     """                        alert_priority=alert.get("priority", "medium"),
                        win_rate=(alert.get("strategy_win_rate") or None),
                        expected_value_r=(alert.get("strategy_ev_r") or None),
                        ai_model_direction=pred_dir,"""),
]


def main():
    planned, already, mismatch, cache = [], [], [], {}
    for path, tag, old, new in EDITS:
        full = os.path.join(REPO, path)
        if not os.path.exists(full):
            mismatch.append((tag, f"file not found: {path}")); continue
        if full not in cache:
            cache[full] = open(full, encoding="utf-8").read()
        c = cache[full]
        if old in c:
            cache[full] = c.replace(old, new, 1); planned.append((path, tag))
        elif new in c:
            already.append((path, tag))
        else:
            mismatch.append((tag, f"anchor not found in {path}"))

    print("=" * 64); print("v19.34.214 deploy"); print("=" * 64)
    for p, t in planned:  print(f"  WILL APPLY : {t:20s} {p}")
    for p, t in already:  print(f"  already ok : {t:20s} {p}")
    for t, w in mismatch: print(f"  !! MISMATCH: {t:20s} {w}")

    if mismatch:
        print("\nABORTING — anchor mismatch. NOTHING written. Paste this back."); sys.exit(2)
    if not planned:
        print("\nNothing to do — already applied (idempotent no-op)."); sys.exit(0)

    for full, content in cache.items():
        open(full, "w", encoding="utf-8").write(content)
    import ast
    for path in {p for p, _ in planned}:
        ast.parse(open(os.path.join(REPO, path), encoding="utf-8").read())
    print(f"\nApplied {len(planned)} edit(s). Syntax OK.")

    rc = os.system('git add -A && git commit -m "v19.34.214: reload EV/R fields on '
                   'restart + guard no-data (0.0) win_rate/EV from tanking Setup pillar" '
                   '&& git push')
    if rc != 0:
        print("\n⚠️  git push non-zero — resolve before restart (wipe hazard)."); sys.exit(4)
    print("\n✅ Committed + pushed. Restart the backend to load.")


if __name__ == "__main__":
    main()
