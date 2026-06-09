/**
 * CostBasisSyncTile — V5 status-strip tile that wires the
 * `/api/trading-bot/sync-entry-prices` endpoint into a one-click
 * operator action.
 *
 * What it does:
 *   • Runs a `dry_run=true` sync on mount + every 60s → shows how
 *     many bot entry_prices are drifting from IB's avgCost.
 *   • Click [Sync Now] → fires the real (mutating) sync.
 *   • Renders compact: drift count + worst symbol + last-sync stamp.
 *
 * 2026-02-13 v19.34.152
 */
import React, { useEffect, useState, useCallback } from 'react';
import { RefreshCcw, AlertCircle, CheckCircle2 } from 'lucide-react';
import api from '../../../utils/api';
import { toast } from 'sonner';

const POLL_MS = 60000;

const fmtRelative = (iso) => {
  if (!iso) return 'never';
  try {
    const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
  } catch { return 'unknown'; }
};

export const CostBasisSyncTile = ({ onStatus }) => {
  const [audit, setAudit] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [lastSyncAt, setLastSyncAt] = useState(null);

  const fetchAudit = useCallback(async () => {
    try {
      const res = await api.post('/api/trading-bot/sync-entry-prices', {
        dry_run: true,
      });
      if (res?.data?.success !== false) setAudit(res.data);
    } catch (e) {
      setAudit({ success: false, error: e?.message || 'request failed' });
    }
  }, []);

  useEffect(() => {
    fetchAudit();
    const id = setInterval(fetchAudit, POLL_MS);
    return () => clearInterval(id);
  }, [fetchAudit]);

  const handleSync = async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      const res = await api.post('/api/trading-bot/sync-entry-prices', {
        dry_run: false,
      });
      if (res?.data?.success === false) {
        toast.error(`Sync failed: ${res.data.error || 'unknown'}`);
      } else {
        const n = res?.data?.synced_count ?? res?.data?.summary?.synced ?? 0;
        toast.success(`Cost-basis sync: ${n} trade(s) updated`);
        setLastSyncAt(new Date().toISOString());
        fetchAudit();  // refresh the audit display
      }
    } catch (e) {
      toast.error(`Sync request failed: ${e?.message || e}`);
    } finally {
      setSyncing(false);
    }
  };

  // Robust to varying field names across versions of the endpoint.
  const driftCount =
    audit?.drift_count
    ?? audit?.summary?.would_sync
    ?? audit?.synced_count
    ?? (Array.isArray(audit?.rows)
      ? audit.rows.filter((r) => r.would_sync || r.drift_per_share).length
      : 0);
  const worstSymbol =
    audit?.worst_symbol
    ?? audit?.summary?.worst_symbol
    ?? (Array.isArray(audit?.rows) && audit.rows.length
      ? audit.rows.reduce((best, r) => {
        const cur = Math.abs(r.drift_per_share ?? 0);
        return cur > (best.cur ?? 0) ? { sym: r.symbol, cur } : best;
      }, {}).sym
      : null);

  const isClean = driftCount === 0;
  useEffect(() => {
    onStatus?.(audit?.success === false ? 'unknown' : (isClean ? 'green' : 'amber'));
  }, [onStatus, isClean, audit]);
  const palette = isClean
    ? 'text-emerald-300 border-emerald-500/30'
    : 'text-amber-300 border-amber-500/30';

  return (
    <div
      data-testid="cost-basis-sync-tile"
      className="flex items-center gap-2 px-3 py-1 bg-zinc-950/60 text-[14px] leading-none whitespace-nowrap"
    >
      {isClean ? (
        <CheckCircle2 className="w-3 h-3 text-emerald-500" />
      ) : (
        <AlertCircle className="w-3 h-3 text-amber-400" />
      )}
      <span
        data-testid="cost-basis-sync-drift-count"
        className={`px-1.5 py-0.5 rounded text-[13px] font-bold tracking-wider border ${palette}`}
        title={
          audit?.error
            ? `Error: ${audit.error}`
            : `Last audit refresh: ${fmtRelative(audit?.generated_at)}`
        }
      >
        COST-BASIS {isClean ? 'OK' : `${driftCount} DRIFT`}
      </span>

      {!isClean && worstSymbol && (
        <span className="text-zinc-500 v5-mono" title="Worst-drift symbol">
          worst: <span className="text-zinc-200 font-bold">{worstSymbol}</span>
        </span>
      )}

      <button
        data-testid="cost-basis-sync-now-btn"
        onClick={handleSync}
        disabled={syncing || isClean}
        className={`ml-1 flex items-center gap-1 px-2 py-0.5 rounded border transition-opacity ${
          syncing
            ? 'opacity-50 cursor-not-allowed border-zinc-700 text-zinc-500'
            : isClean
              ? 'opacity-40 cursor-not-allowed border-zinc-700 text-zinc-500'
              : 'border-amber-500/40 text-amber-200 hover:bg-amber-500/15'
        }`}
        title={isClean ? 'No drift to sync' : 'Snap bot entry_price → IB avgCost'}
      >
        <RefreshCcw className={`w-3 h-3 ${syncing ? 'animate-spin' : ''}`} />
        <span className="text-[12px] font-bold tracking-wider">
          {syncing ? 'SYNCING…' : 'SYNC NOW'}
        </span>
      </button>

      {lastSyncAt && (
        <span
          className="text-zinc-600 text-[12px]"
          title={`Last manual sync: ${lastSyncAt}`}
        >
          {fmtRelative(lastSyncAt)}
        </span>
      )}
    </div>
  );
};

export default CostBasisSyncTile;
