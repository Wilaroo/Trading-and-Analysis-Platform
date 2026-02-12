# TradeCommand — Daily Startup Checklist

## ☀️ Morning Startup (2 minutes)

### Step 1: Start Ollama
```powershell
ollama serve
```
✓ Wait for: `Listening on 127.0.0.1:11434`

---

### Step 2: Start ngrok
```powershell
& "C:\Users\13174\Desktop\Trading Data\ngrok-v3-stable-windows-amd64\ngrok.exe" http 11434 --host-header="localhost:11434" --url=pseudoaccidentally-linty-addie.ngrok-free.dev
```
✓ Wait for: `Session Status: online`

---

### Step 3: Open App
```
https://ai-chart-connect.preview.emergentagent.com
```

---

## ✅ You're Ready to Trade!

- AI Chat: Working (free via Ollama)
- Market Data: Working (Alpaca + Finnhub)
- Trading Bot: Ready to start

---

## 🌙 End of Day Shutdown

1. Close browser tab
2. Press `Ctrl+C` in ngrok window
3. Press `Ctrl+C` in Ollama window (or leave running)

---

## 🔧 Quick Fixes

| Problem | Fix |
|---------|-----|
| AI not responding | Restart ngrok |
| Slow AI (15-60s) | Normal, let it process |
| Need latest code | `cd C:\Users\13174\Trading-and-Analysis-Platform` then `git pull origin main` |

---

## 📋 Copy-Paste Commands

**All-in-one startup (run in separate windows):**

Window 1:
```
ollama serve
```

Window 2:
```
& "C:\Users\13174\Desktop\Trading Data\ngrok-v3-stable-windows-amd64\ngrok.exe" http 11434 --host-header="localhost:11434" --url=pseudoaccidentally-linty-addie.ngrok-free.dev
```

Window 3 (browser):
```
https://ai-chart-connect.preview.emergentagent.com
```
