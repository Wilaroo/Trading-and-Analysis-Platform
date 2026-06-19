# SentCom / TradeCommand — Full System Deck (2026-06)

Every prominent piece of the app + infrastructure, as a **full page** and its
**modals / sub-panels**. Aesthetic locked: dark "Control Room" glassmorphism
(deep blue-slate #11161d, frosted floating panels, rim-light edges, cyan
#06b6d4 / emerald #10b981 / amber #f59e0b / rose #f43f5e, monospace data,
NO purple). Commit via "Save to Github".

## Infrastructure → UI map (data flows left→right)
```
Windows IB Gateway ─► IB Data Pusher (client 15) + Turbo Collectors (16-19)
   └─► POST /api/ib/push-data ─► in-mem _pushed_ib_data + Mongo snapshot
   └─► order_queue (Mongo) ◄─ pusher polls /pending, reports /result
MongoDB ─► scheduler_catchup (boot staleness-guard) ─► nightly crons
   (gate_calibration, warm-fundamentals 18:30 ET, learning_stats, eod_gen)
ib_historical_data ─► triple_barrier_labeler ─► purged_cpcv ─► frozen_holdout
   ─► shadow_tracker ─► gate_calibrator ─► model_scorecard (promote/rollback)
LIVE: regime classifiers ─► in_play_service ─► 38 detectors ─► TQS engine
   ─► confidence gate ─► position_manager brackets ─► EOD-flatten / kill-switch
```

## FULL PAGES
| # | File | Piece | Maps to |
|---|---|---|---|
| 01 | `DECK_01_command.png` | Command (home cockpit) | live overview, all seams at a glance |
| 02 | `DECK_02_data_connections.png` | Data & Connections | L0 Truth: IB/Pusher/Mongo/Scheduler/Data Schedule/TQS Coverage |
| 03 | `DECK_03_decision.png` | Decision (Why-Trace + Verdict) | S2/S3 + L5: provenance ring, unified authority |
| 04 | `DECK_04_scanner.png` | Scanner / In-Play | L2 universe funnel + L3 setups |
| 05 | `DECK_05_positions.png` | Positions / management | L6/L7 brackets, proximity strip, exit plan |
| 06 | `DECK_06_autonomy.png` | Strategy Autonomy | S6: family × regime-fit × edge-decay × ON/OFF |
| 07 | `DECK_07_brain.png` | Brain (NIA) ML lifecycle | L4 + Learning: CPCV/holdout/shadow/promote |
| 08 | `DECK_08_journal.png` | Trade Journal | log/weekly/playbooks/report-card/gameplan |
| 09 | `DECK_09_diagnostics.png` | Diagnostics / forensics | trail/funnel/rejections/shadow |
| 10 | `DECK_10_risk_safety.png` | Risk & Safety | Governance: kill-switch, caps, EOD-flatten |

## MODALS / SUB-PANELS
| # | File | Opens from | Shows |
|---|---|---|---|
| 01 | `MODAL_01_whytrace.png` | scanner row / decision | vertical 7-stage Why-Trace + ring + verdict |
| 02 | `MODAL_02_position.png` | position card | proximity strip, bracket history, exit plan, retune |
| 03 | `MODAL_03_connection.png` | data tile | IB pusher health, circuit-breaker, topology, reconnect |
| 04 | `MODAL_04_training.png` | Brain model row | CPCV folds, frozen holdout, promote/rollback |
| 05 | `MODAL_05_strategy.png` | autonomy row | edge-decay history, regime-fit matrix, enable/disable |
| 06 | `MODAL_06_nia_drawer.png` | ⌘K anywhere | conversational NIA, slash-commands, deep-links |
| 07 | `MODAL_07_flatten.png` | CLOSE/CANCEL ALL | type-to-confirm safety, affected positions, account mode |
| 08 | `MODAL_08_tqs_drawer.png` | any TQS chip | 5-pillar drill, weights_used, descriptors |
| 09 | `MODAL_09_shadow.png` | diagnostics cell | decision-trail steps, would-have outcome, divergence |

> AI-rendered concept art (labels illustrative). Locks layout/structure +
> interaction model; final pixels from the shadcn/lucide/framer-motion build.
