# TradeCommand — Daily Startup Guide

## Quick Reference

| Mode | Use Case | What Runs Locally |
|------|----------|-------------------|
| **Cloud Dev** | Building with Emergent AI | Ollama + ngrok only |
| **Full Local** | Production trading with IB | Everything on your PC |

---

## Mode 1: Cloud Development (Recommended for daily use)

Use this when developing with Emergent or just trading with Alpaca.

### Data Sources Available
- ✅ **Alpaca** — Real-time quotes, paper trading (cloud, always on)
- ✅ **Finnhub** — 100 live news headlines (cloud, always on)
- ✅ **Ollama** — Free AI via your local PC (needs ngrok)
- ❌ **IB Gateway** — Not available in cloud mode

### Startup Steps

**Step 1: Start Ollama (your free local AI)**
```powershell
# PowerShell Window 1
ollama serve
```
Wait for: `Listening on 127.0.0.1:11434`

**Step 2: Start ngrok tunnel**
```powershell
# PowerShell Window 2
& "C:\Users\13174\Desktop\Trading Data\ngrok-v3-stable-windows-amd64\ngrok.exe" http 11434 --host-header="localhost:11434" --url=pseudoaccidentally-linty-addie.ngrok-free.dev
```
Wait for: `Session Status: online`

**Step 3: Open TradeCommand**
```
https://market-intel-90.preview.emergentagent.com
```

**That's it!** The app auto-connects to Alpaca and Finnhub.

### Shutdown
1. Close browser tab
2. `Ctrl+C` in ngrok window
3. `Ctrl+C` in Ollama window (or leave running)

---

## Mode 2: Full Local (For IB Gateway + Live Trading)

Use this when you need IB Gateway features (VIX, IB scanners, live execution).

### Data Sources Available
- ✅ **Alpaca** — Real-time quotes, paper trading
- ✅ **Finnhub** — 100 live news headlines
- ✅ **Ollama** — Free AI (direct, no ngrok needed)
- ✅ **IB Gateway** — VIX, scanners, live trading

### Startup Steps

**Step 1: Start IB Gateway**
1. Open **IB Gateway** (official IBKR app)
2. Login to paper account `esw100000` (port 4002)
3. Verify: `File → Global Configuration → API → Settings`
   - ✅ Enable ActiveX and Socket Clients
   - ✅ Socket port: 4002
   - ✅ Allow connections from localhost

**Step 2: Start Ollama**
```powershell
# PowerShell Window 1
ollama serve
```

**Step 3: Start Backend**
```powershell
# PowerShell Window 2
cd C:\Users\13174\Trading-and-Analysis-Platform\backend
.\venv\Scripts\Activate
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

**Step 4: Start Frontend**
```powershell
# PowerShell Window 3
cd C:\Users\13174\Trading-and-Analysis-Platform\frontend
npm start
```

**Step 5: Open App & Connect**
1. Browser opens to `http://localhost:3000`
2. Click **Connect** button (top right) to connect to IB Gateway

### Shutdown
1. Close browser
2. `Ctrl+C` in frontend window
3. `Ctrl+C` in backend window
4. Close IB Gateway

---

## Syncing Code Between Cloud & Local

When we make changes in Emergent cloud, sync to your local PC:

```powershell
cd C:\Users\13174\Trading-and-Analysis-Platform
git pull
```

Then restart backend/frontend to see updates.

---

## AI Cost Optimization (Smart Routing)

Your app automatically routes AI requests to save credits:

| Query Type | AI Used | Cost | Examples |
|------------|---------|------|----------|
| **Light/Standard** | Ollama (local) | FREE | Chat, summaries, market intel reports |
| **Deep Analysis** | GPT-4o (Emergent) | Credits | "Should I buy NVDA?", strategy analysis |

**Deep triggers:** `should i buy`, `analyze`, `evaluate`, `strategy`, `recommend`, `compare`, `risk`

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| AI not responding | Check ngrok window is running, restart if needed |
| AI responses slow | Normal for Ollama (15-60s), let it process |
| "Reconnecting" in header | IB Gateway not running (OK in cloud mode) |
| Market data shows $0.00 | Market closed, or check Alpaca connection |
| Can't pull from GitHub | Run `git stash` first, then `git pull` |

---

## Service Summary

| Service | What It Provides | Required? |
|---------|-----------------|-----------|
| **Ollama + ngrok** | Free AI (chat, reports, analysis) | Yes — for AI features |
| **Alpaca** | Paper trading, real-time quotes | Auto-connected (keys saved) |
| **Finnhub** | Live market news | Auto-connected (key saved) |
| **IB Gateway** | VIX, IB scanners, live trading | Only for Full Local mode |

---

## Current URLs

- **Cloud App:** https://market-intel-90.preview.emergentagent.com
- **Local App:** http://localhost:3000
- **ngrok Tunnel:** https://pseudoaccidentally-linty-addie.ngrok-free.dev
