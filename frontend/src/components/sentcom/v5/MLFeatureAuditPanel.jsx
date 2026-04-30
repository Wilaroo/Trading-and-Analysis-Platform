/**
 * MLFeatureAuditPanel — drop-in panel that audits which label-features
 * (market_setup + multi_index_regime + sector_regime) are firing for a
 * given symbol RIGHT NOW. Backed by `GET /api/scanner/ml-feature-
 * preview/{symbol}`.
 *
 * Shipped 2026-05-01 (v19.22) in response to: "is the regime + sector +
 * setup signal actually feeding the model on this trade?" The panel
 * answers that question without ever opening a terminal.
 *
 * Behaviour:
 *  • Symbol input is editable AND auto-fills whenever any other panel
 *    dispatches `sentcom:focus-symbol` (gap-scanner row, gameplan
 *    chip, etc).
 *  • Three colored label badges at the top show the resolved
 *    market_setup, multi_index_regime, sector_regime for the symbol.
 *  • "Active features" list shows the one-hot bins that fired (=1.0).
 *  • Each `$TICKER` mention in the panel re-emits focus-symbol when
 *    clicked so you can hop between symbols quickly.
 *
 * Standalone — does NOT auto-mount; embed wherever you want it (e.g.,
 * the V5 dashboard side rail or the diagnostics drawer).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Search, Loader2, RefreshCcw, Activity } from 'lucide-react';
import api from '../../../utils/api';

const focusSymbol = (sym) => {
  try {
    window.dispatchEvent(
      new CustomEvent('sentcom:focus-symbol', { detail: { symbol: sym } }),
    );
  } catch {
    // best-effort
  }
};

const setupAccent = (label) => {
  if (!label || label === 'neutral' || label === 'unknown') return 'text-zinc-400 border-zinc-700 bg-zinc-900';
  if (label.includes('gap_and_go') || label.includes('range_break')) return 'text-emerald-300 border-emerald-700 bg-emerald-500/10';
  if (label.includes('overextension') || label.includes('gap_up_into_resistance')) return 'text-rose-300 border-rose-700 bg-rose-500/10';
  if (label.includes('volatility')) return 'text-amber-300 border-amber-700 bg-amber-500/10';
  return 'text-violet-300 border-violet-700 bg-violet-500/10';
};

const regimeAccent = (label) => {
  if (!label || label === 'unknown') return 'text-zinc-400 border-zinc-700 bg-zinc-900';
  if (label.startsWith('risk_on')) return 'text-emerald-300 border-emerald-700 bg-emerald-500/10';
  if (label.startsWith('risk_off')) return 'text-rose-300 border-rose-700 bg-rose-500/10';
  if (label.includes('divergence')) return 'text-amber-300 border-amber-700 bg-amber-500/10';
  return 'text-violet-300 border-violet-700 bg-violet-500/10';
};

const sectorAccent = (label) => {
  if (!label || label === 'unknown') return 'text-zinc-400 border-zinc-700 bg-zinc-900';
  if (label === 'leader') return 'text-emerald-300 border-emerald-700 bg-emerald-500/10';
  if (label === 'laggard') return 'text-rose-300 border-rose-700 bg-rose-500/10';
  return 'text-violet-300 border-violet-700 bg-violet-500/10';
};

const Badge = ({ label, value, accentFn, testid }) => {
  const v = value || 'unknown';
  return (
    <div className="flex flex-col gap-0.5">
      <span className="v5-mono text-[9px] uppercase tracking-widest text-zinc-500">
        {label}
      </span>
      <span
        data-testid={testid}
        className={`v5-mono text-[11px] uppercase tracking-wider px-2 py-1 rounded border ${accentFn(v)}`}
      >
        {v.replace(/_/g, ' ')}
      </span>
    </div>
  );
};

const MLFeatureAuditPanel = ({ defaultSymbol = '' }) => {
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [draft, setDraft] = useState(defaultSymbol);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Listen for focus-symbol dispatches anywhere in the app — auto-prefill
  // the symbol input + fetch when an external panel surfaces a ticker.
  useEffect(() => {
    const onFocus = (evt) => {
      const sym = (evt?.detail?.symbol || '').toUpperCase();
      if (!sym) return;
      setDraft(sym);
      setSymbol(sym);
    };
    window.addEventListener('sentcom:focus-symbol', onFocus);
    return () => window.removeEventListener('sentcom:focus-symbol', onFocus);
  }, []);

  const fetchPreview = useCallback(async (sym) => {
    if (!sym) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get(
        `/api/scanner/ml-feature-preview/${encodeURIComponent(sym)}`,
        { timeout: 15_000 },
      );
      const j = res?.data;
      if (!j) throw new Error('Empty response');
      setData(j);
    } catch (e) {
      setError(e?.message || 'Fetch failed');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Re-fetch any time `symbol` changes.
  useEffect(() => {
    if (symbol) fetchPreview(symbol);
  }, [symbol, fetchPreview]);

  const submit = (e) => {
    e?.preventDefault();
    const clean = (draft || '').toUpperCase().trim();
    if (!clean) return;
    setSymbol(clean);
  };

  const labels = data?.labels || {};
  const fv = data?.feature_vector || {};
  const active = fv.active_features || [];
  const total = fv.feature_count || 0;
  const hasAnyActive = active.length > 0;

  return (
    <div
      data-testid="ml-feature-audit-panel"
      className="rounded-md border border-zinc-800 bg-zinc-950/60 overflow-hidden"
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-900 bg-zinc-950/80">
        <div className="flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-violet-300" />
          <span className="v5-mono text-[11px] uppercase tracking-widest text-violet-300 font-bold">
            ML Feature Audit
          </span>
        </div>
        <button
          type="button"
          data-testid="ml-audit-refresh"
          onClick={() => fetchPreview(symbol)}
          disabled={loading || !symbol}
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

      <form onSubmit={submit} className="px-3 py-2 border-b border-zinc-900">
        <div className="flex items-center gap-2">
          <Search className="w-3.5 h-3.5 text-zinc-500" />
          <input
            type="text"
            data-testid="ml-audit-symbol-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value.toUpperCase())}
            placeholder="Symbol (e.g. NVDA)"
            className="flex-1 bg-transparent border-none outline-none v5-mono text-[13px] text-zinc-200 placeholder:text-zinc-600"
          />
          <button
            type="submit"
            data-testid="ml-audit-submit"
            disabled={!draft || loading}
            className="v5-mono text-[10px] uppercase tracking-widest px-2 py-1 rounded bg-violet-500/15 text-violet-300 border border-violet-500/30 hover:bg-violet-500/25 disabled:opacity-50 transition-colors"
          >
            Audit
          </button>
        </div>
      </form>

      <div className="px-3 py-3 space-y-3" data-testid="ml-audit-body">
        {error && (
          <div className="text-[12px] text-rose-400/80 italic">{error}</div>
        )}

        {!error && !data && !loading && (
          <div className="text-[12px] text-zinc-500 italic">
            Type a symbol or click any{' '}
            <span className="v5-mono text-violet-300">$TICKER</span> elsewhere
            to audit which ML label-features fire on it right now.
          </div>
        )}

        {data && (
          <>
            {/* Three label badges — primary signal layers */}
            <div className="grid grid-cols-3 gap-2">
              <Badge
                label="Setup"
                value={labels.market_setup}
                accentFn={setupAccent}
                testid="ml-audit-label-setup"
              />
              <Badge
                label="Regime"
                value={labels.multi_index_regime}
                accentFn={regimeAccent}
                testid="ml-audit-label-regime"
              />
              <Badge
                label="Sector"
                value={labels.sector_regime}
                accentFn={sectorAccent}
                testid="ml-audit-label-sector"
              />
            </div>

            {/* Wiring status */}
            <div
              data-testid="ml-audit-wiring-status"
              className={`text-[12px] flex items-center gap-2 ${
                hasAnyActive ? 'text-emerald-400' : 'text-amber-400/80'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-current" />
              <span>
                {hasAnyActive
                  ? `Wired — ${active.length} of ${total} feature bins active`
                  : `Cold start — 0 of ${total} feature bins active (data sparse or all "unknown")`}
              </span>
            </div>

            {/* Active feature pills */}
            {hasAnyActive && (
              <div data-testid="ml-audit-active-features">
                <div className="v5-mono text-[10px] uppercase tracking-widest text-zinc-500 mb-1">
                  Active feature bins
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {active.map((feat) => (
                    <span
                      key={feat}
                      className="v5-mono text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                    >
                      {feat.replace(/^setup_label_/, 'setup:')
                          .replace(/^regime_label_/, 'regime:')
                          .replace(/^sector_label_/, 'sector:')
                          .replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Quick-jump links to related symbols (when narrative supplied any) */}
            {data?.symbol && (
              <div className="text-[10px] text-zinc-600 v5-mono pt-1">
                Audited {' '}
                <button
                  type="button"
                  data-testid="ml-audit-symbol-chip"
                  onClick={() => focusSymbol(data.symbol)}
                  className="text-violet-300 hover:text-violet-100"
                >
                  ${data.symbol}
                </button>
                {data.generated_at && (
                  <span className="text-zinc-700">
                    {' · '}
                    {new Date(data.generated_at).toLocaleTimeString()}
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default MLFeatureAuditPanel;
