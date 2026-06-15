#!/usr/bin/env python3
"""
repair_v320b_symbol_field.py
=============================
v19.34.320b mid-run bug: the MongoDB projection in the scan loop
omitted `symbol` and `bar_size`, so the 35,524 docs in
ib_historical_data_quarantine were inserted without those two fields.
The OHLCV data + `_quarantined_*` metadata are intact, but querying or
restoring by symbol fails.

This script BACKFILLS `symbol` and `bar_size` on every quarantined doc
using the deterministic (`_quarantine_window_start`,
`_quarantine_price_ratio`) tuple from the v320b execution table.

Each TRUE_RECYCLE symbol has a unique (window_start, price_ratio) pair
(price ratios span 14 orders of magnitude → no collisions). Matching
uses a ±2% tolerance on price_ratio to absorb any float-precision drift.

USAGE
-----
  --check   : dry-run, prints expected vs found counts per symbol
  (default) : writes `symbol` and `bar_size` onto matching docs
NO data is destroyed; this is a pure $set update.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

# ── canonical mapping from v19.34.320b execution on 2026-06-15T19:17:17 ──
# (symbol, window_start_iso, price_ratio_printed, expected_count)
MAPPING = [
    ("TOPS",  "2017-05-11T00:00:00", 58511747135.70,   2900),
    ("PPCB",  "2013-10-01T00:00:00", 188177438.78,       11),
    ("XTIA",  "2020-01-07T00:00:00", 90419135.75,       727),
    ("SUNE",  "2024-06-12T00:00:00", 2466654.33,       3479),
    ("NUWE",  "2019-01-04T00:00:00", 2076763.44,       1299),
    ("HIND",  "2024-09-23T00:00:00", 1292861.90,       1179),
    ("BNBX",  "2025-03-14T00:00:00", 1159859.34,        316),
    ("CENN",  "2019-12-20T00:00:00", 88156.12,          719),
    ("GPUS",  "2023-05-19T00:00:00", 39109.67,          858),
    ("GTBP",  "2012-07-23T00:00:00", 27997.36,          158),
    ("FAZ",   "2018-03-22T00:00:00", 6087.03,           345),
    ("RCAT",  "2018-03-22T00:00:00", 5727.94,          1152),
    ("DFSC",  "2024-10-23T00:00:00", 2312.51,           464),
    ("SBLX",  "2023-09-18T00:00:00", 1729.50,          1764),
    ("FRMM",  "2022-12-19T00:00:00", 1686.13,           849),
    ("CRVO",  "2018-12-14T00:00:00", 1401.47,           731),
    ("BLIN",  "2017-07-25T00:00:00", 875.75,           1892),
    ("TWAV",  "2023-01-04T00:00:00", 628.20,           2062),
    ("LTM",   "2024-07-25T00:00:00", 531.75,           4512),
    ("XWEL",  "2018-01-08T00:00:00", 521.55,            763),
    ("DUOT",  "2013-06-18T00:00:00", 403.44,            322),
    ("OGEN",  "2013-04-09T00:00:00", 202.72,           1131),
    ("SURG",  "2013-09-25T00:00:00", 169.47,            231),
    ("CNTN",  "2023-11-22T00:00:00", 106.06,            426),
    ("HSDT",  "2018-01-23T00:00:00", 101.91,              8),
    ("PFSA",  "2025-07-14T00:00:00", 55.90,             736),
    ("ACDC",  "2021-10-01T00:00:00", 27.43,             388),
    ("CD",    "2020-05-19T00:00:00", 23.45,             688),
    ("STEX",  "2024-06-12T00:00:00", 22.08,             979),
    ("PROP",  "2018-07-25T00:00:00", 16.75,              16),
    ("SAFX",  "2025-06-09T00:00:00", 15.15,             725),
    ("SRXH",  "2013-10-01T00:00:00", 14.68,              14),
    ("CTM",   "2013-09-10T00:00:00", 10.23,               1),
    ("NEXM",  "2018-03-28T00:00:00", 8.00,             1285),
    ("SPCX",  "2026-06-12T00:00:00", 7.67,               24),
    ("DMAC",  "2015-07-09T00:00:00", 7.16,               27),
    ("LIMN",  "2025-05-01T00:00:00", 7.04,              827),
    ("LGO",   "2008-03-10T00:00:00", 5.91,              234),
    ("KWM",   "2025-05-14T00:00:00", 5.66,              586),
    ("ABEV",  "2002-10-16T00:00:00", 5.46,               24),
    ("APLD",  "2018-03-22T00:00:00", 4.95,               45),
    ("SLNO",  "2017-10-06T00:00:00", 3.31,              627),
]
PATCH_TAG = "v19_34_320b_repair"


def _load_env(repo: Path):
    cand = repo / "backend" / ".env"
    if cand.is_file():
        for ln in cand.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(),
                                      v.strip().strip('"').strip("'"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path.home() / "Trading-and-Analysis-Platform"))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--tolerance", type=float, default=0.02,
                    help="price_ratio tolerance (fraction). default 0.02 = ±2%%")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    _load_env(repo)

    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    db = client[os.environ.get("DB_NAME") or "tradecommand"]
    q = db["ib_historical_data_quarantine"]

    print("═" * 72)
    print(f" {PATCH_TAG} — backfill symbol/bar_size on quarantined docs")
    print("═" * 72)
    total_q = q.count_documents({})
    missing = q.count_documents({"symbol": {"$exists": False}})
    have_sym = q.count_documents({"symbol": {"$exists": True}})
    print(f"  total docs              : {total_q:,}")
    print(f"  missing `symbol`        : {missing:,}")
    print(f"  already have `symbol`   : {have_sym:,}")
    print(f"  mapping rows            : {len(MAPPING)}")
    print(f"  expected target         : {sum(m[3] for m in MAPPING):,}")
    print(f"  price_ratio tolerance   : ±{args.tolerance*100:.1f}%")
    print()

    if missing == 0:
        print("  [ok] no docs missing `symbol`. nothing to do.")
        return 0

    print(f"  {'sym':<7} {'window_start':<22} {'ratio_target':>16} {'found':>7} "
          f"{'expected':>9} {'match':>6}")
    print(f"  {'-' * 72}")

    actions = []
    discrepancies = 0
    for sym, ws, ratio, expected in MAPPING:
        lo = ratio * (1.0 - args.tolerance)
        hi = ratio * (1.0 + args.tolerance)
        flt = {
            "_quarantine_window_start": ws,
            "_quarantine_price_ratio": {"$gte": lo, "$lte": hi},
        }
        found = q.count_documents(flt)
        ok = (found == expected)
        if not ok:
            discrepancies += 1
        print(f"  {sym:<7} {ws:<22} {ratio:>16.2f} {found:>7} "
              f"{expected:>9} {'✓' if ok else '✗':>6}")
        actions.append((sym, flt, found, expected))

    print()
    if discrepancies:
        print(f"  [!] {discrepancies} discrepancy/discrepancies in pre-check.")
        print(f"      Re-run with a different --tolerance if you want to broaden the band,")
        print(f"      OR inspect manually before proceeding.")
        if not args.check:
            print(f"      Aborting — re-run with --check to inspect, or fix tolerance.")
            return 4
    else:
        print(f"  [ok] all {len(MAPPING)} symbols matched expected counts exactly.")

    if args.check:
        print()
        print(f"  --check: no writes. re-run WITHOUT --check to backfill.")
        return 0

    print()
    print(f"─── backfill ───")
    total_updated = 0
    for sym, flt, found, expected in actions:
        if found == 0:
            continue
        res = q.update_many(flt, {"$set": {
            "symbol": sym,
            "bar_size": "1 day",
            "_repaired_by": PATCH_TAG,
        }})
        mark = "✓" if res.modified_count == expected else "!"
        print(f"  [{mark}] {sym:<7} updated={res.modified_count}  expected={expected}")
        total_updated += res.modified_count

    print()
    print(f"─── summary ───")
    print(f"  symbols processed   : {len(MAPPING)}")
    print(f"  docs updated        : {total_updated:,}")
    print(f"  docs still missing  : {q.count_documents({'symbol': {'$exists': False}}):,}")
    print()
    print("Verify:")
    print('  .venv/bin/python -c "from pymongo import MongoClient; import os')
    print("  from pathlib import Path")
    print("  for ln in Path('backend/.env').read_text().splitlines():")
    print("      if '=' in ln and not ln.startswith('#'):")
    print("          k,v=ln.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))")
    print('  d=MongoClient(os.environ[chr(34)+chr(77)+chr(79)+chr(78)+chr(71)+chr(79)+chr(95)+chr(85)+chr(82)+chr(76)+chr(34)])[os.environ.get(chr(34)+chr(68)+chr(66)+chr(95)+chr(78)+chr(65)+chr(77)+chr(69)+chr(34)) or chr(34)+chr(116)+chr(114)+chr(97)+chr(100)+chr(101)+chr(99)+chr(111)+chr(109)+chr(109)+chr(97)+chr(110)+chr(100)+chr(34)]')
    print('  print(d.ib_historical_data_quarantine.count_documents({chr(34)+chr(115)+chr(121)+chr(109)+chr(98)+chr(111)+chr(108)+chr(34):chr(34)+chr(83)+chr(80)+chr(67)+chr(88)+chr(34)}))"')
    print()
    print("Or simpler:")
    print('  .venv/bin/python /tmp/diag_spcx_forensics.py   # section adjusted to')
    print('                                                  # show quarantine count')
    return 0


if __name__ == "__main__":
    sys.exit(main())
