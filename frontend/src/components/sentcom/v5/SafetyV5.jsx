/**
 * V5 Safety overlay — three pieces:
 *
 *   1. useSafety()             hook  — polls /api/safety/status every 8s
 *   2. SafetyBannerV5          full-width red banner when kill-switch tripped
 *   3. FlattenAllButtonV5      bottom-right emergency button (confirm modal)
 *
 * All three live on top of the V5 grid at z-50 so they're visible even when
 * the chart / stream are scrolling. Zero coupling to the rest of V5 —
 * mount once in SentComV5View and forget.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertOctagon, ShieldAlert, X, Loader2, Power, Clock } from 'lucide-react';
import api from '../../../utils/api';


/* ──────────────────────────────────────────────────────────────────────── */
/*  Hook                                                                    */
/* ──────────────────────────────────────────────────────────────────────── */

export const useSafety = ({ pollMs = 8_000 } = {}) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.get('/api/safety/status', { timeout: 6000 });
      setData(r.data);
      setError(null);
    } catch (err) {
      setError(err?.message || 'fetch failed');
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (!pollMs) return undefined;
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [pollMs, refresh]);

  const resetKillSwitch = useCallback(async () => {
    await api.post('/api/safety/reset-kill-switch');
    await refresh();
  }, [refresh]);

  const flattenAll = useCallback(async () => {
    const r = await api.post('/api/safety/flatten-all?confirm=FLATTEN');
    await refresh();
    return r.data;
  }, [refresh]);

  const updateConfig = useCallback(async (patch) => {
    const r = await api.put('/api/safety/config', patch);
    await refresh();
    return r.data;
  }, [refresh]);

  return { data, error, refresh, resetKillSwitch, flattenAll, updateConfig };
};


/* ──────────────────────────────────────────────────────────────────────── */
/*  Banner — shown only when kill-switch is active                          */
/* ──────────────────────────────────────────────────────────────────────── */

export const SafetyBannerV5 = ({ safety }) => {
  const [resetting, setResetting] = useState(false);
  const state = safety?.data?.state;
  if (!state?.kill_switch_active) return null;

  const trippedAt = state.kill_switch_tripped_at
    ? new Date(state.kill_switch_tripped_at * 1000).toLocaleTimeString('en-US', { hour12: false })
    : '—';

  const handleReset = async () => {
    if (resetting) return;
    setResetting(true);
    try { await safety.resetKillSwitch(); } finally { setResetting(false); }
  };

  return (
    <div
      data-testid="v5-safety-banner"
      className="fixed top-0 left-0 right-0 z-[60] bg-gradient-to-r from-rose-900/90 via-rose-700/90 to-rose-900/90 border-b border-rose-400 px-4 py-2 backdrop-blur-md"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <AlertOctagon className="w-5 h-5 text-rose-100 animate-pulse flex-shrink-0" />
          <div className="min-w-0">
            <div className="v5-mono text-xs font-bold text-rose-100 uppercase tracking-widest">
              KILL-SWITCH ACTIVE · no new trades
            </div>
            <div className="v5-why text-[11px] text-rose-200/90 truncate not-italic">
              <span className="v5-mono">{trippedAt}</span>
              <span className="mx-2">·</span>
              {state.kill_switch_reason || 'unknown reason'}
            </div>
          </div>
        </div>
        <button
          onClick={handleReset}
          disabled={resetting}
          data-testid="v5-safety-reset-btn"
          className="shrink-0 px-3 py-1 rounded-sm bg-rose-100 text-rose-900 hover:bg-white v5-mono text-[10px] font-bold uppercase tracking-widest transition-colors disabled:opacity-50"
        >
          {resetting ? <Loader2 className="w-3 h-3 animate-spin inline mr-1" /> : <X className="w-3 h-3 inline mr-1" />}
          Acknowledge + unlock
        </button>
      </div>
    </div>
  );
};


/* ──────────────────────────────────────────────────────────────────────── */
/*  Flatten-all button — bottom-right, confirm modal                        */
/* ──────────────────────────────────────────────────────────────────────── */

export const FlattenAllButtonV5 = ({ safety }) => {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const typedRef = useRef('');
  const [typed, setTyped] = useState('');

  const confirmed = typed.trim().toUpperCase() === 'FLATTEN';

  const onFire = async () => {
    if (!confirmed || busy) return;
    setBusy(true);
    try {
      const r = await safety.flattenAll();
      setResult(r);
    } catch (err) {
      setResult({ success: false, error: err?.message || 'flatten failed' });
    } finally {
      setBusy(false);
    }
  };

  const onClose = () => {
    setOpen(false);
    setResult(null);
    setTyped('');
    typedRef.current = '';
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="v5-flatten-all-btn"
        title="Emergency flatten — cancel all pending + close all positions"
        className="fixed bottom-3 left-3 z-[55] flex items-center gap-1.5 px-3 py-1.5 rounded-sm bg-rose-600/25 hover:bg-rose-600/50 border border-rose-500/60 text-rose-100 v5-mono text-[10px] font-bold uppercase tracking-widest transition-all backdrop-blur-sm"
      >
        <Power className="w-3 h-3" />
        Flatten all
      </button>

      {open && (
        <div
          data-testid="v5-flatten-all-modal"
          className="fixed inset-0 z-[70] bg-black/80 backdrop-blur-sm flex items-center justify-center"
          onClick={onClose}
        >
          <div
            className="max-w-md w-full mx-4 rounded-lg bg-zinc-950 border border-rose-500/40 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {!result ? (
              <>
                <div className="px-4 py-3 border-b border-rose-500/30 bg-rose-950/40">
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="w-4 h-4 text-rose-400" />
                    <span className="v5-mono text-sm font-bold text-rose-200 tracking-widest uppercase">Emergency flatten</span>
                  </div>
                </div>
                <div className="px-4 py-4 space-y-3">
                  <p className="text-[12px] text-zinc-300 leading-relaxed">
                    This will <span className="text-rose-400 font-bold">cancel every pending order</span> and
                    <span className="text-rose-400 font-bold"> market-close every open position</span>. The kill-switch
                    will also latch so the bot cannot re-enter until you reset it.
                  </p>
                  <p className="text-[11px] v5-mono v5-dim">
                    Type <span className="text-rose-400 font-bold">FLATTEN</span> to confirm.
                  </p>
                  <input
                    autoFocus
                    type="text"
                    value={typed}
                    onChange={(e) => { setTyped(e.target.value); typedRef.current = e.target.value; }}
                    className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded-sm v5-mono text-sm text-zinc-100 uppercase focus:border-rose-500 focus:outline-none"
                    placeholder="FLATTEN"
                    data-testid="v5-flatten-confirm-input"
                  />
                </div>
                <div className="px-4 py-3 border-t border-zinc-800 bg-zinc-950 flex justify-end gap-2">
                  <button
                    onClick={onClose}
                    className="px-3 py-1.5 rounded-sm text-zinc-400 hover:text-zinc-200 v5-mono text-[11px] uppercase tracking-widest transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={onFire}
                    disabled={!confirmed || busy}
                    data-testid="v5-flatten-fire-btn"
                    className={`px-4 py-1.5 rounded-sm v5-mono text-[11px] font-bold uppercase tracking-widest transition-colors ${
                      confirmed
                        ? 'bg-rose-600 hover:bg-rose-500 text-white'
                        : 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
                    }`}
                  >
                    {busy ? <Loader2 className="w-3 h-3 inline mr-1 animate-spin" /> : null}
                    Fire
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="px-4 py-3 border-b border-zinc-800 bg-zinc-950">
                  <span className="v5-mono text-sm font-bold tracking-widest uppercase text-zinc-200">
                    Flatten {result.success ? 'complete' : 'failed'}
                  </span>
                </div>
                <div className="px-4 py-4 space-y-2 text-[12px] text-zinc-300">
                  {result.summary ? (
                    <>
                      <div className="v5-why-dim not-italic">Positions closed: <span className="text-emerald-400 font-bold v5-mono">{result.summary.positions_succeeded}</span> / <span className="v5-mono">{result.summary.positions_requested_close}</span></div>
                      {result.summary.positions_failed > 0 && (
                        <div className="v5-why-dim not-italic">Failed: <span className="text-rose-400 font-bold v5-mono">{result.summary.positions_failed}</span></div>
                      )}
                      <div className="v5-why-dim not-italic">Orders cancelled: <span className="v5-mono text-amber-400">{result.summary.orders_cancelled}</span></div>
                    </>
                  ) : (
                    <div className="text-rose-400">{result.error || 'unknown error'}</div>
                  )}
                </div>
                <div className="px-4 py-3 border-t border-zinc-800 flex justify-end">
                  <button
                    onClick={onClose}
                    className="px-4 py-1.5 rounded-sm bg-zinc-800 hover:bg-zinc-700 text-zinc-100 v5-mono text-[11px] font-bold uppercase tracking-widest transition-colors"
                  >
                    Close
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
};


/* ──────────────────────────────────────────────────────────────────────── */
/*  Tiny inline HUD chip — shows risk-cap headroom at a glance              */
/* ──────────────────────────────────────────────────────────────────────── */

export const SafetyHudChip = ({ safety }) => {
  const cfg = safety?.data?.config;
  const st = safety?.data?.state;
  if (!cfg) return null;

  const color = st?.kill_switch_active ? 'v5-chip-veto'
              : !cfg.enabled           ? 'v5-chip-close'
              :                           'v5-chip-manage';
  const label = st?.kill_switch_active ? 'LOCKED'
              : !cfg.enabled           ? 'OFF'
              :                           'ARMED';

  return (
    <span
      data-testid="v5-safety-hud-chip"
      className={`v5-chip ${color}`}
      title={`Daily loss cap: $${cfg.max_daily_loss_usd.toFixed(0)} · max positions: ${cfg.max_positions} · per-symbol cap: $${cfg.max_symbol_exposure_usd.toLocaleString()}`}
    >
      Safety {label}
    </span>
  );
};


/* ──────────────────────────────────────────────────────────────────────── */
/*  Awaiting-quotes pill — amber, shown while any open position is waiting  */
/*  for its first IB quote. Confirms the kill-switch bypass is active so    */
/*  operators can see WHY the bot is holding fire on startup (instead of    */
/*  thinking the bot is hung).                                              */
/* ──────────────────────────────────────────────────────────────────────── */

export const AwaitingQuotesPillV5 = ({ safety }) => {
  const live = safety?.data?.live;
  if (!live?.awaiting_quotes) return null;

  const missing = live.positions_missing_quotes || [];
  const count = missing.length;
  const title = count > 0
    ? `Awaiting first IB quote for: ${missing.join(', ')}. Live unrealized P&L is suppressed from the kill-switch until quotes arrive.`
    : 'Awaiting first IB quote on open positions. Live unrealized P&L is suppressed from the kill-switch until quotes arrive.';

  return (
    <div
      data-testid="v5-awaiting-quotes-pill"
      title={title}
      className="fixed top-2 left-1/2 -translate-x-1/2 z-[58] flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-400/50 backdrop-blur-md shadow-lg shadow-amber-900/20"
    >
      <Clock className="w-3.5 h-3.5 text-amber-300 animate-pulse" />
      <span className="v5-mono text-[10.5px] font-bold uppercase tracking-widest text-amber-200">
        Awaiting IB quotes
      </span>
      {count > 0 && (
        <span
          className="v5-mono text-[10px] text-amber-100/80 px-1.5 py-0.5 rounded-sm bg-amber-500/20 border border-amber-400/30"
          data-testid="v5-awaiting-quotes-symbols"
        >
          {count === 1 ? missing[0] : `${count} positions`}
        </span>
      )}
    </div>
  );
};
