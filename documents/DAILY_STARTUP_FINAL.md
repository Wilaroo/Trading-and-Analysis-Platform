# TradeCommand — Daily Startup Guide

---

## EVERY MORNING: 4 Steps

---

### STEP 1: Start IB Gateway

1. Open **IB Gateway** app (icon on desktop or Start menu)
2. Login:
   - Username: Your IBKR username
   - Password: Your IBKR password
   - Select: **Paper Trading**
3. Wait for **green Connected** status

✅ **Leave IB Gateway open**

---

### STEP 2: Check Ollama

1. Press `Win + R`
2. Type `powershell` and press Enter

**This is PowerShell #1 (Ollama Check)**

Type:
```
ollama serve
```

| You See | Meaning |
|---------|---------|
| `Listening on 127.0.0.1:11434` | ✅ Now running |
| `bind: Only one usage...` | ✅ Already running |

If already running, you can close this window. Otherwise, **leave it open**.

---

### STEP 3: Start Backend

1. Press `Win + R`
2. Type `powershell` and press Enter

**This is PowerShell #2 (BACKEND)**

Type these 3 commands:

```
cd C:\Users\13174\Trading-and-Analysis-Platform\backend
```

```
.\venv\Scripts\Activate
```

```
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

✅ **Wait for:** `Application startup complete.`

⚠️ **Leave this window open!**

---

### STEP 4: Start Frontend

1. Press `Win + R`
2. Type `powershell` and press Enter

**This is PowerShell #3 (FRONTEND)**

Type these 2 commands:

```
cd C:\Users\13174\Trading-and-Analysis-Platform\frontend
```

```
npm start
```

✅ **Wait for:** `Compiled successfully!`

✅ **Browser opens automatically** to `http://localhost:3000`

⚠️ **Leave this window open!**

---

### STEP 5: Connect to IB

1. In the browser, look at **top right**
2. Click **Connect** button
3. Wait for **green Connected** status

---

## ✅ DONE! Your Setup:

```
┌─────────────────────────────────────────────────────────────┐
│                        YOUR SCREEN                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   [IB Gateway App]          [Browser: localhost:3000]       │
│   Status: Connected         TradeCommand App                │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   [PowerShell #2 - BACKEND]    [PowerShell #3 - FRONTEND]   │
│   Shows: server logs           Shows: Compiled successfully │
│   Port: 8001                   Port: 3000                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## PULLING CODE UPDATES

When I make changes, pull them:

Open **any new PowerShell** and type:

```
cd C:\Users\13174\Trading-and-Analysis-Platform
git pull origin main
```

Then **refresh your browser** (F5).

---

## END OF DAY: Shutdown

### 1. Close Frontend
- Click on **PowerShell #3 (FRONTEND)**
- Press `Ctrl + C`
- Type `exit` and press Enter

### 2. Close Backend
- Click on **PowerShell #2 (BACKEND)**
- Press `Ctrl + C`
- Type `exit` and press Enter

### 3. Close IB Gateway
- Click the **X** on IB Gateway app

### 4. Close Browser
- Close the browser tab

---

## QUICK REFERENCE CARD

| Window | Name | Command |
|--------|------|---------|
| App | IB Gateway | Login → Paper Trading |
| PS #1 | Ollama (optional check) | `ollama serve` |
| PS #2 | **BACKEND** | `cd ...\backend` → `.\venv\Scripts\Activate` → `uvicorn server:app --host 0.0.0.0 --port 8001 --reload` |
| PS #3 | **FRONTEND** | `cd ...\frontend` → `npm start` |
| Browser | TradeCommand | `http://localhost:3000` → Click Connect |

---

## TROUBLESHOOTING

| Problem | Solution |
|---------|----------|
| IB Gateway won't connect | Restart IB Gateway, check internet |
| Backend error | Check PowerShell #2 for red error messages |
| Frontend won't compile | Run `npm install` then `npm start` again |
| AI not responding | Check Ollama is running: `ollama serve` |
| Need latest code | `git pull origin main` then refresh browser |
| Port already in use | Close old PowerShell windows, try again |
