"""setup_retro_v90_1.py — re-bucket alert_outcomes EXCLUDING
state-management close noise that polluted v89's analytics.

Real outcomes only: stop_loss, target_hit, partial_target_*,
eod_*close, trailing_stop_*, manual_eod_close.
Excluded: consolidated_*, shrunk_to_zero_*, oca_closed_externally_*,
wrong_direction_phantom_*, external_close_*, operator_external_*,
manual_state_reset_*, manual_flatten_*, emergency_flatten_*.
"""
from __future__ import annotations
import os, re
from collections import defaultdict
from pathlib import Path
from statistics import median

ENV = Path(__file__).resolve().parent.parent / ".env"
for ln in ENV.read_text().splitlines():
    ln = ln.strip()
    if ln and not ln.startswith("#") and "=" in ln:
        k, _, v = ln.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

# Close reasons that DO represent real outcome of a setup playing out
REAL_REASONS = re.compile(
    r"^(stop_loss|target_hit|partial_target|eod_auto_close|"
    r"manual_eod_close|trailing_stop|tp[0-9]+_hit|profit_target)",
    re.IGNORECASE,
)
# Close reasons that are pure bot-state plumbing noise
NOISE_REASONS = re.compile(
    r"^(consolidated|shrunk_to_zero|oca_closed_externally|"
    r"wrong_direction_phantom|external_close|operator_external|"
    r"manual_state_reset|manual_flatten|emergency_flatten)",
    re.IGNORECASE,
)


def main() -> None:
    docs = list(db.alert_outcomes.find({}, {"_id": 0}))
    real, noise, other = [], [], []
    for d in docs:
        r = str(d.get("close_reason") or "")
        if REAL_REASONS.match(r):
            real.append(d)
        elif NOISE_REASONS.match(r):
            noise.append(d)
        else:
            other.append(d)

    print(f"\n[v90.1] total={len(docs)}  "
          f"real_outcomes={len(real)}  "
          f"noise_excluded={len(noise)}  "
          f"other={len(other)}\n")

    if other:
        from collections import Counter
        c = Counter(str(d.get("close_reason")) for d in other)
        print("  -- 'other' reasons (review/classify):")
        for k, n in c.most_common(20):
            print(f"     {k:<40} {n}")
        print()

    # Re-bucket real outcomes by (setup, grade)
    buckets = defaultdict(list)
    for d in real:
        buckets[(d.get("setup_type"), d.get("trade_grade"))].append(d)

    print(f"  {'setup':<28} {'grade':>5} {'n':>4} {'win%':>6} "
          f"{'avg_R':>8} {'med_R':>8} {'total_R':>9}")
    print("  " + "-" * 74)
    rows = []
    for (setup, grade), arr in buckets.items():
        n = len(arr)
        if n < 2:
            continue
        wins = sum(1 for d in arr if (d.get("r_multiple") or 0) > 0)
        rs = [float(d.get("r_multiple") or 0) for d in arr]
        rows.append((setup or "?", grade or "?", n,
                     100 * wins / n, sum(rs)/n, median(rs), sum(rs)))
    for setup, grade, n, win_pct, avg_r, med_r, tot_r in sorted(
        rows, key=lambda r: r[6]
    ):
        print(f"  {setup:<28} {grade:>5} {n:>4} {win_pct:>5.1f}% "
              f"{avg_r:>+7.2f}R {med_r:>+7.2f}R {tot_r:>+8.2f}R")


if __name__ == "__main__":
    main()
