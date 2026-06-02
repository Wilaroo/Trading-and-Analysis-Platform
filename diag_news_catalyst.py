#!/usr/bin/env python3
"""
diag_news_catalyst.py  (READ-ONLY)

Pinpoints WHY the TQS Fundamental pillar's catalyst component is floored
(has_recent_news never fires). Tests the LIVE in-backend get_ticker_news path
(IB historical + Finnhub) via the API, plus the news_articles / earnings_calendar
collections + the Finnhub key presence. Writes nothing.
"""
import os
import json
import urllib.request


def _load_env():
    url = os.environ.get("MONGO_URL"); name = os.environ.get("DB_NAME")
    fh = os.environ.get("FINNHUB_API_KEY")
    for c in ("/app/backend/.env", "./backend/.env", "backend/.env", ".env"):
        if not os.path.exists(c):
            continue
        for line in open(c):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1); k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "MONGO_URL" and not url:
                url = v
            elif k == "DB_NAME" and not name:
                name = v
            elif k == "FINNHUB_API_KEY" and not fh:
                fh = v
    return url or "mongodb://localhost:27017", name or "tradecommand", fh


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def main():
    mongo_url, name, fh = _load_env()
    print("=" * 72)
    print("FINNHUB_API_KEY present:", bool(fh), ("(len %d)" % len(fh)) if fh else "")

    # 1. LIVE in-backend news path (full get_ticker_news incl. IB historical)
    print("\n--- LIVE  GET /api/ib/news/<sym>  (in-backend get_ticker_news) ---")
    for sym in ("AAPL", "NVDA", "TSLA", "AMD", "SPY"):
        try:
            st, data = _get(f"http://localhost:8001/api/ib/news/{sym}")
            items = data if isinstance(data, list) else data.get("news", data.get("articles", []))
            if not isinstance(items, list):
                items = []
            real = [it for it in items if not it.get("is_placeholder")]
            srcs = sorted({it.get("source_type", "?") for it in items})
            head = (real[0].get("headline", "")[:60] if real else
                    (items[0].get("headline", "")[:60] if items else ""))
            print(f"  {sym:5s} http={st} items={len(items):2d} real={len(real):2d} "
                  f"src={srcs}  e.g. {head!r}")
        except Exception as e:
            print(f"  {sym:5s} ERROR: {e}")

    # 2. Direct Finnhub company-news probe (does the key/feed work standalone?)
    if fh:
        print("\n--- Direct Finnhub company-news (last 7d) ---")
        import datetime as _dt
        today = _dt.date.today(); wk = today - _dt.timedelta(days=7)
        for sym in ("AAPL", "NVDA"):
            try:
                u = (f"https://finnhub.io/api/v1/company-news?symbol={sym}"
                     f"&from={wk.isoformat()}&to={today.isoformat()}&token={fh}")
                st, data = _get(u)
                n = len(data) if isinstance(data, list) else 0
                print(f"  {sym:5s} http={st} finnhub_items={n}")
            except Exception as e:
                print(f"  {sym:5s} Finnhub ERROR: {e}")

    # 3. Collections
    print("\n--- Collections ---")
    try:
        from pymongo import MongoClient
        db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[name]
        for coll in ("news_articles", "earnings_calendar"):
            c = db[coll]
            total = c.count_documents({})
            newest = None
            for f in ("timestamp", "datetime", "created_at", "date", "fetched_at"):
                d = c.find_one({f: {"$exists": True}}, sort=[(f, -1)])
                if d:
                    newest = (f, d.get(f)); break
            print(f"  {coll:18s} docs={total:6d}  newest={newest}")
    except Exception as e:
        print("  mongo error:", e)

    print("\nDone. Read-only.")


if __name__ == "__main__":
    main()
