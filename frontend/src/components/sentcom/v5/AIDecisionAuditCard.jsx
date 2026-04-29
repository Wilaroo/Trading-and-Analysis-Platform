/**
 * AIDecisionAuditCard — Per-trade AI module audit for the V5 dashboard.
 *
 * Answers "for each closed trade, what did each AI module say, and was
 * that module's signal aligned with the actual P&L outcome?". Pairs
 * with the SmartLevelsAnalyticsCard to give the operator full
 * provenance over how the AI is steering trades.
 *
 * Reads `/api/trading-bot/ai-decision-audit?limit=30` (refreshes
 * every 60s). Renders nothing until data arrives so the panel doesn't
 * pop on mount.
 *
 * Header strip shows per-module alignment-rate (denominator =
 * consultations, NOT total trades — modules don't get penalised for
 * trades where they abstained). Below that, the most recent trades
 * with a per-module verdict pill (✓ aligned, ✗ wrong, − abstained).
 */
import React, { useEffect, useState, useCallback } from 'react';
import { Brain, ChevronRight } from 'lucide-react';
import { safeGet } from '../../../utils/api';

const _fmtPct = (p) => (p == null ? '—' : `${(p * 100).toFixed(0)}%`);
const _fmtPnl = (p) => {
  if (p == null || p === 0) return '—';
  const sign = p >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(p).toFixed(0)}`;
};

const MODULE_DISPLAY = {
  debate: 'Debate',
  risk_manager: 'Risk',
  institutional: 'Flow',
  time_series: 'TS',
};

const _verdictPill = (mod) => {
  if (!mod) {
    return { glyph: '−', cls: 'text-zinc-700', title: 'No data' };
  }
  if (mod.verdict === 'abstain') {
    return { glyph: '−', cls: 'text-zinc-700', title: 'Abstained' };
  }
  if (mod.aligned) {
    return {
      glyph: '✓',
      cls: 'text-emerald-400',
      title: `${mod.verdict} → aligned with outcome`,
    };
  }
  return {
    glyph: '✗',
    cls: 'text-rose-400/70',
    title: `${mod.verdict} → opposite of outcome`,
  };
};

const PerModuleStrip = ({ summary }) => {
  const modules = ['debate', 'risk_manager', 'institutional', 'time_series'];
  return (
    <div
      data-testid="ai-decision-audit-summary"
      className="grid grid-cols-4 gap-3 px-3 py-2 border-b border-zinc-800/70"
    >
      {modules.map((mod) => {
        const s = summary?.per_module?.[mod];
        const rate = s?.alignment_rate;
        const consulted = s?.consulted ?? 0;
        let cls = 'text-zinc-500';
        if (rate != null && consulted >= 5) {
          if (rate >= 0.6) cls = 'text-emerald-300';
          else if (rate < 0.4) cls = 'text-rose-300';
          else cls = 'text-amber-300';
        }
        return (
          <div
            key={mod}
            data-testid={`ai-audit-summary-${mod}`}
            className="flex flex-col items-center gap-0.5"
          >
            <div className="text-[11px] uppercase tracking-wider text-zinc-500">
              {MODULE_DISPLAY[mod]}
            </div>
            <div className={`v5-mono text-sm ${cls}`}>{_fmtPct(rate)}</div>
            <div className="text-[11px] text-zinc-600">
              {consulted > 0 ? `n=${consulted}` : 'no data'}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const TradeRow = ({ row }) => {
  const winCls = row.win ? 'text-emerald-400' : 'text-rose-400/80';
  return (
    <div
      data-testid={`ai-audit-row-${row.trade_id}`}
      className="grid grid-cols-12 items-center gap-1 px-3 py-1.5 text-[13px] border-b border-zinc-900/40 last:border-b-0"
    >
      <span className="col-span-2 v5-mono text-zinc-200 truncate">{row.symbol}</span>
      <span className="col-span-2 text-[12px] text-zinc-500 truncate">
        {row.setup_type || '—'}
      </span>
      <span className={`col-span-2 v5-mono text-right ${winCls}`}>
        {_fmtPnl(row.net_pnl)}
      </span>
      {/* Four module pills */}
      {['debate', 'risk_manager', 'institutional', 'time_series'].map((mod) => {
        const pill = _verdictPill(row.modules?.[mod]);
        return (
          <span
            key={mod}
            title={pill.title}
            data-testid={`ai-audit-pill-${row.trade_id}-${mod}`}
            className={`col-span-1 text-center v5-mono text-sm ${pill.cls}`}
          >
            {pill.glyph}
          </span>
        );
      })}
      <span
        className="col-span-2 text-right v5-mono text-[12px] text-zinc-500 truncate"
        title={row.close_reason}
      >
        {row.close_reason || '—'}
      </span>
    </div>
  );
};

export const AIDecisionAuditCard = ({ limit = 20, className = '' }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    try {
      const resp = await safeGet(
        `/api/trading-bot/ai-decision-audit?limit=${limit}`,
        { timeout: 8000 },
      );
      setData(resp);
      setErr(null);
    } catch (e) {
      setErr(e?.message || 'load failed');
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  if (loading && !data) return null;
  if (err) {
    return (
      <div
        data-testid="ai-decision-audit-error"
        className={`px-4 py-2 border border-zinc-800 rounded-md bg-zinc-950/40 text-xs text-zinc-500 ${className}`}
      >
        AI decision audit unavailable: {err}
      </div>
    );
  }
  if (!data) return null;

  const total = data?.summary?.total_trades || 0;
  if (total === 0) {
    return (
      <div
        data-testid="ai-decision-audit-empty"
        className={`px-4 py-2 border border-zinc-800 rounded-md bg-zinc-950/40 text-xs text-zinc-500 ${className}`}
      >
        AI decision audit — no closed trades with consultation data yet.
      </div>
    );
  }

  const visibleRows = expanded ? data.trades : data.trades.slice(0, 8);

  return (
    <div
      data-testid="ai-decision-audit-card"
      className={`border border-zinc-800/70 rounded-lg bg-zinc-950/50 ${className}`}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800/70">
        <div className="flex items-center gap-2 text-zinc-200 text-xs uppercase tracking-wider">
          <Brain className="w-4 h-4 opacity-70" />
          <span>AI decision audit</span>
          <span className="text-[12px] text-zinc-500">
            ({total} trades · win-rate {_fmtPct(data.summary.win_rate)})
          </span>
        </div>
        <button
          data-testid="ai-decision-audit-refresh"
          onClick={load}
          className="text-[12px] text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          refresh
        </button>
      </div>

      <PerModuleStrip summary={data.summary} />

      <div
        data-testid="ai-decision-audit-trade-list"
        className="grid"
      >
        <div className="grid grid-cols-12 gap-1 px-3 py-1 text-[11px] uppercase tracking-wider text-zinc-600 border-b border-zinc-800/40">
          <span className="col-span-2">Sym</span>
          <span className="col-span-2">Setup</span>
          <span className="col-span-2 text-right">PnL</span>
          <span className="col-span-1 text-center">Deb</span>
          <span className="col-span-1 text-center">Risk</span>
          <span className="col-span-1 text-center">Flow</span>
          <span className="col-span-1 text-center">TS</span>
          <span className="col-span-2 text-right">Reason</span>
        </div>
        {visibleRows.map((row) => (
          <TradeRow key={row.trade_id} row={row} />
        ))}
      </div>

      {data.trades.length > 8 && (
        <button
          data-testid="ai-decision-audit-toggle-expand"
          onClick={() => setExpanded((v) => !v)}
          className="w-full text-center py-1.5 text-[12px] text-zinc-500 hover:text-zinc-300 transition-colors border-t border-zinc-800/40"
        >
          {expanded
            ? 'collapse'
            : `show all ${data.trades.length} trades`}
          <ChevronRight
            className={`inline w-3 h-3 ml-1 transition-transform ${
              expanded ? 'rotate-90' : ''
            }`}
          />
        </button>
      )}
    </div>
  );
};

export default AIDecisionAuditCard;
