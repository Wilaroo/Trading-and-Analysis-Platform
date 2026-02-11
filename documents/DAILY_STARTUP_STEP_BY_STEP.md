# TradeCommand — Daily Startup (Step-by-Step)

---

## STEP 1: Open First PowerShell Window

1. Press `Win + R` on your keyboard
2. Type `powershell` and press Enter
3. A blue PowerShell window opens

---

## STEP 2: Start Ollama

In the PowerShell window, type this and press Enter:

```
ollama serve
```

**What you'll see:**
```
Couldn't find 'C:\Users\13174\.ollama\id_ed25519'. Generating new private key.
Your new public key is:
ssh-ed25519 AAAA...
time=2024-xx-xx level=INFO source=server.go msg="Listening on 127.0.0.1:11434"
```

✅ **Success!** When you see `Listening on 127.0.0.1:11434` — Ollama is running

⚠️ **Leave this window open!** Don't close it.

---

## STEP 3: Open Second PowerShell Window

1. Press `Win + R` again
2. Type `powershell` and press Enter
3. A NEW blue PowerShell window opens

---

## STEP 4: Start ngrok

In the NEW PowerShell window, copy and paste this ENTIRE command (all one line):

```
& "C:\Users\13174\Desktop\Trading Data\ngrok-v3-stable-windows-amd64\ngrok.exe" http 11434 --host-header="localhost:11434" --url=pseudoaccidentally-linty-addie.ngrok-free.dev
```

Press Enter.

**What you'll see:**
```
ngrok                                                           
                                                                
Session Status                online                            
Account                       your-account                      
Version                       3.x.x                             
Region                        United States (us)                
Web Interface                 http://127.0.0.1:4040             
Forwarding                    https://pseudoaccidentally-linty-addie.ngrok-free.dev -> http://localhost:11434
```

✅ **Success!** When you see `Session Status: online` — ngrok is running

⚠️ **Leave this window open too!** Don't close it.

---

## STEP 5: Open TradeCommand

1. Open your web browser (Chrome, Edge, etc.)
2. Go to this address:

```
https://tradehub-420.preview.emergentagent.com
```

✅ **Done!** TradeCommand is now running with AI enabled.

---

## SUMMARY: You Should Have

| Window | Status |
|--------|--------|
| PowerShell 1 | Ollama running (shows "Listening on 127.0.0.1:11434") |
| PowerShell 2 | ngrok running (shows "Session Status: online") |
| Browser | TradeCommand app open |

---

## END OF DAY: Shutdown

### Close ngrok (PowerShell 2):
1. Click on the ngrok PowerShell window
2. Press `Ctrl + C`
3. Type `exit` and press Enter

### Close Ollama (PowerShell 1):
1. Click on the Ollama PowerShell window
2. Press `Ctrl + C`
3. Type `exit` and press Enter

### Close Browser:
1. Close the browser tab

---

## TROUBLESHOOTING

### "ollama is not recognized"
Ollama isn't installed. Download from: https://ollama.ai

### ngrok shows "Session Status: offline"
1. Press `Ctrl + C` to stop it
2. Run the command again

### AI not responding in app
1. Check both PowerShell windows are still open
2. Check ngrok shows "Session Status: online"
3. If not, restart ngrok

### App shows "Reconnecting" 
This is OK! It means IB Gateway isn't connected (you don't need it for cloud mode)

---

## QUICK COPY-PASTE REFERENCE

**Ollama command:**
```
ollama serve
```

**ngrok command:**
```
& "C:\Users\13174\Desktop\Trading Data\ngrok-v3-stable-windows-amd64\ngrok.exe" http 11434 --host-header="localhost:11434" --url=pseudoaccidentally-linty-addie.ngrok-free.dev
```

**App URL:**
```
https://tradehub-420.preview.emergentagent.com
```
