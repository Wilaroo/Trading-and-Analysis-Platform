# TradeCommand — Full Development Setup with IB Gateway

This guide lets you:
- ✅ Develop with Emergent AI (code changes pushed to GitHub)
- ✅ Connect to IB Gateway (live data, VIX, scanners)
- ✅ Use free Ollama AI (no credits used for standard queries)

---

## BEFORE YOU START

Make sure you have these installed:
- IB Gateway (official IBKR app)
- Ollama (https://ollama.ai)
- Node.js
- Python with venv

---

## DAILY STARTUP (5 PowerShell Windows)

---

### WINDOW 1: Start IB Gateway

1. Open **IB Gateway** application (NOT TWS, NOT TC2000)
2. Login:
   - Username: Your IBKR username
   - Password: Your IBKR password
   - Trading Mode: **Paper Trading**
3. Wait for it to show **Connected** (green status)
4. Verify API settings:
   - Go to: `Configure` → `Settings` → `API` → `Settings`
   - ✅ Enable ActiveX and Socket Clients: **Checked**
   - ✅ Socket port: **4002**
   - ✅ Allow connections from localhost only: **Checked**

**Leave IB Gateway running!**

---

### WINDOW 2: Start Ollama

1. Press `Win + R`
2. Type `powershell` and press Enter
3. Type this command and press Enter:

```powershell
ollama serve
```

**What you'll see:**
```
Listening on 127.0.0.1:11434
```

If you see "bind: Only one usage..." — Ollama is already running. That's OK!

**Leave this window open!**

---

### WINDOW 3: Start MongoDB

1. Press `Win + R`
2. Type `powershell` and press Enter
3. Type this command and press Enter:

```powershell
mongod
```

**What you'll see:**
```
waiting for connections on port 27017
```

If MongoDB is already running as a service, skip this step.

**Leave this window open!**

---

### WINDOW 4: Start Backend

1. Press `Win + R`
2. Type `powershell` and press Enter
3. Type these commands one by one:

```powershell
cd C:\Users\13174\Trading-and-Analysis-Platform\backend
```

```powershell
.\venv\Scripts\Activate
```

Your prompt should now show `(venv)` at the start.

```powershell
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

**What you'll see:**
```
INFO:     Uvicorn running on http://0.0.0.0:8001
INFO:     Application startup complete.
```

**Leave this window open!**

---

### WINDOW 5: Start Frontend

1. Press `Win + R`
2. Type `powershell` and press Enter
3. Type these commands one by one:

```powershell
cd C:\Users\13174\Trading-and-Analysis-Platform\frontend
```

```powershell
npm start
```

**What you'll see:**
```
Compiled successfully!

You can now view the app in the browser.

  Local:            http://localhost:3000
```

A browser window should open automatically.

**Leave this window open!**

---

### STEP 6: Connect to IB Gateway in the App

1. Browser should be open to `http://localhost:3000`
2. Look at the top right of the app
3. Click the **Connect** button
4. Wait for it to show **Connected** (green)

---

## ✅ YOU'RE DONE!

You should now have:

| Window | What's Running | Status |
|--------|----------------|--------|
| IB Gateway App | IB Gateway | Connected (green) |
| PowerShell 1 | Ollama | Listening on 11434 |
| PowerShell 2 | MongoDB | Waiting for connections |
| PowerShell 3 | Backend | Running on :8001 |
| PowerShell 4 | Frontend | Running on :3000 |
| Browser | TradeCommand | Connected to IB |

---

## HOW DEVELOPMENT WORKS

1. **You tell me** what feature/fix you want
2. **I write the code** in the cloud
3. **I save to GitHub** (automatic)
4. **You pull the changes:**

```powershell
cd C:\Users\13174\Trading-and-Analysis-Platform
git pull origin main
```

5. **Backend/Frontend auto-reload** (no restart needed usually)
6. **Refresh browser** to see changes

---

## END OF DAY: Shutdown

### 1. Close Frontend (PowerShell 5)
- Press `Ctrl + C`
- Type `exit`

### 2. Close Backend (PowerShell 4)
- Press `Ctrl + C`
- Type `exit`

### 3. Close MongoDB (PowerShell 3)
- Press `Ctrl + C`
- Type `exit`

### 4. Close Ollama (PowerShell 2)
- Press `Ctrl + C`
- Type `exit`

### 5. Close IB Gateway
- Click `X` to close the app

### 6. Close Browser
- Close the tab

---

## TROUBLESHOOTING

### "Cannot connect to IB Gateway"
- Make sure IB Gateway is running and shows green status
- Check API settings: port should be 4002
- Check "Enable ActiveX and Socket Clients" is checked

### "Ollama is not responding"
- Check PowerShell window 2 is still open
- Try running `ollama serve` again

### "Backend won't start"
- Make sure you activated venv: `.\venv\Scripts\Activate`
- Check for error messages in the PowerShell window

### "MongoDB connection failed"
- Make sure MongoDB is running (PowerShell window 3)
- Or check if it's running as a Windows service

### "npm start fails"
- Run `npm install` first, then try again

---

## QUICK REFERENCE: All Commands

**Window 2 - Ollama:**
```powershell
ollama serve
```

**Window 3 - MongoDB:**
```powershell
mongod
```

**Window 4 - Backend:**
```powershell
cd C:\Users\13174\Trading-and-Analysis-Platform\backend
.\venv\Scripts\Activate
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

**Window 5 - Frontend:**
```powershell
cd C:\Users\13174\Trading-and-Analysis-Platform\frontend
npm start
```

**Pull latest code:**
```powershell
cd C:\Users\13174\Trading-and-Analysis-Platform
git pull origin main
```
