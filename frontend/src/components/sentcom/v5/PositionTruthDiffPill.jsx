/**
 * PositionTruthDiffPill — v19.34.64 (2026-05-20)
 *
 * Compact V5 status-strip indicator showing whether the bot's
 * `_open_trades` symbol set matches IB's authoritative `positions()`.
 *
 * Why this exists:
 *   Pre-v19.34.64 the bot's exit-tracker would silently drift from IB
 *   (OCA-race double-fills, external TWS closes, network-blip partials).
 *   The orphan-reconciler caught up 2-3 min later, but the operator
 *   had no visual signal during the divergence window. On 2026-05-20
 *   an OCA-race direction-flipped IBIT/SOFI/RBLX positions and the
 *   operator only noticed because they happened to be watching TWS.
 *
 *   This pill makes divergence impossible to miss: green dot when in
 *   sync, red `Δ=N` when not. Hover shows the full breakdown:
 *     - bot_only:          bot tracks, IB doesn't (phantom in bot)
 *     - ib_only:           IB has, bot doesn't (orphan at IB)
 *     - direction_flipped: same symbol, opposite sides (OCA-race signature)
 *     - share_mismatch:    same direction, different sizes (partial fill)
 *
 * Polls /api/trading-bot/positions/truth-diff every 5s.
 *
 * NOTE: This is a READ-ONLY canary. It does NOT auto-flatten or auto-
 * reconcile — that's the orphan-reconciler's job. This just gives the
 * operator instant visibility instead of waiting on the reconciler's
 * 2-3 min cadence.
 */
import React, { useEffect, useState } from 'react';
import { GitCompare } from 'lucide-react';
// v316e — switched to fetch+AbortController (no more safeGet) so a
// stalled IB socket can't hang the 5s-cadence poll.

const COLOR = {
  sync: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  drift: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  unknown: 'bg-zinc-700/30 text-zinc-400 border-zinc-700/50',
};

export const PositionTruthDiffPill = ({ onStatus }) => {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    const API = process.env.REACT_APP_BACKEND_URL || '';
    // v316e — hard 4s client timeout so a stalled IB socket can't pile
    // up 5s-cadence requests (the no-timeout hang the operator hit).
    const fetchOnce = async () => {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 4000);
      try {
        const r = await fetch(`${API}/api/trading-bot/positions/truth-diff`, {
          signal: ctrl.signal,
          headers: { Accept: 'application/json' },
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (alive) { setData(d); setErr(null); }
      } catch (e) {
        if (alive) setErr(e?.name === 'AbortError' ? 'timeout' : (e?.message || String(e)));
      } finally {
        clearTimeout(to);
      }
    };
    fetchOnce();
    const t = setInterval(fetchOnce, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    if (err || !data) { onStatus?.('unknown'); return; }
    onStatus?.(data.in_sync ? 'green' : 'red');
  }, [onStatus, err, data]);

  if (err || !data) {
    return (
      <div
        data-testid="v5-position-truth-diff-pill"
        className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[11px] font-mono ${COLOR.unknown}`}
        title={err || 'Loading position diff…'}
      >
        <GitCompare className="w-3 h-3" />
        <span>SYNC ?</span>
      </div>
    );
  }

  const total =
    (data.bot_only?.length || 0) +
    (data.ib_only?.length || 0) +
    (data.direction_flipped?.length || 0) +
    (data.share_mismatch?.length || 0);

  const klass = data.in_sync ? COLOR.sync : COLOR.drift;
  const label = data.in_sync
    ? `SYNC ${data.bot_count}=${data.ib_count}`
    : `Δ ${total}`;

  // Build the hover tooltip — kept terse so the strip stays readable.
  const tooltipLines = [
    `bot tracks: ${data.bot_count}`,
    `IB holds:   ${data.ib_count}`,
  ];
  if (data.direction_flipped?.length) {
    tooltipLines.push('', 'DIRECTION-FLIPPED (OCA race?):');
    for (const f of data.direction_flipped) {
      tooltipLines.push(
        `  ${f.symbol}: bot ${f.bot_side} ${f.bot_shares} vs IB ${f.ib_side} ${f.ib_shares}`
      );
    }
  }
  if (data.bot_only?.length) {
    tooltipLines.push('', 'BOT-ONLY (ghost in bot):');
    for (const b of data.bot_only) tooltipLines.push(`  ${b.symbol} ${b.direction} ${b.shares}`);
  }
  if (data.ib_only?.length) {
    tooltipLines.push('', 'IB-ONLY (orphan at IB):');
    for (const i of data.ib_only) tooltipLines.push(`  ${i.symbol} ${i.direction} ${i.shares}`);
  }
  if (data.share_mismatch?.length) {
    tooltipLines.push('', 'SHARE MISMATCH (partial fill?):');
    for (const m of data.share_mismatch) {
      tooltipLines.push(`  ${m.symbol}: bot ${m.bot_shares} vs IB ${m.ib_shares}`);
    }
  }

  return (
    <div
      data-testid="v5-position-truth-diff-pill"
      data-in-sync={data.in_sync}
      data-delta={total}
      className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[11px] font-mono ${klass}`}
      title={tooltipLines.join('\n')}
    >
      <GitCompare className={`w-3 h-3 ${data.in_sync ? '' : 'animate-pulse'}`} />
      <span>{label}</span>
    </div>
  );
};

export default PositionTruthDiffPill;
