/**
 * RegimeStrip — full-width multi-timeframe market-regime band for the
 * Command Center. Visualizes the v315/v316 multi_tf engine:
 *
 *   CONTEXT  ·  1D / 1H / 5m / 1m lanes (SPY/QQQ/IWM blended)  ·
 *   LONG/SHORT trading modes  ·  $TICK internals (+ climax)  ·
 *   per-index breakdown (SPY/QQQ/IWM)  ·  divergence flags.
 *
 * Data source: GET /api/market-regime/summary (now carries `multi_tf`).
 * Degrades gracefully: if multi_tf is absent (no intraday bars / engine
 * cold) the strip shows the daily-anchor context only, never blank.
 */
import React, { useEffect, useState, useCallback } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const REFRESH_MS = 30_000;

// bias → tints (UP green / DOWN red / NEUTRAL zinc)
const biasTint = (bias) => {
  if (bias === 'UP') return { bg: 'rgba(34,197,94,0.16)', fg: '#86efac', dot: '#22c55e' };
  if (bias === 'DOWN') return { bg: 'rgba(244,63,94,0.16)', fg: '#fda4af', dot: '#f43f5e' };
  return { bg: 'rgba(113,113,122,0.18)', fg: '#a1a1aa', dot: '#71717a' };
};
const biasArrow = (bias) => (bias === 'UP' ? '▲' : bias === 'DOWN' ? '▼' : '▬');

// context → headline tint
const CONTEXT_TINT = {
  ALIGNED_UP: { bg: 'rgba(34,197,94,0.22)', fg: '#bbf7d0', label: 'ALIGNED UP' },
  PULLBACK_IN_UPTREND: { bg: 'rgba(132,204,22,0.20)', fg: '#d9f99d', label: 'PULLBACK · UPTREND' },
  MIXED: { bg: 'rgba(161,161,170,0.20)', fg: '#d4d4d8', label: 'MIXED' },
  BOUNCE_IN_DOWNTREND: { bg: 'rgba(245,158,11,0.20)', fg: '#fde68a', label: 'BOUNCE · DOWNTREND' },
  ALIGNED_DOWN: { bg: 'rgba(244,63,94,0.22)', fg: '#fecdd3', label: 'ALIGNED DOWN' },
  UNKNOWN: { bg: 'rgba(113,113,122,0.18)', fg: '#a1a1aa', label: 'UNKNOWN' },
};

// per-direction trading mode → tint
const MODE_TINT = {
  aggressive: { fg: '#34d399', bg: 'rgba(16,185,129,0.20)', label: 'AGGR' },
  normal: { fg: '#86efac', bg: 'rgba(34,197,94,0.14)', label: 'NORMAL' },
  cautious: { fg: '#fbbf24', bg: 'rgba(245,158,11,0.16)', label: 'CAUTIOUS' },
  defensive: { fg: '#fda4af', bg: 'rgba(244,63,94,0.16)', label: 'DEFENSIVE' },
};

// Semantic horizon labels + the human-readable lookback span each lane
// analyzes (derived from the engine's bar windows: 220 daily / 120 hourly /
// 120×5m / 120×1m). Spans are easy to retune here without touching the engine.
const LANE_META = {
  long:  { term: 'LONG TERM',  span: '~1yr', tf: '1-day bars · 20/50/200 SMA' },
  mid:   { term: 'MID TERM',   span: '~18d', tf: '1-hour bars · 20/50 EMA' },
  short: { term: 'SHORT TERM', span: '~2d',  tf: '5-min bars · 9/21 EMA + VWAP' },
  micro: { term: 'MICRO',      span: '~2h',  tf: '1-min bars · 9/21 EMA + VWAP' },
};
const fmtScore = (s) => (s == null || Number.isNaN(Number(s)) ? '—' : Number(s).toFixed(0));

const Lane = ({ k, lane }) => {
  if (!lane) return null;
  const m = LANE_META[k] || { term: k, span: '', tf: lane.timeframe };
  const t = biasTint(lane.bias);
  return (
    <div
      data-testid={`regime-lane-${k}`}
      title={`${m.term} · ${m.span} · ${m.tf} · score ${fmtScore(lane.score)} · ${lane.bias}`}
      className="flex flex-col items-center justify-center rounded px-2 py-0.5 min-w-[64px]"
      style={{ backgroundColor: t.bg, color: t.fg }}
    >
      <span className="v5-mono text-[9px] uppercase tracking-wide leading-tight opacity-80 whitespace-nowrap">
        {m.term}
      </span>
      <span className="v5-mono text-[9px] leading-tight opacity-60">{m.span}</span>
      <span className="v5-mono text-[12px] font-bold leading-tight">
        {biasArrow(lane.bias)} {fmtScore(lane.score)}
      </span>
    </div>
  );
};

const ModeChip = ({ side, mode }) => {
  const t = MODE_TINT[mode] || MODE_TINT.cautious;
  return (
    <div
      data-testid={`regime-mode-${side}`}
      title={`${side.toUpperCase()} stance: ${mode}`}
      className="flex items-center gap-1 rounded px-2 py-0.5"
      style={{ backgroundColor: t.bg, color: t.fg }}
    >
      <span className="v5-mono text-[10px] uppercase opacity-70">{side}</span>
      <span className="v5-mono text-[12px] font-bold">{t.label}</span>
    </div>
  );
};

export const RegimeStrip = () => {
  const [mtf, setMtf] = useState(null);
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/api/market-regime/summary`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setMtf(d.multi_tf || null);
      setState({ state: d.state, display: d.state_display, score: d.composite_score, reco: d.recommendation });
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, REFRESH_MS);
    return () => clearInterval(t);
  }, [fetchData]);

  const ctx = mtf?.context || 'UNKNOWN';
  const ctxT = CONTEXT_TINT[ctx] || CONTEXT_TINT.UNKNOWN;
  const internals = mtf?.internals || null;
  const perIndex = mtf?.per_index || {};
  const divergence = mtf?.divergence || [];
  const align = mtf?.tf_alignment;

  return (
    <div
      data-testid="regime-strip"
      className="flex items-center flex-wrap gap-x-3 gap-y-1 px-3 py-1 bg-zinc-950 border-b border-zinc-800 text-[13px]"
    >
      <span className="v5-mono text-[11px] text-zinc-500 uppercase tracking-wide shrink-0">Regime</span>

      {/* CONTEXT headline */}
      <div
        data-testid="regime-context"
        title={mtf?.recommendation || state?.reco || ''}
        className="flex items-center gap-1.5 rounded px-2.5 py-0.5 font-bold shrink-0"
        style={{ backgroundColor: ctxT.bg, color: ctxT.fg }}
      >
        <span className="v5-mono text-[12px]">{ctxT.label}</span>
        {align?.dominant && align.dominant !== 'UNKNOWN' && (
          <span className="v5-mono text-[10px] opacity-70">
            {align.dominant} {Math.round((align.ratio || 0) * 100)}%
          </span>
        )}
      </div>

      {/* 4 timeframe lanes */}
      {mtf?.lanes ? (
        <div className="flex items-center gap-1">
          {['long', 'mid', 'short', 'micro'].map((k) => (
            <Lane key={k} k={k} lane={mtf.lanes[k]} />
          ))}
        </div>
      ) : (
        !loading && (
          <span data-testid="regime-strip-degraded" className="v5-mono text-[11px] text-zinc-600">
            daily-anchor only (intraday bars cold)
          </span>
        )
      )}

      {/* per-direction modes */}
      {mtf?.modes && (
        <div className="flex items-center gap-1">
          <ModeChip side="long" mode={mtf.modes.long} />
          <ModeChip side="short" mode={mtf.modes.short} />
        </div>
      )}

      {/* TICK internals */}
      {internals && (() => {
        const it = biasTint(internals.bias);
        return (
        <div
          data-testid="regime-internals"
          title={`$TICK internals · NYSE+Nasdaq blended · ${internals.bias}${internals.climax ? ` · ${internals.climax_dir}` : ''}`}
          className="flex items-center gap-1 rounded px-2 py-0.5"
          style={{ backgroundColor: it.bg, color: it.fg }}
        >
          <span className="v5-mono text-[10px] uppercase opacity-70">$TICK</span>
          <span className="v5-mono text-[12px] font-bold">{biasArrow(internals.bias)} {fmtScore(internals.score)}</span>
          {internals.climax && (
            <span className="v5-mono text-[10px] px-1 rounded bg-amber-500/30 text-amber-200">
              {internals.climax_dir === 'BUY_CLIMAX' ? 'BUY CLIMAX' : internals.climax_dir === 'SELL_CLIMAX' ? 'SELL CLIMAX' : 'CLIMAX'}
            </span>
          )}
        </div>
        );
      })()}

      {/* per-index breakdown (intraday read) */}
      {['SPY', 'QQQ', 'IWM'].some((s) => perIndex[s]) && (
        <div className="flex items-center gap-1">
          {['SPY', 'QQQ', 'IWM'].map((s) => {
            const px = perIndex[s];
            if (!px) return null;
            const intra = px.intraday;
            const b = intra == null ? 'NEUTRAL' : intra >= 55 ? 'UP' : intra <= 45 ? 'DOWN' : 'NEUTRAL';
            const t = biasTint(b);
            return (
              <span
                key={s}
                data-testid={`regime-index-${s.toLowerCase()}`}
                title={`${s} · long ${fmtScore(px.long)} / intraday ${fmtScore(intra)}`}
                className="v5-mono text-[11px] rounded px-1.5 py-0.5"
                style={{ backgroundColor: t.bg, color: t.fg }}
              >
                {s} {fmtScore(intra)}
              </span>
            );
          })}
        </div>
      )}

      {/* divergence flags */}
      {divergence.length > 0 && (
        <div data-testid="regime-divergence" className="flex items-center gap-1">
          {divergence.map((d) => (
            <span key={d} className="v5-mono text-[10px] rounded px-1.5 py-0.5 bg-amber-500/20 text-amber-200">
              {d.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}

      {error && (
        <span data-testid="regime-strip-error" className="v5-mono text-[11px] text-rose-500 ml-auto">{error}</span>
      )}
    </div>
  );
};

export default RegimeStrip;
