#!/usr/bin/env python3
"""
diag_stale_policy_audit.py — READ-ONLY. Quantifies how often the v402 stale
gates and the v403 OCA debounce actually fire, from the backend logs, so you
can confidently keep STALE_ALERT_POLICY=block and tune OCA_CLOSE_ZERO_STREAK.

It scans /tmp/backend.log (current session) plus the most recent rotated
logs/backend_*.log files and tallies:

  [v402 stale-policy]  missing/unparseable-timestamp detections, split by gate:
        evaluator (30s TTL)  — "...NO usable ALERT timestamp..."
        execution (timeframe)— "...NO usable timestamp..."
     With policy=block these were REJECTED; with observe they FIRED (logged only).
  [v402b OCA debounce] transient post-fill 0-share reads that DEFERRED a close
     (pre-v403 each of these would have orphaned a live position).
  context: evaluator stale-alert-ttl age drops + execution "Stale alert:" rejects.

NOTHING IS WRITTEN.

USAGE (repo root, DGX):
  .venv/bin/python backend/scripts/diag_stale_policy_audit.py
  .venv/bin/python backend/scripts/diag_stale_policy_audit.py --logs 6   # scan 6 rotated logs too
"""
import glob
import os
import re
import sys
from collections import Counter
from pathlib import Path


def _policy():
    for cand in ["backend/.env", ".env",
                 os.path.join(os.path.dirname(__file__), "..", ".env")]:
        p = Path(cand)
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("STALE_ALERT_POLICY") and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'").lower()
    return "block"  # patcher default


def _streak_env():
    for cand in ["backend/.env", ".env",
                 os.path.join(os.path.dirname(__file__), "..", ".env")]:
        p = Path(cand)
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("OCA_CLOSE_ZERO_STREAK") and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "2"  # patcher default


def _log_files(n_rotated):
    files = []
    for base in (".", os.path.join(os.path.dirname(__file__), "..", "..")):
        cur = os.path.join(base, "..", "tmp", "backend.log")  # unlikely
        if os.path.exists("/tmp/backend.log"):
            cur = "/tmp/backend.log"
        if os.path.exists(cur) and cur not in files:
            files.append(cur)
        rot = sorted(glob.glob(os.path.join(base, "logs", "backend_*.log")),
                     key=lambda p: os.path.getmtime(p), reverse=True)
        for r in rot[:n_rotated]:
            if r not in files:
                files.append(r)
        if files:
            break
    if os.path.exists("/tmp/backend.log") and "/tmp/backend.log" not in files:
        files.insert(0, "/tmp/backend.log")
    return files


def main():
    n_rotated = 0
    if "--logs" in sys.argv:
        try:
            n_rotated = int(sys.argv[sys.argv.index("--logs") + 1])
        except Exception:
            pass

    policy = _policy()
    streak = _streak_env()
    files = _log_files(n_rotated)

    cnt = Counter()
    sym_v402_eval, sym_v402_exec, sym_debounce = Counter(), Counter(), Counter()
    samples = {"v402_eval": [], "v402_exec": [], "debounce": [],
               "exec_reject": [], "eval_ttl": []}
    lines_scanned = 0

    re_v402 = re.compile(r"\[v402 stale-policy=(\w+)\]\s+(\S+)\s+(\S+)")
    re_deb = re.compile(r"\[v402b OCA debounce\]\s+(\S+)\s+zero-share read\s+(\d+)/(\d+)")
    re_exec_rej = re.compile(r"Stale alert:\s+(\S+)\s+(\S+)\s+(.*)")

    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    lines_scanned += 1
                    if "[v402 stale-policy=" in line:
                        m = re_v402.search(line)
                        sym = m.group(2) if m else "?"
                        if "NO usable alert timestamp" in line:
                            cnt["v402_eval"] += 1
                            sym_v402_eval[sym] += 1
                            if len(samples["v402_eval"]) < 5:
                                samples["v402_eval"].append(line.strip()[-140:])
                        else:
                            cnt["v402_exec"] += 1
                            sym_v402_exec[sym] += 1
                            if len(samples["v402_exec"]) < 5:
                                samples["v402_exec"].append(line.strip()[-140:])
                    elif "[v402b OCA debounce]" in line:
                        cnt["debounce"] += 1
                        m = re_deb.search(line)
                        if m:
                            sym_debounce[m.group(1)] += 1
                        if len(samples["debounce"]) < 5:
                            samples["debounce"].append(line.strip()[-140:])
                    elif "Stale alert:" in line:
                        cnt["exec_reject"] += 1
                        if "no usable timestamp" in line:
                            cnt["exec_reject_failclosed"] += 1
                        if len(samples["exec_reject"]) < 5:
                            samples["exec_reject"].append(line.strip()[-140:])
                    elif "stale-alert-ttl" in line and "Dropping" in line:
                        cnt["eval_ttl"] += 1
                        if len(samples["eval_ttl"]) < 5:
                            samples["eval_ttl"].append(line.strip()[-140:])
        except Exception as e:
            print(f"  (skip {f}: {e})")

    print("=" * 96)
    print("STALE-POLICY / OCA-DEBOUNCE AUDIT  (READ-ONLY)")
    print(f"  STALE_ALERT_POLICY = {policy}    OCA_CLOSE_ZERO_STREAK = {streak}")
    print(f"  logs scanned ({lines_scanned} lines):")
    for f in files:
        print(f"    - {f}")
    print("=" * 96)

    nots = cnt["v402_eval"] + cnt["v402_exec"]
    verb = "REJECTED" if policy == "block" else ("LOGGED-ONLY (still fired)" if policy == "observe" else "IGNORED (off)")
    print(f"\n[v402] missing/unparseable-timestamp alerts → {verb}")
    print(f"    evaluator 30s-TTL gate : {cnt['v402_eval']}")
    print(f"    execution timeframe gate: {cnt['v402_exec']}")
    print(f"    TOTAL no-timestamp hits : {nots}")
    if sym_v402_eval or sym_v402_exec:
        top = (sym_v402_eval + sym_v402_exec).most_common(10)
        print(f"    top symbols: {top}")

    print(f"\n[v403] OCA debounce — transient post-fill 0-share reads DEFERRED: {cnt['debounce']}")
    print("       (pre-v403 each of these would have orphaned a live position)")
    if sym_debounce:
        print(f"    top symbols: {sym_debounce.most_common(10)}")

    print(f"\ncontext (age-based staleness, unaffected by policy):")
    print(f"    evaluator stale-alert-ttl drops : {cnt['eval_ttl']}")
    print(f"    execution 'Stale alert:' rejects: {cnt['exec_reject']} "
          f"(of which fail-closed no-ts: {cnt['exec_reject_failclosed']})")

    for key, label in [("v402_eval", "v402 evaluator no-ts"),
                       ("v402_exec", "v402 execution no-ts"),
                       ("debounce", "v403 OCA debounce"),
                       ("exec_reject", "execution stale reject"),
                       ("eval_ttl", "evaluator ttl drop")]:
        if samples[key]:
            print(f"\n  recent [{label}]:")
            for s in samples[key]:
                print(f"    … {s}")

    print("\n" + "=" * 96)
    print("READ:")
    if nots == 0:
        print("  No missing-timestamp alerts seen — the fail-OPEN hole is dormant in this window.")
        print("  Safe to keep policy=block (it only triggers on the edge case).")
    else:
        print(f"  {nots} alert(s) had NO usable timestamp. With policy=block these were stopped")
        print("  from firing (pre-v402 they would have EXECUTED). If this count is high and you")
        print("  see legit setups among them, investigate WHY the timestamp is missing upstream.")
    if cnt["debounce"]:
        maxstreak = 0
        for s in samples["debounce"]:
            m = re_deb.search(s)
            if m:
                maxstreak = max(maxstreak, int(m.group(2)))
        print(f"  OCA debounce fired {cnt['debounce']}x. If deferrals routinely reach the streak")
        print(f"  cap, raise OCA_CLOSE_ZERO_STREAK; if it never fires, the gap was a one-off.")
    print("=" * 96)


if __name__ == "__main__":
    main()
