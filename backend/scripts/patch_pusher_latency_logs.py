"""PowerShell text-replacement patch to add per-step timing logs to the
Windows pusher's bracket handler.

Apply this ONLY if Spark-side latency probe shows claim→ack p50 > 5s and
you want to see exactly where inside the pusher the time is going
(qualifyContracts? each placeOrder? the ib.sleep(2)? the ACK POST?).

Usage (on Windows, from the directory containing ib_data_pusher.py):

    powershell -ExecutionPolicy Bypass -File patch_pusher_latency_logs.ps1

It's additive — it inserts `print(...)` + `time.time()` captures around
each step in `handle_bracket`. Nothing existing is removed. After
testing, either revert via git on Windows or manually remove the
`# LATENCY_PROBE` lines.

Example expected output in the pusher terminal after applying:

    [LATENCY_PROBE] c54e61cd AAPL t0=0.000 start
    [LATENCY_PROBE] c54e61cd AAPL t=0.240s qualifyContracts done
    [LATENCY_PROBE] c54e61cd AAPL t=0.380s reqIds done (752, 753, 754)
    [LATENCY_PROBE] c54e61cd AAPL t=0.510s placeOrder(parent) done
    [LATENCY_PROBE] c54e61cd AAPL t=0.640s placeOrder(stop) done
    [LATENCY_PROBE] c54e61cd AAPL t=0.790s placeOrder(target) done  ← triggers transmit
    [LATENCY_PROBE] c54e61cd AAPL t=2.810s ib.sleep(2) done
    [LATENCY_PROBE] c54e61cd AAPL t=3.050s orderStatus=Submitted ACK POST sent
    [LATENCY_PROBE] c54e61cd AAPL t=3.150s DONE (total 3.15s)

Then grep your pusher log for `[LATENCY_PROBE]` and you'll see exactly
which step is the bottleneck.
"""

# ============================================================
# POWERSHELL SCRIPT BELOW — copy everything between the markers
# into a file named `patch_pusher_latency_logs.ps1` on Windows,
# in the same folder as `ib_data_pusher.py`.
# ============================================================

POWERSHELL_SCRIPT = r'''
# patch_pusher_latency_logs.ps1
# Adds [LATENCY_PROBE] timing logs to handle_bracket in ib_data_pusher.py.

$ErrorActionPreference = "Stop"
$file = ".\ib_data_pusher.py"

if (-not (Test-Path $file)) {
    Write-Host "ERROR: $file not found. Run this from the pusher directory." -ForegroundColor Red
    exit 1
}

$content = Get-Content $file -Raw

# Idempotency guard
if ($content -match "\[LATENCY_PROBE\]") {
    Write-Host "Pusher already has LATENCY_PROBE lines — nothing to do." -ForegroundColor Yellow
    exit 0
}

# Backup
$backup = "$file.bak_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item $file $backup
Write-Host "Backup saved: $backup" -ForegroundColor Green

# Insert timing at start of handle_bracket
$content = $content -replace `
    '(def handle_bracket\([^)]*\):\s*\n\s*)("""[^"]*""")?', `
    '$0
    import time as _lp_time  # LATENCY_PROBE
    _lp_t0 = _lp_time.time()  # LATENCY_PROBE
    _lp_oid = order_payload.get("order_id") or order_payload.get("trade_id") or "?"  # LATENCY_PROBE
    _lp_sym = order_payload.get("symbol", "?")  # LATENCY_PROBE
    print(f"[LATENCY_PROBE] {_lp_oid} {_lp_sym} t0=0.000 start", flush=True)  # LATENCY_PROBE
'

# After qualifyContracts
$content = $content -replace `
    '(ib\.qualifyContracts\(contract\))', `
    '$1
    print(f"[LATENCY_PROBE] {_lp_oid} {_lp_sym} t={_lp_time.time()-_lp_t0:.3f}s qualifyContracts done", flush=True)  # LATENCY_PROBE
'

# After each placeOrder — wrap with timing
$content = $content -replace `
    '(pt\s*=\s*ib\.placeOrder\(contract,\s*parent\))', `
    '$1
    print(f"[LATENCY_PROBE] {_lp_oid} {_lp_sym} t={_lp_time.time()-_lp_t0:.3f}s placeOrder(parent) done", flush=True)  # LATENCY_PROBE
'
$content = $content -replace `
    '(st\s*=\s*ib\.placeOrder\(contract,\s*stop\))', `
    '$1
    print(f"[LATENCY_PROBE] {_lp_oid} {_lp_sym} t={_lp_time.time()-_lp_t0:.3f}s placeOrder(stop) done", flush=True)  # LATENCY_PROBE
'
$content = $content -replace `
    '(tt\s*=\s*ib\.placeOrder\(contract,\s*target\))', `
    '$1
    print(f"[LATENCY_PROBE] {_lp_oid} {_lp_sym} t={_lp_time.time()-_lp_t0:.3f}s placeOrder(target) done (transmit=True)", flush=True)  # LATENCY_PROBE
'

# After ib.sleep
$content = $content -replace `
    '(ib\.sleep\(2\))', `
    '$1
    print(f"[LATENCY_PROBE] {_lp_oid} {_lp_sym} t={_lp_time.time()-_lp_t0:.3f}s ib.sleep(2) done", flush=True)  # LATENCY_PROBE
'

# Before return (final timing)
$content = $content -replace `
    '(return\s*\{\s*\n\s*"status":\s*"working")', `
    'print(f"[LATENCY_PROBE] {_lp_oid} {_lp_sym} t={_lp_time.time()-_lp_t0:.3f}s DONE", flush=True)  # LATENCY_PROBE
    $1
'

Set-Content -Path $file -Value $content -NoNewline
Write-Host "Patched $file with LATENCY_PROBE logs." -ForegroundColor Green
Write-Host "Restart the pusher. Then after a test bracket, run:" -ForegroundColor Cyan
Write-Host "  Select-String -Path pusher.log -Pattern 'LATENCY_PROBE'" -ForegroundColor Cyan
Write-Host "To revert: Copy-Item $backup $file" -ForegroundColor Yellow
'''


if __name__ == "__main__":
    # Print the PowerShell script so the user can pipe it into a file
    print(POWERSHELL_SCRIPT)
