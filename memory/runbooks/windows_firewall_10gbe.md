# Windows Firewall — 10GbE Network Classification

**Date solved:** 2026-05-01  
**Symptom:** Spark → Windows on :8765 silently times out (firewall rule exists but isn't honored)  
**Root cause:** 10GbE adapter to Spark classified as "Public" network on Windows; Public profile overrides explicit allow rules

## Permanent fix (run once, persists across reboots)

PowerShell as Administrator:

```powershell
# 1. Confirm the IB Pusher firewall rule exists
netsh advfirewall firewall show rule name="IB Pusher RPC 8765"
# Should show: Profiles: Domain,Private,Public · Action: Allow · LocalPort: 8765

# If missing, add it:
netsh advfirewall firewall add rule name="IB Pusher RPC 8765" `
    dir=in action=allow protocol=TCP localport=8765 profile=any

# 2. Find the 10GbE adapter to Spark (look for IPv4Connectivity: LocalNetwork
# AND IPv4 address starting with 192.168.50.*)
Get-NetConnectionProfile

# 3. Reclassify it as Private (replace "Ethernet 3" with the actual InterfaceAlias)
Set-NetConnectionProfile -InterfaceAlias "Ethernet 3" -NetworkCategory Private

# 4. Verify
Get-NetConnectionProfile -InterfaceAlias "Ethernet 3"
# Should now show: NetworkCategory : Private
```

## Verify from Spark

```bash
ping -c 3 -W 2 192.168.50.1                          # 0% packet loss
curl -m 3 http://192.168.50.1:8765/rpc/health        # 200 OK with pusher health JSON
curl -s localhost:8001/api/system/banner | jq .level # null (no banner)
```

## Why "Public" silently overrides allow rules on Windows

Windows applies layered policies on Public networks even with explicit `netsh advfirewall firewall add rule`:
- Network Discovery: blocked
- File and Printer Sharing: blocked
- Inbound on most ports: blocked, even with rule overrides
- The "block all incoming connections" master toggle (Settings → Firewall) overrides per-rule allows

By contrast, Private networks honor your explicit firewall rules normally. This is the correct semantic anyway — the direct 10GbE point-to-point cable to Spark IS a private trusted network.

## Diagnostic chain (if it ever recurs)

1. Test ping: `ping -c 3 -W 2 192.168.50.1` from Spark
2. If ping fails: most likely Public profile; reclassify as Private
3. If ping works but TCP times out: rule exists but doesn't apply; check `Get-NetConnectionProfile`
4. Definitive test: `netsh advfirewall set allprofiles state off` for 30s, retry from Spark, then re-enable

## Related files

- `backend/services/system_health_service.py::_check_pusher_rpc()` — emits `rpc_blocked` token when push fresh + RPC fails (this exact scenario)
- `backend/routers/system_banner.py` — banner with inline `netsh` action command
- `frontend/src/components/sentcom/v5/SystemBanner.jsx` — visible alert strip
