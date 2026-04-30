/**
 * PremarketGapScannerWidget — live list of recent gappers from the
 * background scanner. Surfaces what gapped in the last N minutes (default
 * 8 mins, operator-configurable) so the trader can see fresh momentum
 * setups at a glance during the open and through the day.
 *
 * Shipped 2026-05-01 (v19.21). Backed by `GET /api/live-scanner/premarket-
 * gappers`. Each row's symbol is a clickable chip that dispatches the
 * `sentcom:focus-symbol` event so SentCom.jsx auto-fires a "walk me
 * through $SYM right now" chat query.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { TrendingUp, TrendingDown, RefreshCcw, Loader2 } from 'lucide-react';
import api from '../../../utils/api';

const POLL_INTERVAL_MS = 30_000;

const fmtPrice = (v) =>
  v == null || Number.isNaN(Number(v)) ? '—' : `$${Number(v).toFixed(2)}`;
const fmtPct = (v) =>
  v == null || Number.isNaN(Number(v))
    ? '—'
    : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`;
const fmtAge = (sec) => {
  if (sec == null) return '—';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  return `${Math.floor(sec / 3600)}h`;
};

/**
 * Broadcast a focus-symbol intent. SentCom.jsx listens and auto-chats.
 */
const focusSymbol = (symbol) => {
  try {
    window.dispatchEvent(
      new CustomEvent('sentcom:focus-symbol', { detail: { symbol } }),
    );
  } catch {
    // best-effort
  }
};

const PremarketGapScannerWidget = ({
  windowMinutes = 8,
  minGapPct = 2.0,
  maxResults = 25,
  height = 340,
}) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [generatedAt, setGeneratedAt] = useState(null);

  const fetchGappers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = `/api/live-scanner/premarket-gappers?window_minutes=${windowMinutes}&min_gap_pct=${minGapPct}&max_results=${maxResults}`;
      const res = await api.get(url, { timeout: 15_000 });
      const j = res?.data;
      if (!j?.success) throw new Error('Bad response shape');
      setRows(j.gappers || []);
      setGeneratedAt(j.generated_at || null);
    } catch (e) {
      setError(e?.message || 'Failed to load gappers');
    } finally {
      setLoading(false);
    }
  }, [windowMinutes, minGapPct, maxResults]);

  useEffect(() => {
    fetchGappers();
    const t = setInterval(fetchGappers, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [fetchGappers]);

  return (
    <div
      data-testid="premarket-gap-scanner-widget"
      className="rounded-md border border-zinc-800 bg-zinc-950/60 overflow-hidden flex flex-col"
      style={{ height }}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-900 bg-zinc-950/80">
        <div className="flex items-center gap-2">
          <span className="v5-mono text-[11px] uppercase tracking-widest text-violet-300 font-bold">
            Gappers · last {windowMinutes}m
          </span>
          <span className="v5-mono text-[10px] text-zinc-500">
            ≥{minGapPct.toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center gap-2">
          {generatedAt && (
            <span className="v5-mono text-[9px] text-zinc-600 hidden sm:inline">
              {new Date(generatedAt).toLocaleTimeString()}
            </span>
          )}
          <button
            type="button"
            data-testid="gap-scanner-refresh"
            onClick={fetchGappers}
            disabled={loading}
            className="text-zinc-500 hover:text-violet-300 transition-colors disabled:opacity-50"
            title="Refresh"
          >
            {loading ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCcw className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      <div
        data-testid="gap-scanner-list"
        className="flex-1 overflow-y-auto"
      >
        {error && (
          <div className="px-3 py-3 text-[12px] text-rose-400/80 italic">
            {error}
          </div>
        )}
        {!error && rows.length === 0 && !loading && (
          <div className="px-3 py-3 text-[12px] text-zinc-500 italic">
            No gappers in the last {windowMinutes} min above ±{minGapPct}%.
            (Quiet tape, or scanner hasn't woken up yet.)
          </div>
        )}
        {rows.map((r, i) => {
          const sym = (r.symbol || '').toUpperCase();
          const isLong = (r.direction || '').toLowerCase() === 'long';
          const Dir = (r.gap_pct || 0) >= 0 ? TrendingUp : TrendingDown;
          const dirAccent =
            (r.gap_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400';
          const setupPretty = (r.setup_type || '')
            .replace(/_/g, ' ')
            .replace(/\b\w/g, (c) => c.toUpperCase());
          const isCountertrend = !!r.is_countertrend;
          return (
            <div
              key={`${sym}-${i}`}
              data-testid={`gap-row-${sym}`}
              className="flex items-center gap-2 px-3 py-2 border-b border-zinc-900 hover:bg-zinc-900/50 transition-colors"
            >
              <button
                type="button"
                data-testid={`gap-row-symbol-${sym}`}
                onClick={() => focusSymbol(sym)}
                className="v5-mono text-[13px] font-bold text-violet-300 hover:text-violet-100 transition-colors w-[60px] text-left shrink-0"
              >
                ${sym}
              </button>
              <Dir className={`w-3.5 h-3.5 ${dirAccent} shrink-0`} />
              <span
                className={`v5-mono text-[12px] font-bold w-[64px] shrink-0 ${dirAccent}`}
              >
                {fmtPct(r.gap_pct)}
              </span>
              <span className="v5-mono text-[11px] text-zinc-400 w-[60px] shrink-0">
                {fmtPrice(r.current_price)}
              </span>
              <span
                className={`v5-mono text-[10px] uppercase tracking-wider truncate flex-1 ${
                  isLong ? 'text-emerald-300/80' : 'text-rose-300/80'
                }`}
                title={setupPretty}
              >
                {setupPretty}
              </span>
              {isCountertrend && (
                <span
                  className="v5-mono text-[9px] uppercase tracking-wider px-1 py-0.5 rounded bg-amber-500/20 text-amber-300"
                  title="Counter-trend vs market setup"
                  data-testid={`gap-row-countertrend-${sym}`}
                >
                  CTR
                </span>
              )}
              <span className="v5-mono text-[10px] text-zinc-500 w-[32px] text-right shrink-0">
                {fmtAge(r.alert_age_seconds)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default PremarketGapScannerWidget;
export { focusSymbol as focusGapScannerSymbol };
