"""
IB Historical Data Collection Status Monitor
=============================================
A terminal-based status display that auto-refreshes.

Run in a separate terminal while the collector is running:
    python collector_status.py

Or to run alongside the collector:
    python collector_status.py --watch
"""

import requests
import time
import os
import sys
from datetime import datetime

# Configuration
API_BASE = os.environ.get('API_BASE', 'http://localhost:8001')
REFRESH_INTERVAL = 5  # seconds

def clear_screen():
    """Clear terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

def get_progress_data():
    """Fetch progress data from API"""
    try:
        progress = requests.get(f'{API_BASE}/api/ib-collector/queue-progress-detailed', timeout=10).json()
        failures = requests.get(f'{API_BASE}/api/ib-collector/failure-analysis', timeout=10).json()
        stats = requests.get(f'{API_BASE}/api/ib-collector/stats', timeout=10).json()
        return progress, failures, stats
    except Exception as e:
        return None, None, None

def format_number(n):
    """Format number with commas"""
    return f"{n:,}" if isinstance(n, int) else str(n)

def progress_bar(pct, width=20):
    """Create a visual progress bar"""
    filled = int(pct / 100 * width)
    return '█' * filled + '░' * (width - filled)

def display_status(progress, failures, stats):
    """Display the status dashboard"""
    if not progress or not progress.get('success'):
        print("⚠️  Unable to fetch data from API")
        return
    
    overall = progress.get('overall', {})
    by_bar = progress.get('by_bar_size', [])
    breakdown = failures.get('breakdown', {}) if failures else {}
    stats_data = stats.get('stats', {}) if stats else {}
    
    # Calculate totals
    total = overall.get('total', 0)
    completed = overall.get('completed', 0)
    pending = overall.get('pending', 0)
    failed = overall.get('failed', 0)
    claimed = overall.get('claimed', 0)
    pct = (completed / total * 100) if total > 0 else 0
    
    # Header
    print("╔" + "═" * 72 + "╗")
    print("║" + " 📊 IB HISTORICAL DATA COLLECTION STATUS ".center(72) + "║")
    print("║" + f" Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ".center(72) + "║")
    print("╠" + "═" * 72 + "╣")
    
    # Overall Progress
    print("║" + " OVERALL PROGRESS ".center(72, '─') + "║")
    print("║" + f"  {progress_bar(pct, 40)} {pct:>6.1f}%".ljust(72) + "║")
    print("║" + f"  ✓ Completed: {format_number(completed):>10}  │  ⏳ In Progress: {claimed:>5}  │  ⏸ Pending: {format_number(pending):>10}".ljust(72) + "║")
    print("║" + f"  ✗ Failed: {failed:>6}  │  📦 Total Bars: {format_number(stats_data.get('total_bars', 0)):>12}".ljust(72) + "║")
    print("╠" + "═" * 72 + "╣")
    
    # By Timeframe
    print("║" + " PROGRESS BY TIMEFRAME ".center(72, '─') + "║")
    print("║" + f"  {'Timeframe':<10} {'Done':>8} {'Pending':>8} {'Progress':>22} {'ETA':>12}  ".ljust(72) + "║")
    print("║" + "  " + "-" * 68 + "  ║")
    
    for bar in sorted(by_bar, key=lambda x: x.get('progress_pct', 0), reverse=True):
        name = bar.get('bar_size', '?')
        done = bar.get('completed', 0)
        pend = bar.get('pending', 0)
        bar_pct = bar.get('progress_pct', 0)
        eta = bar.get('eta_display', 'N/A')
        stuck = bar.get('in_progress', 0)
        
        stuck_indicator = f" ⚠{stuck}" if stuck > 0 else ""
        line = f"  {name:<10} {done:>8,} {pend:>8,} {progress_bar(bar_pct, 12)} {bar_pct:>5.1f}% {eta:>10}{stuck_indicator}"
        print("║" + line.ljust(72) + "║")
    
    print("╠" + "═" * 72 + "╣")
    
    # Failure Breakdown
    print("║" + " FAILURE BREAKDOWN ".center(72, '─') + "║")
    success = breakdown.get('success', 0)
    no_data = breakdown.get('no_data', 0)
    timeout = breakdown.get('timeout', 0)
    rate_limited = breakdown.get('rate_limited', 0)
    errors = breakdown.get('error', 0)
    
    print("║" + f"  ✓ Success: {format_number(success):>10}  │  ⊘ No Data: {no_data:>5}  │  ⏱ Timeout: {timeout:>5}".ljust(72) + "║")
    print("║" + f"  🚫 Rate Limited: {rate_limited:>5}  │  ✗ Errors: {errors:>5}".ljust(72) + "║")
    
    print("╠" + "═" * 72 + "╣")
    
    # Collection Rate
    active = [b for b in by_bar if b.get('is_active')]
    if active:
        avg_rate = sum(b.get('symbols_per_minute', 0) for b in active) / len(active)
        print("║" + f"  📈 Collection Rate: ~{avg_rate:.1f} symbols/minute across {len(active)} active timeframes".ljust(72) + "║")
    
    print("╚" + "═" * 72 + "╝")
    print("\n  Press Ctrl+C to exit  │  Auto-refresh every 5 seconds")

def main():
    """Main loop"""
    watch_mode = '--watch' in sys.argv or '-w' in sys.argv
    
    print("🔄 Connecting to API...")
    
    while True:
        try:
            clear_screen()
            progress, failures, stats = get_progress_data()
            display_status(progress, failures, stats)
            
            if not watch_mode:
                print("\n  Run with --watch for continuous monitoring")
                break
            
            time.sleep(REFRESH_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n\n👋 Exiting status monitor...")
            break
        except Exception as e:
            print(f"\n⚠️  Error: {e}")
            if watch_mode:
                time.sleep(REFRESH_INTERVAL)
            else:
                break

if __name__ == '__main__':
    main()
