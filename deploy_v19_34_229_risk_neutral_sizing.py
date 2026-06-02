#!/usr/bin/env python3
"""
deploy_v19_34_229_risk_neutral_sizing.py

v19.34.229 — Dial TQS position-size multipliers back to RISK-NEUTRAL (~0.30x mean).

WHY: the v228 percentile-grade calibration spread grades A/B/C/D/F and lifted the
mean position-size multiplier to 0.371x (a ~24% size-up vs the historical flat
0.30x). Operator chose option (a): keep the conviction tilt (A still > D/F) but
normalize the magnitude back to ~0.30x mean by scaling every multiplier by 0.808.

WHAT (env-only, no code logic change):
    POSITION_SIZE_GRADE_A_MULT=0.80
    POSITION_SIZE_GRADE_B_MULT=0.48
    POSITION_SIZE_GRADE_C_MULT=0.24
    POSITION_SIZE_GRADE_D_MULT=0.12
    POSITION_SIZE_GRADE_F_MULT=0.08
  Live grade mix (A 9.3 / B 20.9 / C 35.4 / D 24.4 / F 10.0) -> mean ~= 0.297x.

These keys are read live via os.environ in opportunity_evaluator._resolve_grade_multiplier,
so a backend restart is required to pick them up (.env -> process env at startup).

IDEMPOTENT: re-running just re-asserts the same values. Safe to run multiple times.
Auto-commits so the `.bat` `git checkout -- .` restart cannot silently wipe the
change (CHANGELOG.md is a tracked file; .env is committed only if git already
tracks it, otherwise it is gitignored and survives the checkout anyway).

USAGE on the DGX:
    curl -s https://paste.rs/XXXX -o /tmp/deploy_v229.py
    python3 /tmp/deploy_v229.py            # auto-detects repo root from cwd
    # or, if run from outside the repo:
    python3 /tmp/deploy_v229.py /path/to/TradeCommand
    # then restart the backend so the new env is picked up.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone

TARGET_ENV = {
    "POSITION_SIZE_GRADE_A_MULT": "0.80",
    "POSITION_SIZE_GRADE_B_MULT": "0.48",
    "POSITION_SIZE_GRADE_C_MULT": "0.24",
    "POSITION_SIZE_GRADE_D_MULT": "0.12",
    "POSITION_SIZE_GRADE_F_MULT": "0.08",
}

CHANGELOG_ENTRY = (
    "\n## v19.34.229 — {date} — TQS sizing back to risk-neutral (~0.30x mean)\n"
    "Operator option (a): keep the v228 conviction tilt but normalize the\n"
    "magnitude (scale x0.808) so the mean position-size multiplier returns to\n"
    "the historical ~0.30x (was 0.371x). Env-only, no code change.\n"
    "  POSITION_SIZE_GRADE_A_MULT=0.80  B=0.48  C=0.24  D=0.12  F=0.08\n"
    "Restart required (.env -> process env at startup).\n"
)


def find_repo_root() -> str:
    """Locate the repo root by finding the dir that contains backend/server.py."""
    candidates = []
    if len(sys.argv) > 1:
        candidates.append(os.path.abspath(sys.argv[1]))
    candidates.append(os.getcwd())
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    seen = set()
    for start in candidates:
        cur = start
        for _ in range(8):  # walk up to 8 levels
            if cur in seen:
                break
            seen.add(cur)
            if os.path.isfile(os.path.join(cur, "backend", "server.py")):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    raise SystemExit(
        "ERROR: could not locate repo root (no backend/server.py found). "
        "Pass the repo path explicitly: python3 deploy_v229.py /path/to/repo"
    )


def upsert_env(env_path: str) -> bool:
    """Upsert TARGET_ENV keys into env_path, preserving all other lines/order.
    Returns True if the file content changed."""
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
        lines = []

    remaining = dict(TARGET_ENV)
    out = []
    changed = False
    for line in lines:
        stripped = line.strip()
        # leave comments / blanks untouched
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            new_line = f"{key}={remaining.pop(key)}"
            if new_line != line:
                changed = True
            out.append(new_line)
        else:
            out.append(line)

    # append any keys that weren't already present
    for key, val in remaining.items():
        out.append(f"{key}={val}")
        changed = True

    if changed:
        # preserve a single trailing newline
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    return changed


def append_changelog(repo: str) -> None:
    path = os.path.join(repo, "memory", "CHANGELOG.md")
    if not os.path.isfile(path):
        # fall back to repo-root CHANGELOG.md if memory/ layout differs
        alt = os.path.join(repo, "CHANGELOG.md")
        path = alt if os.path.isfile(alt) else path
    entry = CHANGELOG_ENTRY.format(date=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    # idempotent: don't duplicate the v229 header
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            if "v19.34.229" in f.read():
                print(f"  - CHANGELOG already has v19.34.229 entry ({path}); skipping append")
                return
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"  - appended v19.34.229 entry to {path}")


def git(repo: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
    )


def main():
    repo = find_repo_root()
    env_path = os.path.join(repo, "backend", ".env")
    print(f"== v19.34.229 risk-neutral sizing deploy ==")
    print(f"repo root : {repo}")
    print(f".env path : {env_path}")

    changed = upsert_env(env_path)
    print(f"  - .env {'updated' if changed else 'already up to date'}")

    # verify
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    print("  - verifying keys:")
    ok = True
    for k, v in TARGET_ENV.items():
        present = f"{k}={v}" in content
        ok = ok and present
        print(f"      {k}={v}  ->  {'OK' if present else 'MISSING'}")
    if not ok:
        raise SystemExit("ERROR: one or more keys missing after write. Aborting.")

    append_changelog(repo)

    # --- auto-commit so the .bat git-checkout can't wipe it ---
    git(repo, "add", "-A")
    status = git(repo, "status", "--porcelain")
    if status.stdout.strip():
        msg = "v19.34.229: TQS sizing back to risk-neutral (~0.30x mean); env-only"
        c = git(repo, "commit", "-m", msg)
        print("  - git commit:")
        print("    " + (c.stdout or c.stderr).strip().replace("\n", "\n    "))
        p = git(repo, "push")
        print("  - git push:")
        print("    " + (p.stdout or p.stderr).strip().replace("\n", "\n    "))
    else:
        print("  - git: nothing to commit (already committed / .env gitignored)")
        # if .env is gitignored the value still persists across `git checkout -- .`
        ign = git(repo, "check-ignore", env_path)
        if ign.returncode == 0:
            print("    note: backend/.env is gitignored — safe from `git checkout -- .`")

    print("\nDONE. Now RESTART the backend so the new env vars load:")
    print("  (use your normal StartTrading.bat / spark restart flow)")
    print("Expected new mean position-size multiplier ~= 0.30x (was 0.371x).")


if __name__ == "__main__":
    main()
