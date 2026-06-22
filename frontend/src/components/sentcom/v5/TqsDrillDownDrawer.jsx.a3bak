/**
 * TqsDrillDownDrawer — v19.34.258 (Part B)
 *
 * The single right-side slide-over that consolidates everything that used
 * to be scattered across the card face into ONE trusted drill-down:
 *   • Header — symbol, direction, setup, trade-style, full TQS badge
 *   • Open-position metrics (entry/current/SL/TP + unrealized P&L) — only
 *     for active trades (source=position)
 *   • 5 weighted pillars (reuses TqsPillarPanel internals)
 *   • Folded context — 30d setup perf (win%/avg-R), EV-R, catalyst + gap
 *
 * Data contract: GET /api/tqs/card-detail/{symbol}?source=alert|position
 * (v19.34.256). Mounted ONCE at the V5 root; opened via tqsDrawerBus.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { X, TrendingUp, TrendingDown } from 'lucide-react';
import { TQS_OPEN_EVENT } from './tqsDrawerBus';
import TqsBadge from './TqsBadge';
import TqsPillarPanel from './TqsPillarPanel';
import { gradingStyleKey } from '../../../utils/tradeStyleMeta';

const fmtPx = (v) => (v == null || Number.isNaN(Number(v)) ? '—' : `$${Number(v).toFixed(2)}`);
const fmtPct = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${pct >= 0 ? '' : ''}${pct.toFixed(1)}%`;
};
const fmtR = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}R`;
};
const fmtUsd = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${n >= 0 ? '+$' : '−$'}${Math.abs(n).toFixed(0)}`;
};
const fmtTime = (v) => {
  if (!v) return '—';
  try {
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return String(v);
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return String(v); }
};

const ContextWidget = ({ label, value, sub, tone = 'text-zinc-200', name }) => (
  <div
    data-testid={`context-widget-${name}`}
    className="bg-zinc-900/40 rounded border border-zinc-800/50 p-3 flex flex-col gap-0.5"
  >
    <span className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</span>
    <span className={`v5-mono text-sm font-bold ${tone}`}>{value}</span>
    {sub && <span className="text-[11px] text-zinc-500">{sub}</span>}
  </div>
);

const TqsDrillDownDrawer = () => {
  const [open, setOpen] = useState(false);
  const [meta, setMeta] = useState({ symbol: '', source: 'alert' });
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  const close = useCallback(() => setOpen(false), []);

  const load = useCallback(async (symbol, source) => {
    setLoading(true);
    setError(null);
    setDetail(null);
    try {
      const base = process.env.REACT_APP_BACKEND_URL || '';
      const url = `${base}/api/tqs/card-detail/${encodeURIComponent(symbol)}?source=${encodeURIComponent(source)}`;
      const r = await fetch(url);
      const j = await r.json();
      if (!j || j.success === false) {
        throw new Error(j?.error || 'no_persisted_tqs');
      }
      setDetail(j);
    } catch (e) {
      setError(e?.message || 'load_failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const onOpen = (e) => {
      const { symbol, source } = e.detail || {};
      if (!symbol) return;
      setMeta({ symbol, source: source || 'alert' });
      setOpen(true);
      load(symbol, source || 'alert');
    };
    window.addEventListener(TQS_OPEN_EVENT, onOpen);
    return () => window.removeEventListener(TQS_OPEN_EVENT, onOpen);
  }, [load]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    if (open) document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, close]);

  const dir = String(detail?.direction || '').toLowerCase();
  const isShort = dir === 'short';
  const DirIcon = isShort ? TrendingDown : TrendingUp;
  const dirAccent = isShort ? 'text-rose-400' : 'text-emerald-400';

  const pos = detail?.position;
  const perf = detail?.setup_perf;

  // Reconstruct the tqs-shaped object TqsPillarPanel consumes.
  const pillarTqs = detail
    ? {
        score: detail.tqs_score,
        unified_grade: detail.tqs_grade,
        weights: detail.weights || {},
        breakdown: detail.breakdown || {},
      }
    : null;

  // v19.34.272 (UI Track A / P1) — grading style (pattern, not liquidity).
  // Prefer the persisted scoring_style; fall back to the setup-derived pattern.
  const scoringStyle = detail
    ? gradingStyleKey({ scoring_style: detail.scoring_style, setup_type: detail.setup_type })
    : null;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={close}
        className={`fixed inset-0 z-[60] bg-black/60 transition-opacity duration-200 ${
          open ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        data-testid="tqs-drilldown-backdrop"
      />
      {/* Slide-over */}
      <aside
        data-testid="tqs-drilldown-drawer"
        className={`fixed top-0 right-0 z-[61] h-full w-full sm:w-[540px] bg-zinc-950 border-l border-zinc-800 text-zinc-300 shadow-2xl flex flex-col transition-transform duration-300 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
        style={{ transitionTimingFunction: 'cubic-bezier(0.16,1,0.3,1)' }}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 p-5 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur-md flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1.5 min-w-0">
            <div className="flex items-center gap-2">
              <span className="v5-mono text-3xl font-bold text-white tracking-tight">
                {meta.symbol}
              </span>
              {detail && (
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm border text-[11px] uppercase tracking-wider ${
                  isShort ? 'text-rose-300 border-rose-700 bg-rose-950/40' : 'text-emerald-300 border-emerald-700 bg-emerald-950/40'
                }`}>
                  <DirIcon className={`w-3 h-3 ${dirAccent}`} />
                  {isShort ? 'Short' : 'Long'}
                </span>
              )}
            </div>
            {detail && (
              <div className="flex items-center gap-2 text-[11px] text-zinc-400 uppercase tracking-wider flex-wrap">
                {detail.setup_type && <span>{String(detail.setup_type).replace(/_/g, ' ')}</span>}
                {detail.trade_style && <span className="text-zinc-600">· {String(detail.trade_style).replace(/_/g, ' ')}</span>}
                {detail.tqs_action && <span className="text-zinc-600">· {detail.tqs_action}</span>}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {detail && (
              <TqsBadge
                symbol={meta.symbol}
                score={detail.tqs_score}
                gradeFallback={detail.tqs_grade}
                variant="full"
                testIdSuffix="drawer-header"
              />
            )}
            <button
              type="button"
              onClick={close}
              data-testid="tqs-drilldown-close"
              className="text-zinc-500 hover:text-zinc-200 transition-colors"
              aria-label="Close"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto v5-scroll">
          {loading && (
            <div className="p-6 text-center text-[13px] text-zinc-500 v5-mono">Loading TQS breakdown…</div>
          )}
          {!loading && error && (
            <div className="p-6 text-center text-[13px] text-zinc-500" data-testid="tqs-drilldown-empty">
              <div className="v5-mono text-rose-400/80">No persisted TQS for {meta.symbol}.</div>
              <div className="mt-1 text-zinc-600">
                This card predates TQS capture, or no scored alert is on record yet.
              </div>
            </div>
          )}

          {!loading && detail && (
            <div className="p-5 space-y-5">
              {/* Open position metrics — only for active trades */}
              {pos && (
                <div
                  data-testid="open-position-metrics"
                  className={`bg-zinc-900 border-l-2 ${isShort ? 'border-rose-500' : 'border-sky-500'} rounded-r p-4 grid grid-cols-3 gap-y-3 gap-x-4`}
                >
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500">Entry</span>
                    <span className="v5-mono text-sm text-zinc-200">{fmtPx(pos.entry_price)}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500">Current</span>
                    <span className="v5-mono text-sm text-zinc-200">{fmtPx(pos.current_price)}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500">Shares</span>
                    <span className="v5-mono text-sm text-zinc-200">{pos.shares ?? '—'}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500">Stop</span>
                    <span className="v5-mono text-sm text-rose-300">{fmtPx(pos.stop_price)}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500">Target</span>
                    <span className="v5-mono text-sm text-emerald-300">{fmtPx(pos.target_price)}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500">Unreal. P&L</span>
                    <span className={`v5-mono text-sm font-bold ${Number(pos.unrealized_pnl) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {fmtUsd(pos.unrealized_pnl)}{pos.unrealized_r != null ? ` · ${fmtR(pos.unrealized_r)}` : ''}
                    </span>
                  </div>
                  <div className="flex flex-col col-span-3">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500">Entry time</span>
                    <span className="v5-mono text-[12px] text-zinc-400">{fmtTime(pos.entry_time)}</span>
                  </div>
                </div>
              )}

              {/* 5 weighted pillars */}
              {pillarTqs && <TqsPillarPanel tqs={pillarTqs} scoringStyle={scoringStyle} testIdSuffix="drawer" />}

              {/* Folded-in context */}
              <div>
                <span className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Context</span>
                <div className="grid grid-cols-2 gap-3 mt-2">
                  {perf && (
                    <ContextWidget
                      name="setup-perf"
                      label="30d Setup Win%"
                      value={fmtPct(perf.win_rate)}
                      sub={perf.avg_r != null ? `avg ${fmtR(perf.avg_r)}${perf.sample_size != null ? ` · n=${perf.sample_size}` : ''}` : (perf.sample_size != null ? `n=${perf.sample_size}` : null)}
                      tone={Number(perf.win_rate) >= 0.5 ? 'text-emerald-400' : 'text-amber-400'}
                    />
                  )}
                  {perf && perf.expected_value_r != null && (
                    <ContextWidget
                      name="ev-r"
                      label="Expected Value"
                      value={fmtR(perf.expected_value_r)}
                      tone={Number(perf.expected_value_r) >= 0 ? 'text-emerald-400' : 'text-rose-400'}
                    />
                  )}
                  {(detail.catalyst_tag || detail.gap_pct != null) && (
                    <ContextWidget
                      name="catalyst"
                      label="Catalyst / Gap"
                      value={detail.catalyst_tag ? String(detail.catalyst_tag).replace(/_/g, ' ') : '—'}
                      sub={detail.gap_pct != null ? `gap ${fmtPct(detail.gap_pct)}` : null}
                    />
                  )}
                  {detail.catalyst_summary && (
                    <ContextWidget
                      name="catalyst-summary"
                      label="Catalyst note"
                      value={<span className="text-[12px] font-normal leading-snug">{detail.catalyst_summary}</span>}
                    />
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  );
};

export default TqsDrillDownDrawer;
export { TqsDrillDownDrawer };
