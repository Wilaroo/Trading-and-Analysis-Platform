#!/usr/bin/env python3
"""
deploy_v19_34_213.py — TQS un-flooring + tape scale fix.

Idempotent, anchor-based. Safe to re-run. Applies 8 edits across 4 files:

  A. enhanced_scanner.py
     A1. tape_score emission: raw -1..+1  ->  canonical 0..10
     A2. alert grader: dead `>=70`  ->  `>=7`
     A3. scanner TQS call: pass strategy_win_rate / strategy_ev_r
  B. tqs/setup_quality.py
     B1. calculate_score(): accept win_rate_override / ev_r_override
     B2. prefer overrides over the learning_loop 0.5/0.0 default
  C. tqs/tqs_engine.py
     C1. calculate_tqs(): accept win_rate / expected_value_r
     C2. forward them to the Setup pillar
  D. opportunity_evaluator.py
     D1. post-gate TQS recalc: pass strategy_win_rate / strategy_ev_r

For each edit: if OLD present -> replace; elif NEW present -> already applied;
else -> MISMATCH (script aborts WITHOUT writing anything so nothing is half-applied).

After a clean apply it runs: git add -A && git commit && git push.
Then restart the backend.
"""

import os
import sys

REPO = os.getcwd()  # run from the repo root (~/Trading-and-Analysis-Platform)

EDITS = [
    # ---- A. enhanced_scanner.py ----
    ("backend/services/enhanced_scanner.py", "A1-tape-emit",
     """                    # Add tape reading to alert
                    alert.tape_score = tape.tape_score""",
     """                    # Add tape reading to alert
                    # v19.34.213 — normalize tape_score from the producer's raw
                    # -1..+1 scale to the canonical 0..10 scale that ALL consumers
                    # expect (setup_quality `/10`, dynamic_thresholds 4.0 floor,
                    # ai_assistant `/10`, default=5). Pre-fix the raw float was
                    # copied verbatim, which pinned the TQS tape pillar <=30 and
                    # made the alert grader's `>=70` check dead code. The raw
                    # -1..+1 value stays on `tape` (TapeReading) for L2 gating and
                    # the confirmation_for_long/short flags below.
                    alert.tape_score = round((tape.tape_score + 1.0) * 5.0, 2)"""),

    ("backend/services/enhanced_scanner.py", "A2-grader",
     """        # 3. Tape confirmation
        if self.tape_confirmation and self.tape_score >= 70:""",
     """        # 3. Tape confirmation
        # v19.34.213 — tape_score is now on the 0-10 scale; was a dead `>=70`
        # check against the old raw -1..+1 copy (the +20 bonus never fired).
        if self.tape_confirmation and self.tape_score >= 7:"""),

    ("backend/services/enhanced_scanner.py", "A3-scanner-call",
     """                alert_priority=alert.priority.value if hasattr(alert.priority, 'value') else str(alert.priority),
                ai_model_direction=ai_dir,""",
     """                alert_priority=alert.priority.value if hasattr(alert.priority, 'value') else str(alert.priority),
                win_rate=getattr(alert, 'strategy_win_rate', None),
                expected_value_r=getattr(alert, 'strategy_ev_r', None),
                ai_model_direction=ai_dir,"""),

    # ---- B. tqs/setup_quality.py ----
    ("backend/services/tqs/setup_quality.py", "B1-signature",
     """        risk_reward: float = 2.0,
        alert_priority: str = "medium"
    ) -> SetupQualityScore:""",
     """        risk_reward: float = 2.0,
        alert_priority: str = "medium",
        win_rate_override: Optional[float] = None,
        ev_r_override: Optional[float] = None
    ) -> SetupQualityScore:"""),

    ("backend/services/tqs/setup_quality.py", "B2-winrate-block",
     """        # 2. Historical Win Rate Score (25% weight)
        win_rate = 0.5  # Default
        ev_r = 0.0
        
        if self._learning_loop:
            try:
                stats = await self._learning_loop.get_contextual_win_rate(setup_type=base_setup)
                if stats.get("sample_size", 0) >= 5:
                    win_rate = stats.get("win_rate", 0.5)
                    ev_r = stats.get("expected_value_r", 0.0)
            except Exception as e:
                logger.debug(f"Could not get learning stats: {e}")""",
     """        # 2. Historical Win Rate Score (25% weight)
        win_rate = 0.5  # Default
        ev_r = 0.0
        
        # v19.34.213 — prefer the win_rate / EV the scanner already stamped on the
        # alert (strategy_win_rate / strategy_ev_r). Pre-fix this pillar ALWAYS
        # re-fetched via learning_loop.get_contextual_win_rate(), which needs >=5
        # contextual samples and otherwise returned the 0.5/0.0 default for 100%
        # of alerts — flooring the highest-weighted TQS pillar (empirically the
        # setup pillar was pinned near 43, never reaching B).
        if win_rate_override is not None:
            win_rate = win_rate_override
            if ev_r_override is not None:
                ev_r = ev_r_override
        elif self._learning_loop:
            try:
                stats = await self._learning_loop.get_contextual_win_rate(setup_type=base_setup)
                if stats.get("sample_size", 0) >= 5:
                    win_rate = stats.get("win_rate", 0.5)
                    ev_r = stats.get("expected_value_r", 0.0)
            except Exception as e:
                logger.debug(f"Could not get learning stats: {e}")"""),

    # ---- C. tqs/tqs_engine.py ----
    ("backend/services/tqs/tqs_engine.py", "C1-signature",
     """        risk_reward: float = 2.0,
        alert_priority: str = "medium",
        # Context overrides""",
     """        risk_reward: float = 2.0,
        alert_priority: str = "medium",
        # v19.34.213 — win_rate / EV the scanner already computed on the alert
        # (strategy_win_rate / strategy_ev_r). Forwarded to the Setup pillar so it
        # stops re-fetching learning_loop (which returned the 0.5/0.0 default for
        # ~100% of alerts and floored the highest-weighted pillar).
        win_rate: Optional[float] = None,
        expected_value_r: Optional[float] = None,
        # Context overrides"""),

    ("backend/services/tqs/tqs_engine.py", "C2-forward",
     """                risk_reward=risk_reward,
                alert_priority=alert_priority
            )
            result.pillar_grades["setup"] = result.setup_score.grade""",
     """                risk_reward=risk_reward,
                alert_priority=alert_priority,
                win_rate_override=win_rate,
                ev_r_override=expected_value_r
            )
            result.pillar_grades["setup"] = result.setup_score.grade"""),

    # ---- D. opportunity_evaluator.py ----
    ("backend/services/opportunity_evaluator.py", "D1-postgate-call",
     """                        alert_priority=alert.get("priority", "medium"),
                        ai_model_direction=pred_dir,""",
     """                        alert_priority=alert.get("priority", "medium"),
                        win_rate=alert.get("strategy_win_rate"),
                        expected_value_r=alert.get("strategy_ev_r"),
                        ai_model_direction=pred_dir,"""),
]


def main():
    planned = []   # (path, tag, new_content)
    already = []
    mismatch = []

    # cache file contents so we apply multiple edits per file in-memory
    cache = {}
    for path, tag, old, new in EDITS:
        full = os.path.join(REPO, path)
        if not os.path.exists(full):
            mismatch.append((tag, f"file not found: {path}"))
            continue
        if full not in cache:
            with open(full, "r", encoding="utf-8") as fh:
                cache[full] = fh.read()
        content = cache[full]
        if old in content:
            cache[full] = content.replace(old, new, 1)
            planned.append((path, tag))
        elif new in content:
            already.append((path, tag))
        else:
            mismatch.append((tag, f"anchor not found in {path}"))

    print("=" * 64)
    print("v19.34.213 deploy — dry analysis")
    print("=" * 64)
    for p, t in planned:
        print(f"  WILL APPLY : {t:22s} {p}")
    for p, t in already:
        print(f"  already ok : {t:22s} {p}")
    for t, why in mismatch:
        print(f"  !! MISMATCH: {t:22s} {why}")

    if mismatch:
        print("\nABORTING — one or more anchors did not match. NOTHING was written.")
        print("Paste this output back so the anchors can be re-synced to your tree.")
        sys.exit(2)

    if not planned:
        print("\nNothing to do — already fully applied. (idempotent no-op)")
        sys.exit(0)

    # write all touched files
    for full, content in cache.items():
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
    print(f"\nApplied {len(planned)} edit(s) across {len(cache)} file(s).")

    # syntax-check the four touched source files
    import ast
    for path in {p for p, _ in planned}:
        full = os.path.join(REPO, path)
        try:
            ast.parse(open(full, encoding="utf-8").read())
        except SyntaxError as e:
            print(f"!! SYNTAX ERROR in {path}: {e} — fix before restart!")
            sys.exit(3)
    print("Syntax OK on all touched files.")

    # commit + push so the .bat git-checkout-on-restart can't wipe it
    rc = os.system('git add -A && git commit -m "v19.34.213: TQS un-flooring '
                   '(thread real win_rate/EV into Setup pillar) + tape 0-10 scale fix" '
                   '&& git push')
    if rc != 0:
        print("\n⚠️  git commit/push returned non-zero — resolve before restarting "
              "(uncommitted changes get wiped by the restart script).")
        sys.exit(4)
    print("\n✅ Committed + pushed. Now restart the backend to load the changes.")


if __name__ == "__main__":
    main()
