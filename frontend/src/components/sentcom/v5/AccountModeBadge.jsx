/**
 * AccountModeBadge — v19.31.13 (2026-05-04)
 *
 * Top-strip HUD badge showing which IB account the bot is firing
 * against right now. Operator's "I never want to confuse paper for
 * live when switching accounts" requirement.
 *
 * Renders:
 *   - PAPER · DUN615665   (amber)  — paper account detected
 *   - LIVE · U7654321     (red)    — live account detected, danger color
 *   - SHADOW              (sky)    — pusher offline, env says paper standby
 *   - UNKNOWN             (slate)  — pusher offline AND env unconfigured
 *
 * Polls /api/system/account-mode every 30s. Pulls from the Windows IB
 * pusher's account snapshot — DU* prefix → paper, anything else → live
 * via account_guard.classify_account_id.
 */
import React, { useEffect, useState, useRef } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const MODE_STYLE = {
  live:    { cls: 'bg-rose-950/60 text-rose-300 border-rose-700 hover:border-rose-500', label: 'LIVE' },
  paper:   { cls: 'bg-amber-950/60 text-amber-300 border-amber-700 hover:border-amber-500', label: 'PAPER' },
  shadow:  { cls: 'bg-sky-950/60 text-sky-300 border-sky-700 hover:border-sky-500', label: 'SHADOW' },
  unknown: { cls: 'bg-slate-900/80 text-slate-300 border-slate-700 hover:border-slate-500', label: 'UNKNOWN' },
};

const truncateAccount = (id) => {
  if (!id) return null;
  const s = String(id);
  return s.length > 12 ? `${s.slice(0, 5)}…${s.slice(-4)}` : s;
};

export default function AccountModeBadge() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/api/system/account-mode`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (cancelled) return;
        setData(j);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    };
    tick();
    timer.current = setInterval(tick, 30000);
    return () => { cancelled = true; if (timer.current) clearInterval(timer.current); };
  }, []);

  if (error && !data) {
    return (
      <span
        data-testid="account-mode-badge-error"
        className="px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border border-zinc-800 text-zinc-500"
        title={error}
      >
        ACCT · ?
      </span>
    );
  }

  if (!data) {
    return (
      <span
        data-testid="account-mode-badge-loading"
        className="px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border border-zinc-800 text-zinc-600"
      >
        ACCT · …
      </span>
    );
  }

  // effective_mode is what trade_type freshly-filled bot_trades will get.
  // It's the IB-detected mode when present, or the env-configured mode
  // when pusher is offline. We display whichever is most informative:
  //   - If pusher connected AND we have a current account ID → display
  //     detected mode + truncated account ID.
  //   - If pusher offline → display "SHADOW · standby" using effective_mode.
  //   - If unconfigured → "UNKNOWN".
  const detected = data.detected_mode || 'unknown';
  const effective = data.effective_mode || 'unknown';
  const acct = data.current_account_id;
  const ibConnected = !!data.ib_connected;
  const matched = !!data.match;

  // Choose primary color based on what the bot will stamp on next fill.
  const primary = (() => {
    if (effective === 'live') return MODE_STYLE.live;
    if (effective === 'paper') return MODE_STYLE.paper;
    if (effective === 'shadow') return MODE_STYLE.shadow;
    return MODE_STYLE.unknown;
  })();

  // Inline subtitle: account id when known, "standby" when pusher off,
  // or the reason string when account_guard reports a mismatch.
  const subLabel = acct
    ? truncateAccount(acct)
    : (ibConnected ? '—' : 'standby');

  // Hover panel shows everything — detected vs effective vs env, match status.
  const tooltipLines = [
    `Detected: ${detected.toUpperCase()}${acct ? ` · ${acct}` : ''}`,
    `Effective (next fill): ${effective.toUpperCase()}`,
    `Env active mode: ${(data.active_mode || '?').toUpperCase()}`,
    `Pusher connected: ${ibConnected ? 'yes' : 'no'}`,
    `Account match: ${matched ? 'ok' : 'no'}${data.reason ? ` · ${data.reason}` : ''}`,
  ];

  return (
    <span
      data-testid="account-mode-badge"
      data-mode={effective}
      data-detected={detected}
      data-account={acct || ''}
      title={tooltipLines.join('\n')}
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded border ${primary.cls} transition-colors cursor-help`}
    >
      <span data-testid="account-mode-badge-label">{primary.label}</span>
      {subLabel && (
        <span
          data-testid="account-mode-badge-id"
          className="font-mono opacity-80 normal-case tracking-normal"
        >
          · {subLabel}
        </span>
      )}
      {!matched && acct && (
        <span data-testid="account-mode-badge-mismatch" className="opacity-80">⚠</span>
      )}
    </span>
  );
}
