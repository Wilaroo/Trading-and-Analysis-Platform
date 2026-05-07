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
import { fmtET12Sec } from '../../../utils/timeET';


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
    ? fmtET12Sec(state.kill_switch_tripped_at * 1000)
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
            <div className="v5-why text-[13px] text-rose-200/90 truncate not-italic">
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
          className="shrink-0 px-3 py-1 rounded-sm bg-rose-100 text-rose-900 hover:bg-white v5-mono text-[12px] font-bold uppercase tracking-widest transition-colors disabled:opacity-50"
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

export const FlattenAllButtonV5 = ({ safety, inline = false }) => {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const typedRef = useRef('');
  const [typed, setTyped] = useState('');
  // v19.34.32 — Operator opt-in to ALSO trip the kill-switch alongside
  // the close+cancel. Pre-v19.34.32 the backend unconditionally did
  // this. Now it's an explicit checkbox — default OFF — so "clean my
  // books" is the common-case one-click intent.
  const [alsoHaltBot, setAlsoHaltBot] = useState(false);

  const confirmed = typed.trim().toUpperCase() === 'FLATTEN';

  const onFire = async () => {
    if (!confirmed || busy) return;
    setBusy(true);
    try {
      // v19.34.32 — Close/Cancel-All first, then optionally halt.
      // We fire the kill-switch trip AFTER the flatten call succeeds so
      // that if flatten crashes at the pusher layer, we haven't also
      // locked the operator out. The backend race-guard covers the
      // intra-flatten window regardless.
      const r = await safety.flattenAll();
      if (alsoHaltBot) {
        try {
          await api.post('/api/safety/kill-switch/trip',
            { reason: 'operator_close_cancel_all_with_halt' });
        } catch (haltErr) {
          // eslint-disable-next-line no-console
          console.warn('[Close/CancelAll] halt-after-flatten failed:', haltErr?.message || haltErr);
          r.halt_after_flatten_error = haltErr?.message || 'halt call failed';
        }
      }
      await safety?.refresh?.();
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
    setAlsoHaltBot(false);
  };

  // Two layouts:
  //   • inline=true  → compact button meant to sit inside an existing header
  //     (no fixed positioning, matches the v5-chip scale).
  //   • inline=false → legacy floating button in the bottom-left corner.
  const btnClass = inline
    ? "flex items-center gap-1 px-2 py-0.5 rounded-sm bg-rose-600/25 hover:bg-rose-600/60 border border-rose-500/60 text-rose-100 v5-mono text-[11px] font-bold uppercase tracking-widest transition-all"
    : "fixed bottom-3 left-[64px] z-[55] flex items-center gap-1.5 px-3 py-1.5 rounded-sm bg-rose-600/25 hover:bg-rose-600/50 border border-rose-500/60 text-rose-100 v5-mono text-[12px] font-bold uppercase tracking-widest transition-all backdrop-blur-sm";

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="v5-flatten-all-btn"
        data-help-id="flatten-all"
        title="Close every open position + cancel every pending order. Does NOT halt the bot (bot keeps scanning). Check 'Also halt bot?' in the modal to combine with kill-switch."
        className={btnClass}
      >
        <Power className={inline ? "w-2.5 h-2.5" : "w-3 h-3"} />
        Close/Cancel All
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
                    <span className="v5-mono text-sm font-bold text-rose-200 tracking-widest uppercase">Close / Cancel All</span>
                  </div>
                </div>
                <div className="px-4 py-4 space-y-3">
                  <p className="text-[12px] text-zinc-300 leading-relaxed">
                    This will <span className="text-rose-400 font-bold">cancel every pending order</span> and
                    <span className="text-rose-400 font-bold"> market-close every open position</span>.
                  </p>
                  <p className="text-[12px] text-zinc-400 leading-relaxed">
                    The bot <span className="text-emerald-300 font-bold">will keep scanning</span> and may re-enter
                    on its next setup. A short 30-second race-guard prevents new entries <em>during</em> the close
                    iteration — but once complete, trading resumes normally.
                  </p>
                  <label
                    className="flex items-center gap-2 px-2 py-1.5 rounded-sm bg-zinc-900/60 border border-zinc-700 cursor-pointer hover:border-amber-500/50 transition-colors"
                    data-testid="v5-flatten-also-halt-label"
                  >
                    <input
                      type="checkbox"
                      checked={alsoHaltBot}
                      onChange={(e) => setAlsoHaltBot(e.target.checked)}
                      data-testid="v5-flatten-also-halt-checkbox"
                      className="accent-amber-500"
                    />
                    <span className="v5-mono text-[12px] text-zinc-200">
                      Also halt bot <span className="text-zinc-500">(trip kill-switch)</span>
                    </span>
                  </label>
                  {alsoHaltBot && (
                    <p className="text-[11px] text-amber-300/80 leading-relaxed pl-2 border-l-2 border-amber-500/40">
                      After flatten completes, the kill-switch will latch. Bot will refuse new entries
                      until you manually reset via the Safety panel. Scanner keeps finding setups
                      (paused separately via the scanner toggle).
                    </p>
                  )}
                  <p className="text-[13px] v5-mono v5-dim">
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
                    className="px-3 py-1.5 rounded-sm text-zinc-400 hover:text-zinc-200 v5-mono text-[13px] uppercase tracking-widest transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={onFire}
                    disabled={!confirmed || busy}
                    data-testid="v5-flatten-fire-btn"
                    className={`px-4 py-1.5 rounded-sm v5-mono text-[13px] font-bold uppercase tracking-widest transition-colors ${
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
                    className="px-4 py-1.5 rounded-sm bg-zinc-800 hover:bg-zinc-700 text-zinc-100 v5-mono text-[13px] font-bold uppercase tracking-widest transition-colors"
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
      data-help-id="safety-armed"
      className={`v5-chip ${color}`}
      title={`Daily loss cap: $${cfg.max_daily_loss_usd.toFixed(0)} · max positions: ${cfg.max_positions} · per-symbol cap: $${cfg.max_symbol_exposure_usd.toLocaleString()}`}
    >
      Safety {label}
    </span>
  );
};


/* ──────────────────────────────────────────────────────────────────────── */
/*  Account guard chip — PAPER · paperesw100000 (green) or MISMATCH (red).  */
/*  Keeps live/paper accounts configured side-by-side but only ever lets    */
/*  one trade at a time. Backed by /api/safety/status → account_guard.      */
/* ──────────────────────────────────────────────────────────────────────── */

export const AccountGuardChipV5 = ({ safety }) => {
  const g = safety?.data?.account_guard;
  if (!g) return null;

  const mode = (g.active_mode || 'paper').toUpperCase();
  const current = g.current_account_id;
  const currentNorm = (current || '').trim().toLowerCase();
  const expected = g.expected_account_id;
  const expectedAliases = g.expected_aliases || (expected ? [expected] : []);
  const liveAliases = g.live_aliases || (g.live_account_id ? [g.live_account_id] : []);
  const paperAliases = g.paper_aliases || (g.paper_account_id ? [g.paper_account_id] : []);
  const standbyAliases = mode === 'LIVE' ? paperAliases : liveAliases;
  const standbyLabel = mode === 'LIVE' ? 'PAPER standby' : 'LIVE standby';

  const renderAliases = (aliases, isExpectedSet) => {
    if (!aliases?.length) return <span className="v5-dim">—</span>;
    return aliases.map((a) => {
      const hit = isExpectedSet && currentNorm && a.toLowerCase() === currentNorm;
      return (
        <span key={a} className={`alias${hit ? ' active' : ''}`}>
          {a}{hit ? ' ✓' : ''}
        </span>
      );
    });
  };

  const renderPanel = (extraHint = null) => (
    <div className="v5-hover-panel" role="tooltip">
      <div className="row">
        <span className="k">Mode</span>
        <span className="v">{mode}</span>
      </div>
      <div className="row">
        <span className="k">Current</span>
        <span className={`v ${g.match ? 'match' : 'miss'}`}>
          {current || '(none reported)'}
        </span>
      </div>
      <hr />
      <div className="row">
        <span className="k">Expected</span>
        <span className="v">{renderAliases(expectedAliases, true)}</span>
      </div>
      <div className="row">
        <span className="k">{standbyLabel}</span>
        <span className="v">{renderAliases(standbyAliases, false)}</span>
      </div>
      {g.reason && (
        <>
          <hr />
          <div className="reason">{g.reason}</div>
        </>
      )}
      {extraHint && <div className="hint">{extraHint}</div>}
    </div>
  );

  if (!g.match) {
    return (
      <span className="v5-hover-wrap" data-testid="v5-account-guard-chip-wrap" tabIndex={0}>
        <span
          data-testid="v5-account-guard-chip"
          className="v5-chip v5-chip-veto"
        >
          ⚠ ACCOUNT MISMATCH · {current || '—'}
        </span>
        {renderPanel('Kill-switch will auto-trip on next scan cycle.')}
      </span>
    );
  }

  if (g.reason === 'unconfigured') {
    return (
      <span className="v5-hover-wrap" data-testid="v5-account-guard-chip-wrap" tabIndex={0}>
        <span
          data-testid="v5-account-guard-chip"
          className="v5-chip"
        >
          ACCT · unconfigured
        </span>
        <div className="v5-hover-panel" role="tooltip">
          <div className="row">
            <span className="k">Status</span>
            <span className="v">Guard is opt-in</span>
          </div>
          <hr />
          <div className="hint">
            Set <code>IB_ACCOUNT_LIVE</code>, <code>IB_ACCOUNT_PAPER</code>,
            and <code>IB_ACCOUNT_ACTIVE</code> in <code>backend/.env</code> to
            enable. Each var accepts comma-separated aliases (login + IB account number).
          </div>
        </div>
      </span>
    );
  }

  return (
    <span className="v5-hover-wrap" data-testid="v5-account-guard-chip-wrap" data-help-id="account-mismatch" tabIndex={0}>
      <span
        data-testid="v5-account-guard-chip"
        className={`v5-chip ${mode === 'LIVE' ? 'v5-chip-veto' : 'v5-chip-manage'}`}
      >
        {mode} · {current || expected}
      </span>
      {renderPanel()}
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
          className="v5-mono text-[12px] text-amber-100/80 px-1.5 py-0.5 rounded-sm bg-amber-500/20 border border-amber-400/30"
          data-testid="v5-awaiting-quotes-symbols"
        >
          {count === 1 ? missing[0] : `${count} positions`}
        </span>
      )}
    </div>
  );
};


/* ──────────────────────────────────────────────────────────────────────── */
/*  Scanner Pause Toggle (v19.34.26)                                        */
/*                                                                          */
/*  Soft-brake — stop NEW alerts entering the eval pipeline without         */
/*  killing in-flight evals or open-position management. Operator's         */
/*  "I'm done finding new ideas for today" semantic. State is persisted     */
/*  server-side (safety_state collection), so this button reflects the      */
/*  authoritative latch and survives backend restarts.                      */
/*                                                                          */
/*  Reads `safety.data.state.scanner_paused` from the existing useSafety()  */
/*  poll (8s cadence) — no separate endpoint poll needed. Mutating          */
/*  endpoints: POST /api/safety/scanner/{pause,resume}.                     */
/* ──────────────────────────────────────────────────────────────────────── */

export const ScannerPauseToggleV5 = ({ safety, compact = false }) => {
  const [busy, setBusy] = useState(false);
  const paused = !!safety?.data?.state?.scanner_paused;
  const pausedAt = safety?.data?.state?.scanner_paused_at;

  const onClick = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (paused) {
        await api.post('/api/safety/scanner/resume');
      } else {
        await api.post('/api/safety/scanner/pause', { reason: 'operator_toggle' });
      }
      await safety?.refresh?.();
    } catch (e) {
      // Surface a single-line console error; the safety status poll will
      // re-converge state on the next 8s tick if the call ever silently
      // succeeded server-side.
      // eslint-disable-next-line no-console
      console.warn('[ScannerPauseToggleV5] toggle failed:', e?.message || e);
    } finally {
      setBusy(false);
    }
  }, [busy, paused, safety]);

  // When safety hasn't loaded yet, render nothing rather than flash a
  // wrong-state button. Keeps the header from layout-shifting.
  if (!safety?.data) return null;

  const label = paused ? 'PAUSED' : 'LIVE';
  const title = paused
    ? `Scanner paused${pausedAt ? ` since ${fmtET12Sec(pausedAt * 1000)}` : ''} — click to resume new alert intake`
    : 'Scanner live — click to pause new alert intake (open positions keep managing)';

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      data-testid="v5-scanner-pause-toggle"
      data-state={paused ? 'paused' : 'running'}
      title={title}
      className={[
        'v5-mono inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm border transition-colors',
        compact ? 'text-[10px]' : 'text-[11px]',
        busy ? 'opacity-60 cursor-wait' : 'cursor-pointer',
        paused
          ? 'bg-amber-500/15 border-amber-400/40 text-amber-200 hover:bg-amber-500/25'
          : 'bg-emerald-500/10 border-emerald-400/30 text-emerald-300 hover:bg-emerald-500/20',
      ].join(' ')}
    >
      {busy
        ? <Loader2 size={compact ? 10 : 11} className="animate-spin" />
        : <Power size={compact ? 10 : 11} />
      }
      <span>{label}</span>
    </button>
  );
};



/* ──────────────────────────────────────────────────────────────────────── */
/*  IB-LIVE brokerage-permission chip (v19.34.27)                           */
/*                                                                          */
/*  Polls /api/system/ib-direct/status every 15s. Surfaces FOUR distinct    */
/*  states the operator needs to distinguish at a glance:                   */
/*                                                                          */
/*    IB-LIVE   (green)  connected + authorized_to_trade — orders OK        */
/*    IB-AUTH   (amber)  connected, but managedAccounts is empty            */
/*                       ("logged in on another platform" scenario)         */
/*    IB-DOWN   (red)    socket not connected — pusher might still work     */
/*    IB-OFF    (gray)   ib_async not installed (Phase 1 not deployed)      */
/*                                                                          */
/*  Tooltip surfaces order_path mode + shadow divergence counters when      */
/*  BOT_ORDER_PATH=shadow so the operator can see at-a-glance whether       */
/*  pusher and IB-direct have been agreeing today.                          */
/* ──────────────────────────────────────────────────────────────────────── */

export const useIbDirectStatus = ({ pollMs = 15_000 } = {}) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.get('/api/system/ib-direct/status', { timeout: 6000 });
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

  return { data, error, refresh };
};

export const IbLiveChipV5 = () => {
  const { data } = useIbDirectStatus();
  const [connecting, setConnecting] = useState(false);

  // First paint: render a neutral placeholder rather than nothing so
  // the status strip doesn't layout-shift on initial load.
  if (!data) {
    return (
      <span
        data-testid="v5-ib-live-chip"
        data-state="loading"
        className="v5-chip v5-chip-close"
        title="IB direct status loading…"
      >
        IB-…
      </span>
    );
  }

  const ibAvailable = !!data.ib_async_available;
  const connected = !!data.connected;
  const authorized = !!data.authorized_to_trade;
  const orderPath = data.shadow?.order_path || 'pusher';
  const counters = data.shadow?.counters || {};
  const divergences =
    (counters.missing_at_ib || 0) +
    (counters.direction_mismatch || 0) +
    (counters.auth_lost || 0);

  let label;
  let color;
  let state;
  if (!ibAvailable) {
    label = 'IB-OFF'; color = 'v5-chip-close'; state = 'unavailable';
  } else if (!connected) {
    label = 'IB-DOWN'; color = 'v5-chip-veto'; state = 'disconnected';
  } else if (!authorized) {
    label = 'IB-AUTH'; color = 'v5-chip-eval'; state = 'auth_lost';
  } else {
    label = 'IB-LIVE'; color = 'v5-chip-manage'; state = 'live';
  }

  // Operator can click an IB-DOWN chip to attempt a reconnect without
  // hunting for the curl endpoint.
  const onClick = async () => {
    if (connecting) return;
    if (state === 'disconnected' && ibAvailable) {
      setConnecting(true);
      try { await api.post('/api/system/ib-direct/connect'); }
      catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[IbLiveChipV5] connect failed:', e?.message || e);
      } finally { setConnecting(false); }
    }
  };

  const tooltipLines = [
    `IB direct: ${state}`,
    `host=${data.host}:${data.port} clientId=${data.client_id}`,
    data.managed_accounts?.length
      ? `accounts: ${data.managed_accounts.join(', ')}`
      : 'managedAccounts: (none)',
    `order_path: ${orderPath}`,
  ];
  if (orderPath === 'shadow') {
    tooltipLines.push(
      `shadow: ${counters.observed_ok || 0} ok · ${divergences} divergences`
    );
  }
  if (state === 'disconnected') tooltipLines.push('Click to attempt reconnect');
  if (data.last_connect_error) tooltipLines.push(`last error: ${data.last_connect_error}`);

  return (
    <span
      role={state === 'disconnected' ? 'button' : undefined}
      onClick={state === 'disconnected' ? onClick : undefined}
      data-testid="v5-ib-live-chip"
      data-state={state}
      data-order-path={orderPath}
      className={`v5-chip ${color}`}
      title={tooltipLines.join('\n')}
      style={{
        cursor: state === 'disconnected' && !connecting ? 'pointer' : 'default',
        opacity: connecting ? 0.6 : 1,
      }}
    >
      {connecting ? '…' : label}
      {orderPath === 'shadow' && divergences > 0 && (
        <span
          data-testid="v5-ib-live-shadow-divergences"
          style={{ marginLeft: 4, color: '#f87171' }}
        >
          ⚠{divergences}
        </span>
      )}
    </span>
  );
};


/* ──────────────────────────────────────────────────────────────────────── */
/*  ScannerPausedBannerV5 (v19.34.27 — UX nudge)                            */
/*                                                                          */
/*  Persistent banner above the Scanner card list when the pause latch is   */
/*  active. Loud yellow strip with elapsed time so the operator can't       */
/*  forget the soft-brake is on the morning after.                          */
/*                                                                          */
/*  Compact one-liner — does NOT push the cards or chart out of view.       */
/* ──────────────────────────────────────────────────────────────────────── */

export const ScannerPausedBannerV5 = ({ safety }) => {
  const paused = !!safety?.data?.state?.scanner_paused;
  const pausedAt = safety?.data?.state?.scanner_paused_at;
  const reason = safety?.data?.state?.scanner_paused_reason;
  const [now, setNow] = useState(Date.now());
  const [resuming, setResuming] = useState(false);

  // Tick every 15s for the elapsed-time render so the operator sees
  // the pause duration grow. 15s is plenty granular for "30m" or "2h"
  // displays without burning render cycles.
  useEffect(() => {
    if (!paused) return undefined;
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, [paused]);

  if (!paused) return null;

  const elapsedSec = pausedAt ? Math.max(0, Math.floor(now / 1000 - pausedAt)) : 0;
  let elapsedText;
  if (elapsedSec < 60)        elapsedText = `${elapsedSec}s`;
  else if (elapsedSec < 3600) elapsedText = `${Math.floor(elapsedSec / 60)}m`;
  else                        elapsedText = `${Math.floor(elapsedSec / 3600)}h ${Math.floor((elapsedSec % 3600) / 60)}m`;

  const onResume = async () => {
    if (resuming) return;
    setResuming(true);
    try {
      await api.post('/api/safety/scanner/resume');
      await safety?.refresh?.();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[ScannerPausedBannerV5] resume failed:', e?.message || e);
    } finally { setResuming(false); }
  };

  const reasonLabel = reason && reason !== 'manual_pause' && reason !== 'operator_toggle'
    ? ` · ${reason}`
    : '';

  return (
    <div
      data-testid="v5-scanner-paused-banner"
      role="status"
      className="flex items-center gap-2 px-3 py-1.5 border-b border-amber-500/40 bg-amber-500/15 text-amber-100"
      title={`Scanner alert intake paused since ${pausedAt ? fmtET12Sec(pausedAt * 1000) : '—'}${reasonLabel}. Open-position management continues normally.`}
    >
      <Power size={11} className="flex-shrink-0 text-amber-300" />
      <div className="flex-1 min-w-0 v5-mono text-[11px] truncate">
        <span className="font-bold">Scanner paused</span>
        <span className="opacity-70"> · {elapsedText}{reasonLabel} · open positions keep managing</span>
      </div>
      <button
        type="button"
        data-testid="v5-scanner-paused-banner-resume"
        onClick={onResume}
        disabled={resuming}
        className="v5-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 border border-amber-400/40 hover:bg-amber-500/25 text-amber-100 rounded-sm flex-shrink-0 disabled:opacity-50"
      >
        {resuming ? '…' : 'resume'}
      </button>
    </div>
  );
};
