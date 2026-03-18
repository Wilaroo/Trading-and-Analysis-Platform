# TradeCommand Weekend Auto Setup Guide

## Overview

This automation system allows TradeCommand to run batch operations (data collection, model training, simulations) automatically on weekends and/or overnight without manual intervention.

## Components

1. **WeekendAuto.bat** - Master script that:
   - Runs StartTrading.bat
   - Waits for services to be ready
   - Launches weekend_batch.py

2. **weekend_batch.py** - Python script that:
   - Detects if it's weekend or nightly time
   - Triggers Smart Collection (ADV-filtered stocks)
   - Monitors progress until complete
   - Triggers model retraining
   - Runs batch simulations
   - Logs everything to `weekend_batch.log`

3. **TradeCommand_WeekendAuto_Task.xml** - Windows Task Scheduler template

## Quick Setup

### Step 1: Copy Files
Copy these files to your trading scripts folder (same place as StartTrading.bat):
- `WeekendAuto.bat`
- `weekend_batch.py`
- `TradeCommand_WeekendAuto_Task.xml`

### Step 2: Configure Task Scheduler

1. Open Task Scheduler:
   - Press `Win + R`, type `taskschd.msc`, press Enter

2. Import the task:
   - Click "Import Task..." in the right panel
   - Select `TradeCommand_WeekendAuto_Task.xml`

3. Update settings:
   - **General tab**: Click "Change User or Group" and enter your Windows credentials
   - **Actions tab**: Update the path to where `WeekendAuto.bat` is located
   - **Triggers tab**: Adjust times if needed (default: Sat/Sun 2 AM)

4. Enable "Wake to run":
   - **Conditions tab**: Ensure "Wake the computer to run this task" is checked

5. Click OK and enter your password when prompted

### Step 3: Configure Power Settings

For the computer to wake from sleep:

1. Open Power Options:
   - Press `Win + R`, type `powercfg.cpl`, press Enter

2. Click "Change plan settings" for your active plan

3. Click "Change advanced power settings"

4. Expand "Sleep" > "Allow wake timers"
   - Set to "Enable" for both Battery and Plugged in

### Step 4: Configure IB Gateway Auto-Restart (Optional)

If you want IB Gateway to auto-reconnect after disconnection:

1. Open IB Gateway
2. Go to Configure > Settings > Auto Restart
3. Set your preferred restart times
4. Enable "Auto restart"

## Modes

The `weekend_batch.py` script supports different modes:

| Mode | When | What It Does |
|------|------|--------------|
| `auto` | Default | Detects weekend (Sat/Sun) or nightly (after 8 PM) |
| `weekend` | Sat/Sun | Full batch: Smart Collection + Training + Simulations |
| `nightly` | Weeknights | Quick refresh: Smart Collection only |
| `manual` | Testing | Shows what would run without executing |

## Manual Testing

Test the automation before relying on it:

```batch
:: Test detection (won't actually run anything)
python weekend_batch.py --cloud-url https://tradecommand.trade --mode manual

:: Force weekend mode
python weekend_batch.py --cloud-url https://tradecommand.trade --mode weekend

:: Force nightly mode  
python weekend_batch.py --cloud-url https://tradecommand.trade --mode nightly
```

## Logs

Check `weekend_batch.log` in your scripts folder for:
- What was triggered
- Progress updates
- Any errors

## Troubleshooting

### Computer doesn't wake up
1. Check BIOS settings - "Wake on RTC Alarm" must be enabled
2. Ensure Wake Timers are enabled in Power Options
3. Some laptops don't support wake from sleep via Task Scheduler

### IB Gateway doesn't connect
1. Check IB Gateway auto-login is configured
2. May need 2FA app approval if using 2FA
3. Check for IB maintenance windows (usually Sunday evenings)

### Collection doesn't start
1. Check `weekend_batch.log` for errors
2. Verify cloud URL is reachable
3. Ensure IB Data Pusher window is open

### Batch runs during trading hours
1. Check system time is correct
2. Use `--mode manual` to verify detection logic
3. Adjust triggers in Task Scheduler

## Default Schedule

| Day | Time | Mode | Actions |
|-----|------|------|---------|
| Saturday | 2:00 AM | weekend | Smart Collection → Training → Simulations |
| Sunday | 2:00 AM | weekend | Smart Collection → Training → Simulations |
| Weekdays | 9:00 PM | nightly | Smart Collection only (DISABLED by default) |

To enable weekday nightly runs, edit the task in Task Scheduler and enable the weekday trigger.
