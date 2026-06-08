#!/usr/bin/env python3
"""
LIVE pusher-health watcher — run from ~3:40pm ET through ~4:05pm ET to capture
WHETHER and WHEN the IB pusher goes stale as the EOD close sequence fires.

Samples /api/system/health every 10s and prints the pusher_rpc subsystem
(push_age_s, push_fresh, status, consecutive_failures) + the EOD-relevant
subsystems, so we can correlate pusher death with the 15:45 RegT cutoff and the
15:55 EOD close. Writes a CSV alongside for later analysis.

Usage (on DGX, ~3:40pm ET):
  cd ~/Trading-and-Analysis-Platform/backend
  ../.venv/bin/python scripts/watch_pusher_eod.py
  # Ctrl-C to stop. CSV: /tmp/pusher_eod_watch.csv
"""
import csv
import time
import urllib.request
import json
from datetime import datetime, timezone

URL = "http://localhost:8001/api/system/health"
CSV = "/tmp/pusher_eod_watch.csv"


def _sample():
    with urllib.request.urlopen(URL, timeout=8) as r:
        return json.loads(r.read().decode())


def main():
    print(f"watching {URL} every 10s — Ctrl-C to stop. CSV → {CSV}\n")
    with open(CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["utc", "overall", "pusher_status", "push_age_s", "push_fresh",
                    "consec_fail", "ib_gateway", "live_bar_cache"])
        while True:
            try:
                h = _sample()
                subs = {s["name"]: s for s in h.get("subsystems", [])}
                p = subs.get("pusher_rpc", {})
                m = p.get("metrics", {})
                row = [
                    datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    h.get("overall"),
                    p.get("status"),
                    m.get("push_age_s"),
                    m.get("push_fresh"),
                    m.get("consecutive_failures"),
                    subs.get("ib_gateway", {}).get("status"),
                    subs.get("live_bar_cache", {}).get("detail"),
                ]
                w.writerow(row)
                fh.flush()
                flag = "" if p.get("status") == "green" else "  <<< PUSHER NOT GREEN"
                print(f"{row[0]}  overall={row[1]:<7} pusher={row[2]:<7} "
                      f"push_age={row[3]} fresh={row[4]} ib={row[6]}{flag}")
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  sample error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
