/**
 * ClosedTradesPreview — v19.34.177
 *
 * Isolated harness for the portable ClosedTradesTable, reachable ONLY at
 * ?preview=closedfeed. It self-fetches the new GET /api/sentcom/closed-trades
 * endpoint (range-switchable + 15s live refresh to demonstrate background
 * updates) and is NOT mounted anywhere in the live app tree — so it has zero
 * effect on the running command center.
 */
import React, { useCallback, useEffect, useState } from 'react';
import ClosedTradesTable from '../v5/ClosedTradesTable';

const API = process.env.REACT_APP_BACKEND_URL || '';

const ClosedTradesPreview = () => {
  const [range, setRange] = useState('today');
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [lastFetch, setLastFetch] = useState(null);

  const load = useCallback(async (r) => {
    try {
      const res = await fetch(`${API}/api/sentcom/closed-trades?range=${r}`);
      const data = await res.json();
      if (data && data.success) {
        setTrades(data.trades || []);
        setSummary(data.summary || {});
        setLastFetch(new Date());
      }
    } catch (e) {
      // swallow — preview harness only
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load(range);
    const id = setInterval(() => load(range), 15000); // live background refresh
    return () => clearInterval(id);
  }, [range, load]);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans p-4" data-testid="closed-feed-preview">
      <div className="max-w-[1200px] mx-auto">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h1 className="text-sm font-bold tracking-[0.18em] uppercase text-zinc-200">
              Closed Trades Feed <span className="text-zinc-600">· preview</span>
            </h1>
            <p className="text-[11px] text-zinc-500 font-mono mt-1">
              Portable component · /api/sentcom/closed-trades · deduped from bot_trades · 15s live refresh
            </p>
          </div>
          <span className="text-[10px] font-mono text-zinc-600">
            {lastFetch ? `updated ${lastFetch.toLocaleTimeString('en-US', { hour12: false })}` : '…'}
          </span>
        </div>
        <div className="border border-zinc-800 rounded-md bg-zinc-900/40 h-[78vh]">
          <ClosedTradesTable
            trades={trades}
            summary={summary}
            range={range}
            loading={loading}
            onRangeChange={setRange}
            onRowClick={(t) => console.log('row click → bracket history for', t.symbol, t.trade_id)}
          />
        </div>
      </div>
    </div>
  );
};

export default ClosedTradesPreview;
