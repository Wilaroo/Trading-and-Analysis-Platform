/**
 * ConnectivityCheck — one-click V5 upstream-dependency smoke test.
 *
 * Pings every REST endpoint the V5 Command Center depends on (in parallel
 * via Promise.allSettled) and inspects the freshness of every WebSocket
 * stream we expect to see. Shows a drawer with green/amber/red status per
 * channel, latency, and a one-line summary of what it saw.
 *
 * Purely read-only — safe to run at any time, including during the
 * multi-hour training subprocess. No endpoints mutate anything.
 *
 * Entry point: a tiny chip in the V5 HUD. Overall color is the worst
 * single-channel color (red beats amber beats green).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, RefreshCw, ChevronDown, X } from 'lucide-react';
import api from '../../../utils/api';
import { useWsData } from '../../../contexts/WebSocketDataContext';

const CHANNELS = [
  {
    id: 'pusher',
    name: 'IB Pusher (Windows)',
    url: '/api/ib/pusher-health',
    assess: (d) => {
      if (!d?.success) return ['fail', 'backend returned no success flag'];
      if (d.health === 'green') return ['ok', `LIVE · ${d.counts?.quotes ?? 0} quotes · last push ${d.age_seconds}s ago`];
      if (d.health === 'amber') return ['warn', `SLOW · last push ${d.age_seconds}s ago`];
      if (d.health === 'red') return ['fail', `DOWN · last push ${d.age_seconds}s ago`];
      return ['warn', 'no pushes received yet this session'];
    },
  },
  {
    id: 'safety',
    name: 'Safety + Account Guard',
    url: '/api/safety/status',
    assess: (d) => {
      const guard = d?.account_guard;
      const cfg = d?.config;
      const st = d?.state;
      if (!guard || !cfg) return ['fail', 'missing account_guard or config'];
      if (st?.kill_switch_active) return ['warn', `kill-switch LATCHED · ${st?.kill_switch_reason || 'reason unknown'}`];
      if (!guard.match) return ['fail', `account MISMATCH — current "${guard.current_account_id}" not in expected aliases`];
      return ['ok', `${(guard.active_mode || 'paper').toUpperCase()} · ${guard.current_account_id || 'unknown'} · cap $${cfg.max_daily_loss_usd}`];
    },
  },
  {
    id: 'portfolio',
    name: 'Portfolio',
    url: '/api/portfolio',
    assess: (d) => {
      const positions = d?.positions ?? d?.data?.positions ?? [];
      const equity = d?.account?.net_liquidation ?? d?.data?.account?.net_liquidation ?? null;
      if (!d) return ['fail', 'empty response'];
      const nPos = Array.isArray(positions) ? positions.length : 0;
      return ['ok', `${nPos} open position${nPos === 1 ? '' : 's'}${equity != null ? ` · equity $${Number(equity).toLocaleString()}` : ''}`];
    },
  },
  {
    id: 'bot',
    name: 'Trading Bot',
    url: '/api/trading-bot/status',
    assess: (d) => {
      if (!d) return ['fail', 'empty response'];
      const running = d.running ?? d.is_running ?? d.status === 'running';
      const mode = d.mode || d.account_mode || '—';
      if (running) return ['ok', `RUNNING · mode ${mode}`];
      return ['warn', `IDLE · mode ${mode} (expected during training)`];
    },
  },
  {
    id: 'scanner',
    name: 'Live Scanner',
    url: '/api/live-scanner/status',
    assess: (d) => {
      if (!d) return ['fail', 'empty response'];
      const running = d.is_running ?? d.running ?? false;
      const cycles = d.cycles ?? d.scan_count ?? 0;
      if (running) return ['ok', `SCANNING · ${cycles} cycles`];
      return ['warn', 'IDLE (scanner paused — expected during training)'];
    },
  },
  {
    id: 'sentcom',
    name: 'SentCom Drift Feed',
    url: '/api/sentcom/drift',
    assess: (d) => {
      if (!d) return ['fail', 'empty response'];
      // Endpoint returns a list or object of drift entries — just prove it deserialized.
      const n = Array.isArray(d) ? d.length : (d.entries?.length ?? d.count ?? 0);
      return ['ok', `drift feed online · ${n} entries`];
    },
  },
  {
    id: 'market_context',
    name: 'Market Context / Session',
    url: '/api/market-context/session/status',
    assess: (d) => {
      if (!d) return ['fail', 'empty response'];
      const phase = d.session || d.phase || d.status || '—';
      return ['ok', `session ${phase}`];
    },
  },
  {
    id: 'queue',
    name: 'Collection Queue',
    url: '/api/ib-collector/queue-progress-detailed',
    assess: (d) => {
      if (!d?.success) return ['fail', 'queue-progress call failed'];
      const o = d.overall || {};
      const pending = o.pending ?? 0;
      const failed = o.failed ?? 0;
      const completed = o.completed ?? 0;
      if (failed > 100) return ['warn', `${completed.toLocaleString()} done · ${pending.toLocaleString()} pending · ${failed.toLocaleString()} FAILED (check DLQ)`];
      return ['ok', `${completed.toLocaleString()} done · ${pending.toLocaleString()} pending · ${failed} failed`];
    },
  },
];

// Small helper — turns a ws `lastUpdate` age into a status.
const wsStatus = (lastMs, staleSec) => {
  if (!lastMs) return ['warn', 'never received'];
  const ageSec = Math.floor((Date.now() - lastMs) / 1000);
  if (ageSec <= staleSec) return ['ok', `last msg ${ageSec}s ago`];
  if (ageSec <= staleSec * 6) return ['warn', `stale · last msg ${ageSec}s ago`];
  return ['fail', `DEAD · last msg ${ageSec}s ago`];
};

const STATUS_META = {
  ok: { dot: 'bg-emerald-400', text: 'text-emerald-300', border: 'border-emerald-500/20' },
  warn: { dot: 'bg-amber-400', text: 'text-amber-300', border: 'border-amber-500/20' },
  fail: { dot: 'bg-rose-500', text: 'text-rose-300', border: 'border-rose-500/30' },
  pending: { dot: 'bg-zinc-600', text: 'text-zinc-500', border: 'border-zinc-700' },
};

const ROLLUP = { ok: 0, warn: 1, fail: 2, pending: 0 };
const rollupStatus = (results) => {
  let worst = 'ok';
  for (const r of results) {
    if ((ROLLUP[r.status] ?? 0) > (ROLLUP[worst] ?? 0)) worst = r.status;
  }
  return worst;
};

const runCheck = async (ch) => {
  const t0 = performance.now();
  try {
    const res = await api.get(ch.url, { timeout: 8000 });
    const dt = Math.round(performance.now() - t0);
    const [status, summary] = ch.assess(res?.data);
    return { id: ch.id, name: ch.name, status, summary, latency_ms: dt, url: ch.url };
  } catch (err) {
    const dt = Math.round(performance.now() - t0);
    const detail = err?.response?.data?.detail || err?.message || 'unknown error';
    return { id: ch.id, name: ch.name, status: 'fail', summary: `request failed — ${detail}`, latency_ms: dt, url: ch.url };
  }
};

export const ConnectivityCheck = () => {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState([]);
  const [wsResults, setWsResults] = useState([]);
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState(null);
  const ran = useRef(false);
  const ws = useWsData();

  const runAll = useCallback(async () => {
    setRunning(true);
    // Seed placeholder rows so the drawer renders the right shape immediately
    setResults(CHANNELS.map(c => ({ id: c.id, name: c.name, status: 'pending', summary: 'checking…', latency_ms: null, url: c.url })));
    const out = await Promise.all(CHANNELS.map(runCheck));
    setResults(out);
    setLastRun(new Date());

    // Sample the WS freshness NOW (these update continuously so they don't
    // need to be "awaited")
    const lu = ws?.lastUpdate || {};
    const wsChecks = [
      { id: 'ws_quotes',   name: 'WS · quotes',         status: null, sec: 15 },
      { id: 'ws_ib',       name: 'WS · ib_status',      status: null, sec: 30 },
      { id: 'ws_sentcom',  name: 'WS · sentcomStream',  status: null, sec: 60 },
      { id: 'ws_training', name: 'WS · training_status',status: null, sec: 120 },
    ].map(c => {
      const key = c.id.replace('ws_', '');
      // WS dispatch-keys vary — look up a few common spellings
      const lastMs = lu[key] || lu[c.id] || lu[key.replace('_', '')] || null;
      const [status, summary] = wsStatus(lastMs, c.sec);
      return { ...c, status, summary };
    });
    setWsResults(wsChecks);
    setRunning(false);
  }, [ws]);

  // Kick off once when the drawer is mounted / opened the first time
  useEffect(() => {
    if (open && !ran.current) {
      ran.current = true;
      runAll();
    }
  }, [open, runAll]);

  const overall = useMemo(() => rollupStatus([...results, ...wsResults]), [results, wsResults]);
  const meta = STATUS_META[overall];

  const counts = useMemo(() => {
    const all = [...results, ...wsResults];
    return {
      ok: all.filter(r => r.status === 'ok').length,
      warn: all.filter(r => r.status === 'warn').length,
      fail: all.filter(r => r.status === 'fail').length,
    };
  }, [results, wsResults]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`v5-chip flex items-center gap-1 ${
          overall === 'ok' ? 'v5-chip-manage' :
          overall === 'warn' ? 'v5-chip-close' :
          overall === 'fail' ? 'v5-chip-veto' : 'v5-chip-close'
        }`}
        data-testid="v5-connectivity-chip"
        title="Run V5 connectivity check"
      >
        <Activity className="w-2.5 h-2.5" />
        <span>Wires</span>
        {counts.fail > 0 && <span className="ml-1 v5-mono text-[11px]">· {counts.fail} fail</span>}
        {counts.fail === 0 && counts.warn > 0 && <span className="ml-1 v5-mono text-[11px]">· {counts.warn} warn</span>}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[62] bg-black/70 backdrop-blur-sm flex items-start justify-center pt-20 px-4"
          onClick={() => setOpen(false)}
          data-testid="v5-connectivity-drawer"
        >
          <div
            className="w-full max-w-2xl rounded-xl bg-zinc-950 border border-white/10 overflow-hidden shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-gradient-to-r from-zinc-900 to-zinc-950">
              <div className="flex items-center gap-2.5">
                <div className={`w-2 h-2 rounded-full ${meta.dot} ${overall === 'ok' ? 'shadow-[0_0_8px_currentColor]' : ''}`} />
                <div>
                  <div className="text-sm font-bold text-white tracking-tight">V5 Connectivity Check</div>
                  <div className="text-[12px] text-zinc-500">
                    {lastRun
                      ? `Last run ${lastRun.toLocaleTimeString()} · ${counts.ok} ok · ${counts.warn} warn · ${counts.fail} fail`
                      : 'Running initial pass…'}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={runAll}
                  disabled={running}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-white/5 hover:bg-white/10 text-[13px] text-zinc-300 border border-white/10 transition-colors disabled:opacity-50"
                  data-testid="v5-connectivity-rerun"
                >
                  <RefreshCw className={`w-3 h-3 ${running ? 'animate-spin' : ''}`} />
                  Re-run
                </button>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="p-1.5 rounded-md text-zinc-500 hover:text-white hover:bg-white/5"
                  data-testid="v5-connectivity-close"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="max-h-[70vh] overflow-y-auto v5-scroll">
              <ConnectivityGroup title="REST endpoints" rows={results} />
              <ConnectivityGroup title="WebSocket streams" rows={wsResults} />
              <div className="px-4 py-3 text-[12px] text-zinc-600 border-t border-white/5 bg-zinc-950/60">
                Read-only pings. Training and collection are not affected by this check.
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

const ConnectivityGroup = ({ title, rows }) => {
  if (!rows || rows.length === 0) return null;
  return (
    <div className="px-4 pt-3 pb-1">
      <div className="flex items-center gap-2 mb-2">
        <ChevronDown className="w-3 h-3 text-zinc-600" />
        <span className="text-[12px] font-semibold text-zinc-400 uppercase tracking-widest">{title}</span>
        <span className="text-[12px] text-zinc-600 v5-mono">· {rows.length}</span>
      </div>
      <div className="space-y-1">
        {rows.map((r) => {
          const m = STATUS_META[r.status] || STATUS_META.pending;
          return (
            <div
              key={r.id}
              className={`flex items-center gap-3 px-2.5 py-1.5 rounded-md border ${m.border} bg-white/[0.015] hover:bg-white/[0.04] transition-colors`}
              data-testid={`v5-connectivity-row-${r.id}`}
            >
              <div className={`w-2 h-2 rounded-full ${m.dot} shrink-0`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-zinc-200 truncate">{r.name}</span>
                  {r.latency_ms != null && (
                    <span className="text-[11px] text-zinc-500 v5-mono shrink-0">{r.latency_ms}ms</span>
                  )}
                </div>
                <div className={`text-[12px] ${m.text} truncate`} title={r.summary}>
                  {r.summary}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ConnectivityCheck;
