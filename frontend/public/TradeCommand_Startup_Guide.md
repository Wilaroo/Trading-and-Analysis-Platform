# TradeCommand — Daily Startup Guide

## Step 1: Start IB Gateway (required for live data & trading)

1. Open **IBKR Trader Workstation** or **IB Gateway** on your PC
2. Log in with your IBKR credentials
3. Make sure API is enabled:
   - In TWS: `File → Global Configuration → API → Settings`
   - Check "Enable ActiveX and Socket Clients"
   - Socket port should be **4002** (paper) or **4001** (live)
   - Check "Allow connections from localhost only"
4. Wait until it shows **"Connected"** with a green status

## Step 2: Start Ollama (your local AI — free)

1. Open **PowerShell**
2. Run:
```powershell
ollama serve
```
3. Wait for `Listening on 127.0.0.1:11434` (or it may already be running as a service — that's fine)

## Step 3: Start ngrok tunnel (connects your AI to the cloud app)

1. Open a **second PowerShell** window
2. Run:
```powershell
& "C:\Users\13174\Desktop\Trading Data\ngrok-v3-stable-windows-amd64\ngrok.exe" http 11434 --host-header="localhost:11434" --url=pseudoaccidentally-linty-addie.ngrok-free.dev
```
3. Wait for `Session Status: online` — you're good

## Step 4: Open TradeCommand

1. Go to: **https://trader-hq.preview.emergentagent.com**
2. Click **"Connect"** button (top right) to connect to IB Gateway
3. The app will auto-generate your morning briefing if one doesn't exist yet

---

## What Each Service Does

| Service | What it does | Required? |
|---------|-------------|-----------|
| **IB Gateway** | Live market data, positions, order execution, scanners | Yes — for live trading |
| **Ollama + ngrok** | AI chat, market intel reports, strategy analysis (FREE) | Yes — for AI features |
| **Alpaca** | Paper trading execution, account data | Auto-connected (keys saved) |
| **Finnhub** | Supplemental market news | Auto-connected (key saved) |

---

## Quick Troubleshooting

- **"Reconnecting" in header?** → IB Gateway isn't running or port 4002 isn't open
- **AI responses slow?** → Normal for local Ollama (15-60s). Let it process.
- **AI not responding?** → Check ngrok window is still running. Restart if needed.
- **Market data shows $0.00?** → Market is closed, or IB Gateway not connected

---

## Shutdown

1. Close the browser tab
2. Press `Ctrl+C` in the ngrok PowerShell window
3. Press `Ctrl+C` in the Ollama PowerShell window (or leave it running)
4. Close IB Gateway/TWS when done
