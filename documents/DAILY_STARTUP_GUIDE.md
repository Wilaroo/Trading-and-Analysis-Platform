# TradeCommand Daily Startup Guide

## Quick Summary
Every trading day, you need to start **2 things** on your local machine:
1. **Ollama** (your local AI)
2. **ngrok tunnel** (connects your AI to the cloud)

Then open the trading platform in your browser.

---

## Method 1: Manual Startup (Step-by-Step)

### Step 1: Start Ollama
Ollama usually starts automatically when Windows boots. To verify:
- Look for the Ollama icon in your system tray (bottom-right near the clock)
- If not running, search "Ollama" in Start menu and launch it

**To verify Ollama is running:**
```powershell
curl http://localhost:11434/api/tags
```
You should see a list of your models (deepseek-r1, llama3, etc.)

### Step 2: Start ngrok Tunnel
Open **PowerShell** or **Command Prompt** and run:
```powershell
ngrok http 11434
```

You'll see output like:
```
Session Status                online
Account                       YourName (Plan: Hobby)
Forwarding                    https://pseudoaccidentally-linty-addie.ngrok-free.dev -> http://localhost:11434
```

**Important:** Keep this window open while trading! Closing it disconnects the AI.

### Step 3: Open Trading Platform
Open your browser and go to:
```
https://market-alerts-31.preview.emergentagent.com
```

### Step 4: Verify Connection
1. Click **Settings** in the left sidebar
2. Click the **Test** button
3. You should see a green "Connected!" message with your available models

---

## Method 2: One-Click Automated Startup (Recommended)

### Create the Startup Script

1. **Create a new file** on your Desktop called `StartTrading.bat`

2. **Right-click the file** → Edit (or Open with Notepad)

3. **Paste this script:**

```batch
@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo ============================================
echo.

:: Check if Ollama is running
echo [1/4] Checking Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama is running!
) else (
    echo       Starting Ollama...
    start "" "C:\Users\%USERNAME%\AppData\Local\Programs\Ollama\ollama app.exe"
    timeout /t 5 /nobreak >nul
)

echo.
echo [2/4] Starting ngrok tunnel...
echo       Your tunnel URL: https://pseudoaccidentally-linty-addie.ngrok-free.dev
echo.

:: Start ngrok in a new window
start "ngrok Tunnel" cmd /k "ngrok http 11434"

:: Wait for ngrok to initialize
timeout /t 3 /nobreak >nul

echo [3/4] Opening Trading Platform...
timeout /t 2 /nobreak >nul

:: Open browser to trading platform
start "" "https://market-alerts-31.preview.emergentagent.com"

echo.
echo [4/4] Startup Complete!
echo.
echo ============================================
echo    IMPORTANT: Keep the ngrok window open!
echo    Close it when you're done trading.
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
```

4. **Save and close** Notepad

5. **Double-click** `StartTrading.bat` to run it!

### Create a Desktop Shortcut with Custom Icon

1. **Right-click** on `StartTrading.bat`
2. Select **Create shortcut**
3. **Right-click** the shortcut → **Properties**
4. Click **Change Icon...**
5. Browse to an icon file or select from Windows icons
6. Rename the shortcut to "TradeCommand" or "Start Trading"

---

## Method 3: Windows Task Scheduler (Auto-Start on Login)

If you want everything to start automatically when you log into Windows:

1. Press `Win + R`, type `taskschd.msc`, press Enter
2. Click **Create Basic Task...**
3. Name: "TradeCommand Startup"
4. Trigger: "When I log on"
5. Action: "Start a program"
6. Browse to your `StartTrading.bat` file
7. Finish

---

## Troubleshooting

### "Ollama not responding"
```powershell
# Restart Ollama
taskkill /f /im ollama.exe
start "" "C:\Users\%USERNAME%\AppData\Local\Programs\Ollama\ollama app.exe"
```

### "ngrok tunnel not connecting"
```powershell
# Kill existing ngrok and restart
taskkill /f /im ngrok.exe
ngrok http 11434
```

### "Settings page shows Disconnected"
1. Make sure ngrok window is still open
2. Click the **Test** button on Settings page
3. If still failing, restart ngrok

### "AI not responding in chat"
1. Check Settings page - verify "Connected" status
2. Try a simple message like "hi"
3. Check that Ollama is running locally

---

## Daily Checklist

- [ ] Ollama running (system tray icon visible)
- [ ] ngrok tunnel active (PowerShell window open)
- [ ] Trading platform open in browser
- [ ] Settings page shows "Connected" (green badge)
- [ ] Test AI with a simple message

---

## Shutdown Procedure

When you're done trading:
1. Close the ngrok PowerShell window (this disconnects the tunnel)
2. Ollama can keep running (it uses minimal resources)
3. Close browser tabs

---

## Your Connection Details

| Component | URL/Location |
|-----------|-------------|
| Trading Platform | https://market-alerts-31.preview.emergentagent.com |
| ngrok Tunnel | https://pseudoaccidentally-linty-addie.ngrok-free.dev |
| Local Ollama | http://localhost:11434 |
| Default AI Model | deepseek-r1:8b |

---

*Last updated: February 23, 2026*
