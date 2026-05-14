#!/usr/bin/env python3
"""v19.34.30 DB Cleanup -- dry-run default; --execute to write."""
import os, sys, json
from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

EXEC = "--execute" in sys.argv
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME   = os.environ.get("DB_NAME",   "tradecommand")
API       = os.environ.get("APP_URL",   "http://localhost:8001")
db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)[DB_NAME]
trades, archive = db["bot_trades"], db["bot_trades_archive_v19_34_30"]

print("="*84)
print(f"  v19.34.30 DB Cleanup -- {'EXECUTE' if EXEC else 'DRY-RUN'} -- {DB_NAME}")
print("="*84)

ib_positions = {}
try:
    import urllib.request
    with urllib.request.urlopen(f"{API}/api/system/ib-direct/positions", timeout=6) as r:
        for p in json.loads(r.read().decode()).get("positions", []):
            ib_positions[(p.get("symbol") or "").upper()] = float(p.get("position", 0))
    print(f"  IB positions fetched: {len(ib_positions)}")
except Exception as e:
    print(f"  [!] IB positions skip: {e}"); ib_positions = None

print("\n[1] Truncate stacked target_order_ids on open rows")
open_rows = list(trades.find({"status":"open"}))
to_t = []
for r in open_rows:
    nt = len(r.get("target_order_ids") or []); hs = bool(r.get("stop_order_id"))
    if nt > 0 or hs:
        to_t.append(r["_id"])
        print(f"    {r.get('symbol','?'):<6} id={str(r.get('id',''))[:8]} tgts={nt} stop={r.get('stop_order_id') or '-'}")
print(f"  -> {len(to_t)} rows would be reset")
if EXEC and to_t:
    res = trades.update_many({"_id":{"$in":to_t}},
        {"$set":{"target_order_ids":[],"stop_order_id":None,"oca_group":None,
                 "cleanup_v19_34_30_at":datetime.now(timezone.utc).isoformat()}})
    print(f"  WROTE matched={res.matched_count} modified={res.modified_count}")

print("\n[2] Archive phantom DUP_ID pairs (keep newest)")
dups = list(trades.aggregate([
    {"$match":{"status":"open"}},
    {"$group":{"_id":"$id","rows":{"$push":{"oid":"$_id","ca":"$created_at"}},"n":{"$sum":1}}},
    {"$match":{"n":{"$gt":1}}}]))
to_a = []
for g in dups:
    rows = sorted(g["rows"], key=lambda x: x.get("ca") or "")
    for r in rows[:-1]:
        to_a.append(r["oid"]); print(f"    DUP id={str(g['_id'])[:8]} archive _id={r['oid']}")
print(f"  -> {len(to_a)} phantom rows would be archived")
if EXEC and to_a:
    docs = list(trades.find({"_id":{"$in":to_a}}))
    for d in docs: d["archived_at"] = datetime.now(timezone.utc).isoformat()
    if docs: archive.insert_many(docs, ordered=False)
    res = trades.delete_many({"_id":{"$in":to_a}})
    print(f"  WROTE archived={len(docs)} deleted={res.deleted_count}")

print("\n[3] Zombie rows (open but IB has no position)")
zombies = []
if ib_positions is not None:
    for r in trades.find({"status":"open"}):
        sym = (r.get("symbol") or "").upper()
        rem = r.get("remaining_shares") if r.get("remaining_shares") is not None else (r.get("shares") or 0)
        if abs(ib_positions.get(sym, 0)) < 0.5 and rem > 0:
            zombies.append(r["_id"])
            print(f"    ZOMBIE {sym:<6} id={str(r.get('id',''))[:8]} rem={rem}")
print(f"  -> {len(zombies)} zombies would be marked")
if EXEC and zombies:
    res = trades.update_many({"_id":{"$in":zombies}},
        {"$set":{"status":"closed_zombie_v30","closed_at":datetime.now(timezone.utc).isoformat()}})
    print(f"  WROTE matched={res.matched_count} modified={res.modified_count}")

print("\n[4] Unique index on bot_trades.id")
existing = [ix["name"] for ix in trades.list_indexes()]
print(f"  Indexes: {existing}")
NAME = "id_unique_v19_34_30"
if NAME in existing: print("  Already present.")
elif EXEC:
    try: trades.create_index([("id",ASCENDING)], unique=True, name=NAME); print(f"  WROTE created {NAME}")
    except DuplicateKeyError as e: print(f"  [!] Duplicate after dedupe: {e}")
else: print("  (would create in --execute)")

print("\n" + "="*84)
print(f"  Done. mode={'EXECUTE' if EXEC else 'DRY-RUN'}")
