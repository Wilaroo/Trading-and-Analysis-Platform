/**
 * EOD Countdown Banner — v19.14 (2026-04-30)
 *
 * Sticky banner pinned above the day-rollup that activates 5 min
 * before the EOD close window so the operator has a last-minute
 * chance to flatten manually or extend a winning position before
 * auto-close fires at 3:55 PM ET (12:55 PM on half-days).
 *
 * Drives off `GET /api/trading-bot/eod-status` (lightweight; only
 * polls when status is non-idle).
 *
 * States:
 *   idle      — outside window. Component returns null.
 *   imminent  — ≤5 min until close. Live MM:SS countdown +
 *               position list. "Close all now" override button.
 *   closing   — close window has opened; auto-close running.
 *   complete  — EOD ran cleanly today. Hide after 60s of "complete".
 *   alarm     — past 4:00 PM with positions still locally open.
 *               Loud red banner.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

// Poll cadence: heavier when window is active, lighter outside it.
const POLL_INTERVAL_ACTIVE_MS = 5000;
const POLL_INTERVAL_IDLE_MS = 30000;

function _fmtMmSs(secs) {
  if (secs == null || !Number.isFinite(secs)) return '--:--';
  const sign = secs < 0 ? '-' : '';
  const s = Math.abs(Math.round(secs));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${sign}${m}:${String(r).padStart(2, '0')}`;
}

export const EodCountdownBannerV5 = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [closingNow, setClosingNow] = useState(false);
  const [completeHiddenAt, setCompleteHiddenAt] = useState(null);

  // Local-clock countdown — server gives us eta_seconds, we tick it
  // down each second between polls so the display feels live.
  const [clientEta, setClientEta] = useState(null);
  const lastFetchRef = useRef(0);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/trading-bot/eod-status`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      if (!body?.success) throw new Error(body?.error || 'fetch failed');
      setData(body);
      setClientEta(body.eta_seconds);
      lastFetchRef.current = Date.now();
    } catch (_e) {
      // Silent — banner just won't render until next successful poll.
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  // Adaptive polling — heavier when active.
  useEffect(() => {
    const interval =
      data && ['imminent', 'closing', 'alarm'].includes(data.status)
        ? POLL_INTERVAL_ACTIVE_MS
        : POLL_INTERVAL_IDLE_MS;
    const id = setInterval(fetchStatus, interval);
    return () => clearInterval(id);
  }, [data, fetchStatus]);

  // 1 Hz client-side countdown so the operator sees seconds tick.
  useEffect(() => {
    if (!data || data.status === 'idle' || data.status === 'complete') return;
    const id = setInterval(() => {
      setClientEta((prev) => (prev == null ? null : prev - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [data]);

  const handleCloseAllNow = useCallback(async () => {
    setClosingNow(true);
    try {
      const r = await fetch(`${API_BASE}/api/trading-bot/eod-close-now`, {
        method: 'POST',
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || !body?.success) {
        // eslint-disable-next-line no-alert
        alert(`EOD close failed: ${body?.error || body?.detail || `HTTP ${r.status}`}`);
      }
    } catch (e) {
      // eslint-disable-next-line no-alert
      alert(`EOD close error: ${e.message || String(e)}`);
    } finally {
      setClosingNow(false);
      setConfirming(false);
      // Force-refresh status so the banner flips state.
      fetchStatus();
    }
  }, [fetchStatus]);

  // Auto-hide complete state after 60s so the bar doesn't linger
  // forever after a clean close.
  useEffect(() => {
    if (data?.status === 'complete' && !completeHiddenAt) {
      setCompleteHiddenAt(Date.now() + 60_000);
    }
    if (data?.status !== 'complete' && completeHiddenAt) {
      setCompleteHiddenAt(null);
    }
  }, [data, completeHiddenAt]);

  const presentation = useMemo(() => {
    if (!data) return null;
    if (loading) return null;
    if (data.status === 'idle') return null;
    if (data.status === 'complete' && completeHiddenAt && Date.now() > completeHiddenAt) {
      return null;
    }
    return data;
  }, [data, loading, completeHiddenAt]);

  if (!presentation) return null;

  const { status, intraday_positions_queued: queued, swing_positions_holding: swing,
    intraday_symbols: symbols, close_time_et, is_half_day } = presentation;

  // Per-state styling — calm for imminent, urgent for closing/alarm,
  // muted-green for complete.
  const tone = {
    imminent: {
      bg: 'bg-amber-500/10 border-amber-500/30',
      accent: 'text-amber-300',
      label: 'EOD CLOSE',
      icon: '⏱',
    },
    closing: {
      bg: 'bg-rose-500/15 border-rose-500/40',
      accent: 'text-rose-300',
      label: 'EOD CLOSING',
      icon: '⏵',
    },
    alarm: {
      bg: 'bg-rose-600/25 border-rose-500/60',
      accent: 'text-rose-200',
      label: 'EOD ALARM',
      icon: '⚠',
    },
    complete: {
      bg: 'bg-emerald-500/10 border-emerald-500/30',
      accent: 'text-emerald-300',
      label: 'EOD COMPLETE',
      icon: '✓',
    },
  }[status] || {
    bg: 'bg-zinc-900/40 border-zinc-700',
    accent: 'text-zinc-300',
    label: 'EOD',
    icon: '·',
  };

  return (
    <div
      data-testid="v5-eod-countdown-banner"
      className={`px-3 py-1.5 border-b ${tone.bg} sticky top-0 z-[10] v5-mono`}
      title={`EOD close window: ${close_time_et}${is_half_day ? '  [HALF-DAY MODE]' : ''}`}
    >
      <div className="flex items-center justify-between gap-3 text-[12px]">
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          <span className={`${tone.accent} font-bold tracking-widest text-[11px]`}>
            {tone.icon} {tone.label}
          </span>
          {status === 'imminent' && (
            <>
              <span className="text-zinc-400">in</span>
              <span
                className={`${tone.accent} font-bold text-[14px] tabular-nums`}
                data-testid="v5-eod-countdown-clock"
              >
                {_fmtMmSs(clientEta)}
              </span>
              <Sep />
              <span className="text-zinc-300">
                <span className="text-zinc-500">queued</span>{' '}
                <span className="font-bold">{queued}</span>{' '}
                <span className="text-zinc-500">intraday</span>
              </span>
              {swing > 0 && (
                <>
                  <Sep />
                  <span className="text-zinc-500">
                    holding <span className="text-zinc-300 font-semibold">{swing}</span> swing
                  </span>
                </>
              )}
              {symbols && symbols.length > 0 && (
                <>
                  <Sep />
                  <span className="truncate text-zinc-400 text-[11px]" title={symbols.join(', ')}>
                    {symbols.slice(0, 8).join(' · ')}
                    {symbols.length > 8 ? ` +${symbols.length - 8}` : ''}
                  </span>
                </>
              )}
            </>
          )}
          {status === 'closing' && (
            <>
              <span className="text-zinc-300">
                Closing <span className="font-bold">{queued}</span> intraday position{queued === 1 ? '' : 's'} now…
              </span>
              {swing > 0 && (
                <>
                  <Sep />
                  <span className="text-zinc-500">
                    holding <span className="text-zinc-300 font-semibold">{swing}</span> swing overnight
                  </span>
                </>
              )}
            </>
          )}
          {status === 'alarm' && (
            <span className={`${tone.accent} font-semibold`}>
              {queued} position{queued === 1 ? '' : 's'} still OPEN past market close — verify IB-side state
            </span>
          )}
          {status === 'complete' && (
            <span className="text-zinc-300">
              All eligible intraday positions closed for today.
              {swing > 0 && (
                <span className="text-zinc-500"> Holding <span className="text-zinc-300 font-semibold">{swing}</span> swing overnight.</span>
              )}
            </span>
          )}
          {is_half_day && (
            <>
              <Sep />
              <span className="text-orange-300 text-[11px] font-bold tracking-widest">HALF-DAY</span>
            </>
          )}
        </div>

        {(status === 'imminent' || status === 'alarm') && queued > 0 && (
          <div className="flex items-center gap-2 shrink-0">
            {!confirming ? (
              <button
                type="button"
                data-testid="v5-eod-close-all-btn"
                onClick={() => setConfirming(true)}
                className="px-2 py-0.5 text-[11px] font-bold tracking-widest border border-rose-500/50 text-rose-300 hover:bg-rose-500/20 transition-colors"
              >
                CLOSE ALL NOW
              </button>
            ) : (
              <>
                <span className="text-rose-300 text-[11px]">Confirm?</span>
                <button
                  type="button"
                  data-testid="v5-eod-close-all-confirm-btn"
                  onClick={handleCloseAllNow}
                  disabled={closingNow}
                  className="px-2 py-0.5 text-[11px] font-bold bg-rose-500 text-white hover:bg-rose-600 disabled:opacity-50 transition-colors"
                >
                  {closingNow ? 'CLOSING…' : 'YES — CLOSE'}
                </button>
                <button
                  type="button"
                  data-testid="v5-eod-close-all-cancel-btn"
                  onClick={() => setConfirming(false)}
                  disabled={closingNow}
                  className="px-2 py-0.5 text-[11px] text-zinc-400 hover:text-zinc-200 transition-colors"
                >
                  cancel
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const Sep = () => <span className="text-zinc-700">·</span>;

export default EodCountdownBannerV5;
