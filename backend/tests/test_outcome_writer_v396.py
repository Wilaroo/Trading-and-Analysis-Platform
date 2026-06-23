"""v19.34.396 — alert_outcomes writer hardening + backfill regression.

A) Direct writer persists an alert_outcomes row (grade + r_multiple + excursion
   floor fields) — proves the shared-handle path works.
B) learning_reconciler.reconcile() backfills missing closes AND floors mfe_r/mae_r
   on bot_trades where the manage loop left them 0, WITHOUT clobbering a real
   tracked peak (mfe_r=1.5 stays 1.5).

Throwaway DB; run: PYTHONPATH=/app/backend MONGO_URL=... python tests/test_outcome_writer_v396.py
"""
import os
import pymongo
from datetime import datetime, timezone

from services import pnl_compute
from services import learning_reconciler

NOW = datetime.now(timezone.utc).isoformat()
DBNAME = "outcome_v396_DELETEME_db"


class _FakeTrade:
    def __init__(self, **kw):
        self.id = kw["id"]
        self.alert_id = kw.get("alert_id")
        self.symbol = kw["symbol"]
        self.setup_type = kw["setup_type"]
        self.direction = kw.get("direction", "long")
        self.fill_price = kw["fill_price"]
        self.stop_price = kw["stop_price"]
        self.stop_loss = kw["stop_price"]
        self.tp_price = kw.get("tp_price")
        self.target = kw.get("tp_price")
        self.target_prices = [kw["tp_price"]] if kw.get("tp_price") else []
        self.shares = kw["shares"]
        self.trade_grade = kw.get("trade_grade")
        self.smb_grade = kw.get("smb_grade", "")
        self.entered_by = "bot"
        self.closed_at = NOW
        self.executed_at = NOW
        self.created_at = NOW
        self.mfe_r = kw.get("mfe_r", 0.0)
        self.mae_r = kw.get("mae_r", 0.0)
        self.scale_out_config = {}


def main():
    client = pymongo.MongoClient(os.environ["MONGO_URL"])
    db = client[DBNAME]
    client.drop_database(DBNAME)

    # Point the writer at the throwaway DB (mirrors in-server behaviour).
    pnl_compute._AO_DB = db
    pnl_compute._AO_CLIENT = None

    # ---- A: direct writer ----
    t = _FakeTrade(id="t-A", symbol="AAA", setup_type="stage_2_breakout",
                   fill_price=100.0, stop_price=95.0, tp_price=110.0,
                   shares=10, trade_grade="B")
    pnl_compute._record_alert_outcome_bestEffort(
        t, "stop_loss",
        {"realized_pnl": -20.0, "net_pnl": -21.0, "shares": 10},
        98.0, "test")
    row = db["alert_outcomes"].find_one({"trade_id": "t-A"})
    assert row is not None, "writer did not persist a row"
    assert row["outcome"] == "lost", row
    assert row["trade_grade"] == "B", row
    assert isinstance(row.get("r_multiple"), (int, float)), row
    assert abs(row["r_multiple"] - (-0.4)) < 1e-6, ("r_multiple wrong", row["r_multiple"])
    assert "mae_r_floor" in row and "mfe_r_floor" in row, row
    print("A writer OK:", {k: row[k] for k in ("outcome", "trade_grade", "r_multiple", "mae_r_floor")})

    # ---- B: backfill floors mfe_r/mae_r without clobbering a real peak ----
    db["bot_trades"].insert_many([
        # closed, manage loop never populated excursion (mfe_r=0) -> should floor
        {"id": "bt-zero", "symbol": "ZRO", "setup_type": "daily_breakout",
         "direction": "long", "status": "closed", "fill_price": 50.0,
         "stop_price": 48.0, "target_prices": [56.0], "shares": 5,
         "realized_pnl": -10.0, "net_pnl": -10.0, "mfe_r": 0.0, "mae_r": 0.0,
         "close_reason": "stop_loss", "closed_at": NOW, "trade_grade": "C"},
        # closed, has a REAL tracked peak (mfe_r=1.5) -> must NOT be overwritten
        {"id": "bt-real", "symbol": "REA", "setup_type": "daily_breakout",
         "direction": "long", "status": "closed", "fill_price": 50.0,
         "stop_price": 48.0, "target_prices": [56.0], "shares": 5,
         "realized_pnl": 12.0, "net_pnl": 12.0, "mfe_r": 1.5, "mae_r": -0.3,
         "close_reason": "eod_auto_close", "closed_at": NOW, "trade_grade": "A"},
    ])

    rep = learning_reconciler.reconcile(db, days=None, commit=True, verbose=False)
    print("B reconcile report:", {k: rep[k] for k in ("closed_scanned", "ao_written")})
    assert db["alert_outcomes"].count_documents({"trade_id": "bt-zero"}) == 1, "zero-trade ao missing"
    assert db["alert_outcomes"].count_documents({"trade_id": "bt-real"}) == 1, "real-trade ao missing"

    zero = db["bot_trades"].find_one({"id": "bt-zero"})
    real = db["bot_trades"].find_one({"id": "bt-real"})
    # zero-mfe loser got an mae_r floor applied (now <= realized adverse, non-zero)
    assert zero["mae_r"] != 0.0, ("expected mae_r floor on zero trade", zero["mae_r"])
    # real peak preserved (NOT clobbered by the thinner exit-floor)
    assert abs(real["mfe_r"] - 1.5) < 1e-9, ("real mfe_r was clobbered", real["mfe_r"])
    print("B floor OK: zero.mae_r=", zero["mae_r"], "real.mfe_r=", real["mfe_r"])

    client.drop_database(DBNAME)
    pnl_compute._AO_DB = None
    print("CLEANED UP — OUTCOME WRITER v396 PASS")


if __name__ == "__main__":
    main()
