# IB Fill Tape Audit — 2026-05-04

**Account: DUN615665 (PAPER — DU* prefix)**

## Operator findings

- **Prior-day carryover flushed today** — STX (-17sh). These extra sells likely came from positions held overnight. Cross-check `bot_trades` for this symbol with `executed_at < today_start_ET` to confirm the bot owned them. If the bot has no record, they are **genuine orphan shares** that need a `POST /api/trading-bot/reconcile` before the bot can report on the round-trip PnL accurately.
- **Heavy fragmentation** (broker venue split) — V (46f / 9v), BKNG (87f / 9v), SBUX (28f / 7v), MO (22f / 7v), NCLH (19f / 7v). The bot's `bot_trades` row should aggregate these into a single fill record per execution; if Mongo shows separate rows per venue fragment for the same parent order, the executor's fill-aggregation is broken.
- **Top losers (gross)** — BKNG $-2,059, APH $-1,553, VALE $-1,528, NXPI $-1,339, MO $-1,179
- **Winners (gross)** — WDC $+281, BP $+79, ELV $+27
- **Short-direction trades today** — LHX, GM, FDX, CRCL. Confirm `direction='short'` on the matching `bot_trades` rows; v19.29 added a 30s direction-stability gate so a SHORT row materialized right after a LONG eval should NOT exist.

## Summary

- **Total fills**: 328
- **Symbols traded**: 21
- **Total bought**: $2,089,801.32
- **Total sold**: $2,088,093.06
- **Realized PnL (FIFO, gross of fees)**: $-14,249.67
- **Total fees**: $310.70
- **Net realized after fees**: $-14,560.37
- **Symbols with non-zero residual**: 1 (net residual shares: -17)

## Verdict counts

- `CARRYOVER_FLATTENED`: 1
- `MULTI_LEG_MIXED`: 3
- `MULTI_LEG_LONG`: 13
- `MULTI_LEG_SHORT`: 4

## Per-symbol audit (severity sorted)

| Symbol | Verdict | Fills | Bought | Sold | Net | Realized PnL | Fees | Earliest | Latest | EOD-flat? | Frag warn |
|---|---|---:|---:|---:|---:|---:|---:|---|---|:---:|---|
| **STX** | `CARRYOVER_FLATTENED` | 14 | 274 | 291 | -17 | $-860.32 | $12.47 | 9:32 AM | 3:57 PM | ✓ | - |
| **V** | `MULTI_LEG_MIXED` | 46 | 1,447 | 1,447 | +0 | $-975.46 | $24.85 | 9:33 AM | 3:51 PM | - | high_fragmentation_46_fills |
| **WDC** | `MULTI_LEG_MIXED` | 12 | 120 | 120 | +0 | $+281.00 | $13.14 | 9:43 AM | 10:29 AM | - | - |
| **LITE** | `MULTI_LEG_MIXED` | 5 | 124 | 124 | +0 | $-22.94 | $6.55 | 9:31 AM | 2:00 PM | - | - |
| **BKNG** | `MULTI_LEG_LONG` | 87 | 740 | 740 | +0 | $-2,059.01 | $10.17 | 9:35 AM | 11:48 AM | - | high_fragmentation_87_fills |
| **SBUX** | `MULTI_LEG_LONG` | 28 | 1,245 | 1,245 | +0 | $-1,073.72 | $18.65 | 9:37 AM | 3:51 PM | - | venue_spread_7_venues |
| **MO** | `MULTI_LEG_LONG` | 22 | 1,701 | 1,701 | +0 | $-1,179.28 | $19.93 | 9:35 AM | 12:55 PM | - | venue_spread_7_venues |
| **NCLH** | `MULTI_LEG_LONG` | 19 | 2,422 | 2,422 | +0 | $-72.66 | $25.59 | 9:43 AM | 3:55 PM | ✓ | venue_spread_7_venues |
| **BP** | `MULTI_LEG_LONG` | 12 | 1,200 | 1,200 | +0 | $+79.02 | $13.42 | 1:00 PM | 3:51 PM | - | - |
| **APH** | `MULTI_LEG_LONG` | 10 | 588 | 588 | +0 | $-1,553.08 | $7.71 | 9:32 AM | 11:21 AM | - | - |
| **LHX** | `MULTI_LEG_SHORT` | 10 | 309 | 309 | +0 | $-235.11 | $6.73 | 9:34 AM | 11:18 AM | - | - |
| **NXPI** | `MULTI_LEG_LONG` | 8 | 333 | 333 | +0 | $-1,339.23 | $6.06 | 9:34 AM | 3:55 PM | ✓ | - |
| **TER** | `MULTI_LEG_LONG` | 7 | 197 | 197 | +0 | $-791.94 | $3.42 | 1:29 PM | 3:55 PM | ✓ | - |
| **GM** | `MULTI_LEG_SHORT` | 7 | 397 | 397 | +0 | $-107.19 | $4.68 | 12:56 PM | 3:51 PM | - | - |
| **PYPL** | `MULTI_LEG_LONG` | 7 | 816 | 816 | +0 | $-366.20 | $9.17 | 9:46 AM | 3:51 PM | - | - |
| **STM** | `MULTI_LEG_LONG` | 7 | 747 | 747 | +0 | $-694.71 | $8.47 | 9:35 AM | 10:29 AM | - | - |
| **FDX** | `MULTI_LEG_SHORT` | 7 | 220 | 220 | +0 | $-234.30 | $5.70 | 9:41 AM | 9:46 AM | - | - |
| **VALE** | `MULTI_LEG_LONG` | 6 | 5,179 | 5,179 | +0 | $-1,527.98 | $54.52 | 9:44 AM | 3:55 PM | ✓ | - |
| **SOXS** | `MULTI_LEG_LONG` | 5 | 5,166 | 5,166 | +0 | $-671.58 | $54.11 | 12:52 PM | 3:55 PM | ✓ | - |
| **ELV** | `MULTI_LEG_LONG` | 5 | 113 | 113 | +0 | $+27.12 | $2.89 | 9:34 AM | 3:55 PM | ✓ | - |
| **CRCL** | `MULTI_LEG_SHORT` | 4 | 190 | 190 | +0 | $-872.10 | $2.47 | 9:38 AM | 10:44 AM | - | - |

## Per-symbol leg detail

### STX — `CARRYOVER_FLATTENED`

- Bought: **274sh** for **$202,573.30** (avg $739.3186)
- Sold: **291sh** for **$214,254.39** (avg $736.2694)
- Net position end-of-tape: **-17sh** (open residual: -17sh)
- Realized PnL: **$-860.32** (after fees: $-872.79)
- Fees: **$12.47**
- Fragmentation: 14 fills across 3 venues — ARCA, IBKRATS, NASDAQ
- Time window: 9:32 AM → 3:57 PM
- **Touched EOD-flatten window** (≥3:55 PM)

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 25 | $735.2900 | $735.0900 | 9:32 AM | 3:51 PM | $-5.00 |
  | LONG | 44 | $735.2900 | $735.0900 | 9:32 AM | 3:51 PM | $-8.80 |
  | LONG | 31 | $735.2900 | $735.0900 | 9:32 AM | 3:51 PM | $-6.20 |
  | LONG | 13 | $735.2900 | $735.0900 | 9:32 AM | 3:51 PM | $-2.60 |
  | LONG | 13 | $742.3700 | $735.0900 | 9:42 AM | 3:51 PM | $-94.64 |
  | LONG | 40 | $742.3700 | $737.6200 | 9:42 AM | 3:56 PM | $-190.00 |
  | LONG | 15 | $742.3700 | $737.6200 | 9:42 AM | 3:56 PM | $-71.25 |
  | LONG | 40 | $742.3700 | $736.1600 | 9:42 AM | 3:56 PM | $-248.40 |
  | LONG | 1 | $741.6900 | $736.1600 | 9:47 AM | 3:56 PM | $-5.53 |
  | LONG | 12 | $741.6900 | $736.1600 | 9:47 AM | 3:56 PM | $-66.36 |
  | LONG | 2 | $741.6900 | $736.1600 | 9:47 AM | 3:56 PM | $-11.06 |
  | LONG | 38 | $741.6900 | $737.7300 | 9:47 AM | 3:57 PM | $-150.48 |

### V — `MULTI_LEG_MIXED`

- Bought: **1,447sh** for **$473,665.31** (avg $327.3430)
- Sold: **1,447sh** for **$472,689.85** (avg $326.6689)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-975.46** (after fees: $-1,000.31)
- Fees: **$24.85**
- Fragmentation: 46 fills across 9 venues — ARCA, BATS, BYX, DRCTEDGE, IBKRATS, IEX, MEMX, NASDAQ, NYSE
- Time window: 9:33 AM → 3:51 PM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 69 | $327.5000 | $326.7900 | 9:33 AM | 9:35 AM | $-48.99 |
  | LONG | 100 | $327.5000 | $326.7900 | 9:33 AM | 9:35 AM | $-71.00 |
  | LONG | 27 | $327.5000 | $326.7900 | 9:33 AM | 9:35 AM | $-19.17 |
  | LONG | 60 | $327.5000 | $326.7900 | 9:33 AM | 9:35 AM | $-42.60 |
  | LONG | 61 | $327.7100 | $326.6600 | 9:34 AM | 9:35 AM | $-64.05 |
  | LONG | 4 | $327.7100 | $326.4600 | 9:34 AM | 9:35 AM | $-5.00 |
  | LONG | 9 | $327.7100 | $326.4600 | 9:34 AM | 9:35 AM | $-11.25 |
  | LONG | 37 | $327.7100 | $326.4600 | 9:34 AM | 9:35 AM | $-46.25 |
  | LONG | 25 | $327.7100 | $326.4600 | 9:34 AM | 9:35 AM | $-31.25 |
  | LONG | 5 | $327.7100 | $326.4600 | 9:34 AM | 9:35 AM | $-6.25 |
  | LONG | 40 | $327.7100 | $326.4600 | 9:34 AM | 9:35 AM | $-50.00 |
  | LONG | 35 | $327.7100 | $326.4600 | 9:34 AM | 9:35 AM | $-43.75 |
  | LONG | 40 | $327.7100 | $326.4600 | 9:34 AM | 9:35 AM | $-50.00 |
  | LONG | 21 | $327.1500 | $326.4600 | 9:35 AM | 9:35 AM | $-14.49 |
  | LONG | 19 | $327.1500 | $326.4600 | 9:35 AM | 9:35 AM | $-13.11 |
  | LONG | 21 | $327.1500 | $326.4600 | 9:35 AM | 9:35 AM | $-14.49 |
  | LONG | 30 | $327.1500 | $326.4600 | 9:35 AM | 9:35 AM | $-20.70 |
  | LONG | 29 | $327.1500 | $326.4600 | 9:35 AM | 9:35 AM | $-20.01 |
  | LONG | 21 | $327.1500 | $326.4600 | 9:35 AM | 9:35 AM | $-14.49 |
  | LONG | 105 | $327.1500 | $326.4600 | 9:35 AM | 9:35 AM | $-72.45 |
  | LONG | 10 | $327.1500 | $326.4600 | 9:35 AM | 9:35 AM | $-6.90 |
  | SHORT | 26 | $326.9600 | $327.3200 | 9:36 AM | 9:36 AM | $-9.36 |
  | SHORT | 3 | $326.9600 | $327.1200 | 9:36 AM | 9:36 AM | $-0.48 |
  | SHORT | 43 | $326.9600 | $327.1200 | 9:36 AM | 9:36 AM | $-6.88 |
  | SHORT | 19 | $326.9600 | $327.1200 | 9:36 AM | 9:36 AM | $-3.04 |
  | SHORT | 21 | $326.9600 | $327.1200 | 9:36 AM | 9:36 AM | $-3.36 |
  | SHORT | 24 | $326.9600 | $327.1200 | 9:36 AM | 9:36 AM | $-3.84 |
  | SHORT | 29 | $326.9600 | $327.1200 | 9:36 AM | 9:36 AM | $-4.64 |
  | SHORT | 51 | $326.9600 | $327.1200 | 9:36 AM | 9:36 AM | $-8.16 |
  | SHORT | 40 | $326.9600 | $327.1200 | 9:36 AM | 9:36 AM | $-6.40 |
  | SHORT | 40 | $326.6200 | $326.6900 | 9:37 AM | 9:37 AM | $-2.80 |
  | SHORT | 44 | $326.6200 | $326.6900 | 9:37 AM | 9:37 AM | $-3.08 |
  | SHORT | 40 | $326.6200 | $326.6900 | 9:37 AM | 9:37 AM | $-2.80 |
  | SHORT | 74 | $326.6200 | $326.6900 | 9:37 AM | 9:37 AM | $-5.18 |
  | SHORT | 56 | $326.6200 | $326.6900 | 9:37 AM | 9:37 AM | $-3.92 |
  | LONG | 9 | $328.1300 | $326.6500 | 10:50 AM | 3:51 PM | $-13.32 |
  | LONG | 40 | $328.1300 | $326.6500 | 10:50 AM | 3:51 PM | $-59.20 |
  | LONG | 40 | $328.1300 | $326.6900 | 10:50 AM | 3:51 PM | $-57.60 |
  | LONG | 40 | $328.1300 | $326.6900 | 10:50 AM | 3:51 PM | $-57.60 |
  | LONG | 40 | $328.1300 | $326.6900 | 10:50 AM | 3:51 PM | $-57.60 |

### WDC — `MULTI_LEG_MIXED`

- Bought: **120sh** for **$53,617.40** (avg $446.8117)
- Sold: **120sh** for **$53,898.40** (avg $449.1533)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$+281.00** (after fees: $+267.86)
- Fees: **$13.14**
- Fragmentation: 12 fills across 2 venues — IBKRATS, NASDAQ
- Time window: 9:43 AM → 10:29 AM
- **Sold before buying — short-direction round-trip**

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | SHORT | 20 | $447.5700 | $452.7900 | 9:43 AM | 9:47 AM | $-104.40 |
  | SHORT | 20 | $447.5700 | $452.7900 | 9:44 AM | 9:47 AM | $-104.40 |
  | SHORT | 20 | $450.0000 | $452.7900 | 9:46 AM | 9:47 AM | $-55.80 |
  | LONG | 20 | $452.7900 | $450.9100 | 9:47 AM | 9:47 AM | $-37.60 |
  | SHORT | 20 | $449.2200 | $435.4700 | 9:51 AM | 10:23 AM | $+275.00 |
  | SHORT | 20 | $449.6500 | $434.2400 | 10:00 AM | 10:29 AM | $+308.20 |

### LITE — `MULTI_LEG_MIXED`

- Bought: **124sh** for **$123,014.82** (avg $992.0550)
- Sold: **124sh** for **$122,991.88** (avg $991.8700)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-22.94** (after fees: $-29.49)
- Fees: **$6.55**
- Fragmentation: 5 fills across 2 venues — IBKRATS, NASDAQ
- Time window: 9:31 AM → 2:00 PM
- **Sold before buying — short-direction round-trip**

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 55 | $990.0000 | $991.8700 | 9:31 AM | 9:31 AM | $+102.85 |
  | LONG | 7 | $990.0000 | $991.8700 | 9:31 AM | 9:31 AM | $+13.09 |
  | SHORT | 62 | $991.8700 | $994.1100 | 1:30 PM | 2:00 PM | $-138.88 |

### BKNG — `MULTI_LEG_LONG`

- Bought: **740sh** for **$124,978.86** (avg $168.8904)
- Sold: **740sh** for **$122,919.85** (avg $166.1079)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-2,059.01** (after fees: $-2,069.18)
- Fees: **$10.17**
- Fragmentation: 87 fills across 9 venues — ARCA, BATS, DRCTEDGE, IBKRATS, IEX, MEMX, NASDAQ, NYSE, PEARL
- Time window: 9:35 AM → 11:48 AM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 2 | $169.3800 | $166.1300 | 9:35 AM | 11:48 AM | $-6.50 |
  | LONG | 28 | $169.3800 | $166.1000 | 9:35 AM | 11:48 AM | $-91.84 |
  | LONG | 2 | $169.3200 | $166.1000 | 9:35 AM | 11:48 AM | $-6.44 |
  | LONG | 7 | $169.3200 | $166.1500 | 9:35 AM | 11:48 AM | $-22.19 |
  | LONG | 3 | $169.3200 | $166.1500 | 9:35 AM | 11:48 AM | $-9.51 |
  | LONG | 10 | $169.3200 | $166.1500 | 9:35 AM | 11:48 AM | $-31.70 |
  | LONG | 7 | $169.3200 | $166.1000 | 9:35 AM | 11:48 AM | $-22.54 |
  | LONG | 4 | $169.2200 | $166.1000 | 9:35 AM | 11:48 AM | $-12.48 |
  | LONG | 3 | $169.2200 | $166.1000 | 9:35 AM | 11:48 AM | $-9.36 |
  | LONG | 10 | $169.2200 | $166.1000 | 9:35 AM | 11:48 AM | $-31.20 |
  | LONG | 10 | $169.2200 | $166.1500 | 9:35 AM | 11:48 AM | $-30.70 |
  | LONG | 3 | $169.2200 | $166.1500 | 9:35 AM | 11:48 AM | $-9.21 |
  | LONG | 7 | $169.2200 | $166.1500 | 9:35 AM | 11:48 AM | $-21.49 |
  | LONG | 10 | $169.2200 | $166.1200 | 9:35 AM | 11:48 AM | $-31.00 |
  | LONG | 10 | $169.2200 | $166.1200 | 9:35 AM | 11:48 AM | $-31.00 |
  | LONG | 10 | $169.2200 | $166.1200 | 9:35 AM | 11:48 AM | $-31.00 |
  | LONG | 1 | $169.2200 | $166.1200 | 9:35 AM | 11:48 AM | $-3.10 |
  | LONG | 9 | $169.2100 | $166.1200 | 9:35 AM | 11:48 AM | $-27.81 |
  | LONG | 1 | $169.2100 | $166.1500 | 9:35 AM | 11:48 AM | $-3.06 |
  | LONG | 19 | $169.2100 | $166.1500 | 9:35 AM | 11:48 AM | $-58.14 |
  | LONG | 10 | $169.2100 | $166.1500 | 9:35 AM | 11:48 AM | $-30.60 |
  | LONG | 1 | $169.2100 | $166.1200 | 9:35 AM | 11:48 AM | $-3.09 |
  | LONG | 19 | $169.2200 | $166.1200 | 9:35 AM | 11:48 AM | $-58.90 |
  | LONG | 12 | $169.2200 | $166.1500 | 9:35 AM | 11:48 AM | $-36.84 |
  | LONG | 8 | $169.2100 | $166.1500 | 9:35 AM | 11:48 AM | $-24.48 |
  | LONG | 2 | $169.2100 | $166.1200 | 9:35 AM | 11:48 AM | $-6.18 |
  | LONG | 28 | $169.2200 | $166.1200 | 9:35 AM | 11:48 AM | $-86.80 |
  | LONG | 2 | $169.2200 | $166.1500 | 9:35 AM | 11:48 AM | $-6.14 |
  | LONG | 8 | $169.2200 | $166.1500 | 9:35 AM | 11:48 AM | $-24.56 |
  | LONG | 2 | $169.2200 | $166.1500 | 9:35 AM | 11:48 AM | $-6.14 |
  | LONG | 8 | $169.0200 | $166.1500 | 9:36 AM | 11:48 AM | $-22.96 |
  | LONG | 4 | $169.0200 | $166.1500 | 9:36 AM | 11:48 AM | $-11.48 |
  | LONG | 6 | $169.0200 | $166.1500 | 9:36 AM | 11:48 AM | $-17.22 |
  | LONG | 10 | $169.0200 | $166.1500 | 9:36 AM | 11:48 AM | $-28.70 |
  | LONG | 10 | $169.0200 | $166.1500 | 9:36 AM | 11:48 AM | $-28.70 |
  | LONG | 10 | $169.0200 | $166.1400 | 9:36 AM | 11:48 AM | $-28.80 |
  | LONG | 7 | $169.0200 | $166.1400 | 9:36 AM | 11:48 AM | $-20.16 |
  | LONG | 10 | $169.0200 | $166.1400 | 9:36 AM | 11:48 AM | $-28.80 |
  | LONG | 10 | $169.0200 | $166.1400 | 9:36 AM | 11:48 AM | $-28.80 |
  | LONG | 3 | $169.0300 | $166.1400 | 9:36 AM | 11:48 AM | $-8.67 |
  | LONG | 7 | $169.0300 | $166.1000 | 9:36 AM | 11:48 AM | $-20.51 |
  | LONG | 23 | $169.0300 | $166.1000 | 9:36 AM | 11:48 AM | $-67.39 |
  | LONG | 7 | $169.0300 | $166.1000 | 9:36 AM | 11:48 AM | $-20.51 |
  | LONG | 3 | $169.0300 | $166.1000 | 9:36 AM | 11:48 AM | $-8.79 |
  | LONG | 7 | $169.0300 | $166.1400 | 9:36 AM | 11:48 AM | $-20.23 |
  | LONG | 5 | $169.0300 | $166.1400 | 9:36 AM | 11:48 AM | $-14.45 |
  | LONG | 5 | $169.0300 | $166.1400 | 9:36 AM | 11:48 AM | $-14.45 |
  | LONG | 7 | $169.0300 | $166.1400 | 9:36 AM | 11:48 AM | $-20.23 |
  | LONG | 10 | $169.0300 | $166.1400 | 9:36 AM | 11:48 AM | $-28.90 |
  | LONG | 8 | $169.0300 | $166.0900 | 9:36 AM | 11:48 AM | $-23.52 |
  | LONG | 15 | $169.0300 | $166.0900 | 9:36 AM | 11:48 AM | $-44.10 |
  | LONG | 12 | $168.9000 | $166.0900 | 9:36 AM | 11:48 AM | $-33.72 |
  | LONG | 8 | $168.9000 | $166.1300 | 9:36 AM | 11:48 AM | $-22.16 |
  | LONG | 7 | $168.9000 | $166.1300 | 9:36 AM | 11:48 AM | $-19.39 |
  | LONG | 3 | $168.9000 | $166.0900 | 9:36 AM | 11:48 AM | $-8.43 |
  | LONG | 11 | $169.0300 | $166.0900 | 9:36 AM | 11:48 AM | $-32.34 |
  | LONG | 10 | $168.8900 | $166.0900 | 9:36 AM | 11:48 AM | $-28.00 |
  | LONG | 1 | $168.8900 | $166.0900 | 9:36 AM | 11:48 AM | $-2.80 |
  | LONG | 15 | $168.8900 | $166.0600 | 9:36 AM | 11:48 AM | $-42.45 |
  | LONG | 4 | $168.8900 | $166.1000 | 9:36 AM | 11:48 AM | $-11.16 |
  | LONG | 6 | $168.4300 | $166.1000 | 9:37 AM | 11:48 AM | $-13.98 |
  | LONG | 10 | $168.4300 | $166.0900 | 9:37 AM | 11:48 AM | $-23.40 |
  | LONG | 1 | $168.4300 | $166.1000 | 9:37 AM | 11:48 AM | $-2.33 |
  | LONG | 9 | $168.4300 | $166.1000 | 9:37 AM | 11:48 AM | $-20.97 |
  | LONG | 1 | $168.4300 | $166.0900 | 9:37 AM | 11:48 AM | $-2.34 |
  | LONG | 14 | $168.4300 | $166.0900 | 9:37 AM | 11:48 AM | $-32.76 |
  | LONG | 3 | $168.4300 | $166.0900 | 9:37 AM | 11:48 AM | $-7.02 |
  | LONG | 7 | $168.4300 | $166.0900 | 9:37 AM | 11:48 AM | $-16.38 |
  | LONG | 14 | $168.4300 | $166.1300 | 9:37 AM | 11:48 AM | $-32.20 |
  | LONG | 25 | $168.4300 | $166.0600 | 9:37 AM | 11:48 AM | $-59.25 |
  | LONG | 40 | $168.4300 | $166.0600 | 9:37 AM | 11:48 AM | $-94.80 |
  | LONG | 19 | $168.4300 | $166.0600 | 9:37 AM | 11:48 AM | $-45.03 |
  | LONG | 10 | $168.3900 | $166.0600 | 9:37 AM | 11:48 AM | $-23.30 |
  | LONG | 10 | $168.4300 | $166.0600 | 9:37 AM | 11:48 AM | $-23.70 |
  | LONG | 10 | $168.4300 | $166.0600 | 9:37 AM | 11:48 AM | $-23.70 |
  | LONG | 10 | $168.4300 | $166.0600 | 9:37 AM | 11:48 AM | $-23.70 |
  | LONG | 1 | $168.4300 | $166.0600 | 9:37 AM | 11:48 AM | $-2.37 |
  | LONG | 9 | $168.4300 | $166.1000 | 9:37 AM | 11:48 AM | $-20.97 |
  | LONG | 1 | $168.4300 | $166.1000 | 9:37 AM | 11:48 AM | $-2.33 |
  | LONG | 9 | $168.4300 | $166.1200 | 9:37 AM | 11:48 AM | $-20.79 |
  | LONG | 1 | $168.4000 | $166.1200 | 9:37 AM | 11:48 AM | $-2.28 |
  | LONG | 9 | $168.4000 | $166.0600 | 9:37 AM | 11:48 AM | $-21.06 |
  | LONG | 2 | $168.4000 | $166.0600 | 9:37 AM | 11:48 AM | $-4.68 |
  | LONG | 10 | $168.4000 | $166.1100 | 9:37 AM | 11:48 AM | $-22.90 |
  | LONG | 5 | $168.4000 | $166.0900 | 9:37 AM | 11:48 AM | $-11.55 |
  | LONG | 10 | $168.4300 | $166.0900 | 9:37 AM | 11:48 AM | $-23.40 |

### SBUX — `MULTI_LEG_LONG`

- Bought: **1,245sh** for **$131,531.08** (avg $105.6475)
- Sold: **1,245sh** for **$130,457.36** (avg $104.7850)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-1,073.72** (after fees: $-1,092.37)
- Fees: **$18.65**
- Fragmentation: 28 fills across 7 venues — BATS, BEX, EDGEA, IBKRATS, IEX, MEMX, NASDAQ
- Time window: 9:37 AM → 3:51 PM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 82 | $105.6900 | $104.8600 | 9:37 AM | 12:51 PM | $-68.06 |
  | LONG | 14 | $105.6900 | $104.8600 | 9:37 AM | 12:51 PM | $-11.62 |
  | LONG | 79 | $105.6900 | $104.7500 | 9:37 AM | 12:55 PM | $-74.26 |
  | LONG | 21 | $105.6900 | $104.7500 | 9:37 AM | 12:55 PM | $-19.74 |
  | LONG | 23 | $105.6900 | $104.7500 | 9:37 AM | 12:55 PM | $-21.62 |
  | LONG | 56 | $105.6900 | $104.7500 | 9:37 AM | 12:55 PM | $-52.64 |
  | LONG | 26 | $105.6900 | $104.7500 | 9:37 AM | 12:55 PM | $-24.44 |
  | LONG | 18 | $105.6900 | $104.7500 | 9:37 AM | 12:55 PM | $-16.92 |
  | LONG | 25 | $105.6900 | $104.7500 | 9:37 AM | 12:55 PM | $-23.50 |
  | LONG | 50 | $105.6900 | $104.7500 | 9:37 AM | 12:55 PM | $-47.00 |
  | LONG | 27 | $105.2900 | $104.7500 | 9:42 AM | 12:55 PM | $-14.58 |
  | LONG | 6 | $105.2900 | $104.7500 | 9:42 AM | 12:55 PM | $-3.24 |
  | LONG | 20 | $105.2900 | $104.7500 | 9:42 AM | 12:55 PM | $-10.80 |
  | LONG | 74 | $105.3800 | $104.7500 | 9:42 AM | 12:55 PM | $-46.62 |
  | LONG | 26 | $105.3800 | $104.7600 | 9:42 AM | 12:55 PM | $-16.12 |
  | LONG | 99 | $105.3800 | $104.7600 | 9:42 AM | 12:55 PM | $-61.38 |
  | LONG | 31 | $105.3800 | $104.7800 | 9:42 AM | 12:55 PM | $-18.60 |
  | LONG | 69 | $105.3800 | $104.7800 | 9:42 AM | 12:55 PM | $-41.40 |
  | LONG | 42 | $105.3800 | $104.7800 | 9:42 AM | 12:55 PM | $-25.20 |
  | LONG | 4 | $106.0300 | $104.7800 | 10:33 AM | 12:55 PM | $-5.00 |
  | LONG | 92 | $106.0300 | $104.7800 | 10:33 AM | 12:55 PM | $-115.00 |
  | LONG | 91 | $105.9800 | $104.8400 | 10:34 AM | 3:51 PM | $-103.74 |
  | LONG | 9 | $105.9800 | $104.8400 | 10:34 AM | 3:51 PM | $-10.26 |
  | LONG | 82 | $105.9800 | $104.8100 | 10:34 AM | 3:51 PM | $-95.94 |
  | LONG | 91 | $105.9700 | $104.8100 | 10:35 AM | 3:51 PM | $-105.56 |
  | LONG | 88 | $105.2700 | $104.8100 | 2:12 PM | 3:51 PM | $-40.48 |

### MO — `MULTI_LEG_LONG`

- Bought: **1,701sh** for **$125,471.35** (avg $73.7633)
- Sold: **1,701sh** for **$124,292.07** (avg $73.0700)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-1,179.28** (after fees: $-1,199.21)
- Fees: **$19.93**
- Fragmentation: 22 fills across 7 venues — ARCA, BATS, DRCTEDGE, IBKRATS, IEX, NASDAQ, NYSE
- Time window: 9:35 AM → 12:55 PM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 100 | $73.7500 | $73.0700 | 9:35 AM | 12:55 PM | $-68.00 |
  | LONG | 121 | $73.7500 | $73.0700 | 9:35 AM | 12:55 PM | $-82.28 |
  | LONG | 50 | $73.7500 | $73.0700 | 9:35 AM | 12:55 PM | $-34.00 |
  | LONG | 300 | $73.7500 | $73.0700 | 9:35 AM | 12:55 PM | $-204.00 |
  | LONG | 100 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-70.00 |
  | LONG | 5 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-3.50 |
  | LONG | 7 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-4.90 |
  | LONG | 100 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-70.00 |
  | LONG | 100 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-70.00 |
  | LONG | 35 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-24.50 |
  | LONG | 100 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-70.00 |
  | LONG | 100 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-70.00 |
  | LONG | 20 | $73.7700 | $73.0700 | 9:41 AM | 12:55 PM | $-14.00 |
  | LONG | 80 | $73.7700 | $73.0700 | 9:45 AM | 12:55 PM | $-56.00 |
  | LONG | 95 | $73.7700 | $73.0700 | 9:45 AM | 12:55 PM | $-66.50 |
  | LONG | 125 | $73.7700 | $73.0700 | 9:45 AM | 12:55 PM | $-87.50 |
  | LONG | 51 | $73.7700 | $73.0700 | 9:45 AM | 12:55 PM | $-35.70 |
  | LONG | 12 | $73.7700 | $73.0700 | 9:45 AM | 12:55 PM | $-8.40 |
  | LONG | 88 | $73.7700 | $73.0700 | 9:45 AM | 12:55 PM | $-61.60 |
  | LONG | 12 | $73.7700 | $73.0700 | 9:45 AM | 12:55 PM | $-8.40 |
  | LONG | 100 | $73.7700 | $73.0700 | 9:45 AM | 12:55 PM | $-70.00 |

### NCLH — `MULTI_LEG_LONG`

- Bought: **2,422sh** for **$41,876.38** (avg $17.2900)
- Sold: **2,422sh** for **$41,803.72** (avg $17.2600)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-72.66** (after fees: $-98.25)
- Fees: **$25.59**
- Fragmentation: 19 fills across 7 venues — ARCA, BATS, DRCTEDGE, IEX, NASDAQ, NYSE, NYSENAT
- Time window: 9:43 AM → 3:55 PM
- **Touched EOD-flatten window** (≥3:55 PM)

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |
  | LONG | 119 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.57 |
  | LONG | 44 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-1.32 |
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |
  | LONG | 300 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-9.00 |
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |
  | LONG | 139 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-4.17 |
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |
  | LONG | 27 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-0.81 |
  | LONG | 374 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-11.22 |
  | LONG | 300 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-9.00 |
  | LONG | 219 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-6.57 |
  | LONG | 100 | $17.2900 | $17.2600 | 9:43 AM | 3:55 PM | $-3.00 |

### BP — `MULTI_LEG_LONG`

- Bought: **1,200sh** for **$56,224.98** (avg $46.8541)
- Sold: **1,200sh** for **$56,304.00** (avg $46.9200)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$+79.02** (after fees: $+65.60)
- Fees: **$13.42**
- Fragmentation: 12 fills across 5 venues — ARCA, DRCTEDGE, IEX, NASDAQ, NYSE
- Time window: 1:00 PM → 3:51 PM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 17 | $46.8900 | $46.9200 | 1:00 PM | 3:51 PM | $+0.51 |
  | LONG | 38 | $46.8900 | $46.9200 | 1:00 PM | 3:51 PM | $+1.14 |
  | LONG | 187 | $46.8900 | $46.9200 | 1:00 PM | 3:51 PM | $+5.61 |
  | LONG | 100 | $46.8900 | $46.9200 | 1:00 PM | 3:51 PM | $+3.00 |
  | LONG | 125 | $46.8900 | $46.9200 | 1:00 PM | 3:51 PM | $+3.75 |
  | LONG | 33 | $46.8900 | $46.9200 | 1:00 PM | 3:51 PM | $+0.99 |
  | LONG | 222 | $46.8900 | $46.9200 | 1:00 PM | 3:51 PM | $+6.66 |
  | LONG | 78 | $46.8000 | $46.9200 | 2:00 PM | 3:51 PM | $+9.36 |
  | LONG | 264 | $46.8000 | $46.9200 | 2:00 PM | 3:51 PM | $+31.68 |
  | LONG | 36 | $46.8000 | $46.9200 | 2:00 PM | 3:51 PM | $+4.32 |
  | LONG | 100 | $46.8000 | $46.9200 | 2:00 PM | 3:51 PM | $+12.00 |

### APH — `MULTI_LEG_LONG`

- Bought: **588sh** for **$84,113.40** (avg $143.0500)
- Sold: **588sh** for **$82,560.32** (avg $140.4087)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-1,553.08** (after fees: $-1,560.79)
- Fees: **$7.71**
- Fragmentation: 10 fills across 3 venues — IBKRATS, NASDAQ, NYSE
- Time window: 9:32 AM → 11:21 AM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 77 | $143.0500 | $140.3900 | 9:32 AM | 11:21 AM | $-204.82 |
  | LONG | 11 | $143.0500 | $140.3900 | 9:32 AM | 11:21 AM | $-29.26 |
  | LONG | 89 | $143.0500 | $140.4000 | 9:32 AM | 11:21 AM | $-235.85 |
  | LONG | 11 | $143.0500 | $140.4000 | 9:32 AM | 11:21 AM | $-29.15 |
  | LONG | 100 | $143.0500 | $140.3900 | 9:32 AM | 11:21 AM | $-266.00 |
  | LONG | 100 | $143.0500 | $140.3900 | 9:32 AM | 11:21 AM | $-266.00 |
  | LONG | 100 | $143.0500 | $140.4400 | 9:32 AM | 11:21 AM | $-261.00 |
  | LONG | 100 | $143.0500 | $140.4400 | 9:32 AM | 11:21 AM | $-261.00 |

### LHX — `MULTI_LEG_SHORT`

- Bought: **309sh** for **$96,349.29** (avg $311.8100)
- Sold: **309sh** for **$96,114.18** (avg $311.0491)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-235.11** (after fees: $-241.84)
- Fees: **$6.73**
- Fragmentation: 10 fills across 3 venues — IBKRATS, NASDAQ, NYSE
- Time window: 9:34 AM → 11:18 AM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | SHORT | 50 | $310.9600 | $311.8100 | 9:34 AM | 9:34 AM | $-42.50 |
  | SHORT | 50 | $310.9600 | $311.8100 | 9:34 AM | 9:34 AM | $-42.50 |
  | SHORT | 14 | $310.8200 | $311.8100 | 9:34 AM | 9:34 AM | $-13.86 |
  | SHORT | 1 | $310.8200 | $311.8100 | 9:34 AM | 9:34 AM | $-0.99 |
  | SHORT | 34 | $310.8200 | $311.8100 | 9:34 AM | 9:34 AM | $-33.66 |
  | SHORT | 80 | $310.9600 | $311.8100 | 9:34 AM | 9:34 AM | $-68.00 |
  | SHORT | 40 | $310.9600 | $311.8100 | 9:34 AM | 9:34 AM | $-34.00 |
  | SHORT | 40 | $311.8200 | $311.8100 | 11:18 AM | 11:18 AM | $+0.40 |

### NXPI — `MULTI_LEG_LONG`

- Bought: **333sh** for **$98,034.78** (avg $294.3987)
- Sold: **333sh** for **$96,695.55** (avg $290.3770)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-1,339.23** (after fees: $-1,345.29)
- Fees: **$6.06**
- Fragmentation: 8 fills across 4 venues — BATS, IBKRATS, IEX, NASDAQ
- Time window: 9:34 AM → 3:55 PM
- **Touched EOD-flatten window** (≥3:55 PM)

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 41 | $296.7800 | $291.1900 | 9:34 AM | 11:21 AM | $-229.19 |
  | LONG | 59 | $296.7800 | $291.1900 | 9:34 AM | 11:21 AM | $-329.81 |
  | LONG | 41 | $296.7800 | $291.1900 | 9:34 AM | 11:21 AM | $-229.19 |
  | LONG | 92 | $292.6500 | $289.7800 | 1:29 PM | 3:55 PM | $-264.04 |
  | LONG | 100 | $292.6500 | $289.7800 | 1:29 PM | 3:55 PM | $-287.00 |

### TER — `MULTI_LEG_LONG`

- Bought: **197sh** for **$67,370.06** (avg $341.9800)
- Sold: **197sh** for **$66,578.12** (avg $337.9600)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-791.94** (after fees: $-795.36)
- Fees: **$3.42**
- Fragmentation: 7 fills across 4 venues — BYX, DRCTEDGE, IBKRATS, NASDAQ
- Time window: 1:29 PM → 3:55 PM
- **Touched EOD-flatten window** (≥3:55 PM)

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 40 | $341.9800 | $337.9600 | 1:29 PM | 3:55 PM | $-160.80 |
  | LONG | 32 | $341.9800 | $337.9600 | 1:29 PM | 3:55 PM | $-128.64 |
  | LONG | 27 | $341.9800 | $337.9600 | 1:29 PM | 3:55 PM | $-108.54 |
  | LONG | 1 | $341.9800 | $337.9600 | 1:29 PM | 3:55 PM | $-4.02 |
  | LONG | 57 | $341.9800 | $337.9600 | 1:29 PM | 3:55 PM | $-229.14 |
  | LONG | 40 | $341.9800 | $337.9600 | 1:29 PM | 3:55 PM | $-160.80 |

### GM — `MULTI_LEG_SHORT`

- Bought: **397sh** for **$30,056.87** (avg $75.7100)
- Sold: **397sh** for **$29,949.68** (avg $75.4400)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-107.19** (after fees: $-111.87)
- Fees: **$4.68**
- Fragmentation: 7 fills across 5 venues — ARCA, DRCTEDGE, IEX, NASDAQ, NYSE
- Time window: 12:56 PM → 3:51 PM
- **Sold before buying — short-direction round-trip**

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | SHORT | 100 | $75.4400 | $75.7100 | 12:56 PM | 3:51 PM | $-27.00 |
  | SHORT | 93 | $75.4400 | $75.7100 | 12:56 PM | 3:51 PM | $-25.11 |
  | SHORT | 7 | $75.4400 | $75.7100 | 12:56 PM | 3:51 PM | $-1.89 |
  | SHORT | 97 | $75.4400 | $75.7100 | 12:56 PM | 3:51 PM | $-26.19 |
  | SHORT | 3 | $75.4400 | $75.7100 | 12:56 PM | 3:51 PM | $-0.81 |
  | SHORT | 97 | $75.4400 | $75.7100 | 12:56 PM | 3:51 PM | $-26.19 |

### PYPL — `MULTI_LEG_LONG`

- Bought: **816sh** for **$41,476.28** (avg $50.8288)
- Sold: **816sh** for **$41,110.08** (avg $50.3800)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-366.20** (after fees: $-375.37)
- Fees: **$9.17**
- Fragmentation: 7 fills across 4 venues — ARCA, BATS, IEX, NASDAQ
- Time window: 9:46 AM → 3:51 PM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 100 | $50.8200 | $50.3800 | 9:46 AM | 3:51 PM | $-44.00 |
  | LONG | 33 | $50.8300 | $50.3800 | 9:46 AM | 3:51 PM | $-14.85 |
  | LONG | 134 | $50.8300 | $50.3800 | 9:46 AM | 3:51 PM | $-60.30 |
  | LONG | 33 | $50.8300 | $50.3800 | 9:46 AM | 3:51 PM | $-14.85 |
  | LONG | 514 | $50.8300 | $50.3800 | 9:46 AM | 3:51 PM | $-231.30 |
  | LONG | 2 | $50.8300 | $50.3800 | 9:46 AM | 3:51 PM | $-0.90 |

### STM — `MULTI_LEG_LONG`

- Bought: **747sh** for **$41,936.58** (avg $56.1400)
- Sold: **747sh** for **$41,241.87** (avg $55.2100)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-694.71** (after fees: $-703.18)
- Fees: **$8.47**
- Fragmentation: 7 fills across 3 venues — ARCA, BATS, NASDAQ
- Time window: 9:35 AM → 10:29 AM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 17 | $56.1400 | $55.2100 | 9:35 AM | 10:29 AM | $-15.81 |
  | LONG | 133 | $56.1400 | $55.2100 | 9:35 AM | 10:29 AM | $-123.69 |
  | LONG | 57 | $56.1400 | $55.2100 | 9:35 AM | 10:29 AM | $-53.01 |
  | LONG | 346 | $56.1400 | $55.2100 | 9:35 AM | 10:29 AM | $-321.78 |
  | LONG | 120 | $56.1400 | $55.2100 | 9:35 AM | 10:29 AM | $-111.60 |
  | LONG | 74 | $56.1400 | $55.2100 | 9:35 AM | 10:29 AM | $-68.82 |

### FDX — `MULTI_LEG_SHORT`

- Bought: **220sh** for **$80,956.70** (avg $367.9850)
- Sold: **220sh** for **$80,722.40** (avg $366.9200)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-234.30** (after fees: $-240.00)
- Fees: **$5.70**
- Fragmentation: 7 fills across 4 venues — BATS, IBKRATS, NASDAQ, NYSE
- Time window: 9:41 AM → 9:46 AM

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | SHORT | 30 | $367.9800 | $368.8900 | 9:41 AM | 9:41 AM | $-27.30 |
  | SHORT | 40 | $367.9800 | $368.8900 | 9:41 AM | 9:41 AM | $-36.40 |
  | SHORT | 40 | $367.9800 | $368.8900 | 9:41 AM | 9:41 AM | $-36.40 |
  | SHORT | 100 | $365.8600 | $367.0800 | 9:46 AM | 9:46 AM | $-122.00 |
  | SHORT | 10 | $365.8600 | $367.0800 | 9:46 AM | 9:46 AM | $-12.20 |

### VALE — `MULTI_LEG_LONG`

- Bought: **5,179sh** for **$83,459.76** (avg $16.1150)
- Sold: **5,179sh** for **$81,931.78** (avg $15.8200)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-1,527.98** (after fees: $-1,582.50)
- Fees: **$54.52**
- Fragmentation: 6 fills across 3 venues — BATS, BYX, NYSE
- Time window: 9:44 AM → 3:55 PM
- **Touched EOD-flatten window** (≥3:55 PM)

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 1,343 | $16.1400 | $15.8200 | 9:44 AM | 3:55 PM | $-429.76 |
  | LONG | 950 | $16.1400 | $15.8200 | 9:44 AM | 3:55 PM | $-304.00 |
  | LONG | 300 | $16.1400 | $15.8200 | 9:44 AM | 3:55 PM | $-96.00 |
  | LONG | 2,076 | $16.0900 | $15.8200 | 9:49 AM | 3:55 PM | $-560.52 |
  | LONG | 510 | $16.0900 | $15.8200 | 9:49 AM | 3:55 PM | $-137.70 |

### SOXS — `MULTI_LEG_LONG`

- Bought: **5,166sh** for **$69,224.40** (avg $13.4000)
- Sold: **5,166sh** for **$68,552.82** (avg $13.2700)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-671.58** (after fees: $-725.69)
- Fees: **$54.11**
- Fragmentation: 5 fills across 4 venues — ARCA, BYX, IEX, NASDAQ
- Time window: 12:52 PM → 3:55 PM
- **Touched EOD-flatten window** (≥3:55 PM)

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 66 | $13.4000 | $13.2700 | 12:52 PM | 3:55 PM | $-8.58 |
  | LONG | 1,534 | $13.4000 | $13.2700 | 12:52 PM | 3:55 PM | $-199.42 |
  | LONG | 1,366 | $13.4000 | $13.2700 | 12:52 PM | 3:55 PM | $-177.58 |
  | LONG | 2,200 | $13.4000 | $13.2700 | 12:52 PM | 3:55 PM | $-286.00 |

### ELV — `MULTI_LEG_LONG`

- Bought: **113sh** for **$42,029.22** (avg $371.9400)
- Sold: **113sh** for **$42,056.34** (avg $372.1800)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$+27.12** (after fees: $+24.23)
- Fees: **$2.89**
- Fragmentation: 5 fills across 2 venues — NASDAQ, NYSE
- Time window: 9:34 AM → 3:55 PM
- **Touched EOD-flatten window** (≥3:55 PM)

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | LONG | 33 | $371.9400 | $372.1800 | 9:34 AM | 3:55 PM | $+7.92 |
  | LONG | 7 | $371.9400 | $372.1800 | 9:34 AM | 3:55 PM | $+1.68 |
  | LONG | 40 | $371.9400 | $372.1800 | 9:35 AM | 3:55 PM | $+9.60 |
  | LONG | 33 | $371.9400 | $372.1800 | 9:36 AM | 3:55 PM | $+7.92 |

### CRCL — `MULTI_LEG_SHORT`

- Bought: **190sh** for **$21,840.50** (avg $114.9500)
- Sold: **190sh** for **$20,968.40** (avg $110.3600)
- Net position end-of-tape: **+0sh** (open residual: +0sh)
- Realized PnL: **$-872.10** (after fees: $-874.57)
- Fees: **$2.47**
- Fragmentation: 4 fills across 3 venues — ARCA, NASDAQ, NYSE
- Time window: 9:38 AM → 10:44 AM
- **Sold before buying — short-direction round-trip**

  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |
  |---|---:|---:|---:|---|---|---:|
  | SHORT | 100 | $110.3600 | $114.9500 | 9:38 AM | 10:44 AM | $-459.00 |
  | SHORT | 9 | $110.3600 | $114.9500 | 9:38 AM | 10:44 AM | $-41.31 |
  | SHORT | 81 | $110.3600 | $114.9500 | 9:38 AM | 10:44 AM | $-371.79 |


---
_Report generated 2026-05-04T20:24:51_