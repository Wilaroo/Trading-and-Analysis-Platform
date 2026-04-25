/**
 * DataFreshnessBadge — compact "how fresh is the data I'm looking at?" chip.
 *
 * Why this exists:
 * ---------------
 * The TradeCommand/SentCom app has multiple data surfaces (charts, scanner,
 * briefings, modal, trade journal, AI chat). Each one can be fed by a
 * different pipe — the IB pusher (live ticks), the on-demand pusher RPC
 * (Phase 1+), or the historical `ib_historical_data` backfill (1+ day old).
 * It's easy to end up staring at a 5-week-stale chart without realising it
 * (we did exactly that 2026-03-17 → 2026-04-24). This badge surfaces the
 * answer globally: one glance tells you whether the app is fresh or lying.
 *
 * Data sources (today):
 *   GET /api/ib/pusher-health           → live tick freshness (pusher age)
 *   GET /api/ib-collector/universe-freshness-health
 *                                       → historical-queue freshness
 *
 * When Phase 1 of the live-data architecture lands, this component will
 * also surface `live_bar_cache` TTL state per active-view symbol.
 *
 * Status states (traffic-light + label):
 *   LIVE · Ns ago      — pusher green, <10s age
 *   CACHED · Nm ago    — pusher amber or within reasonable window
 *   STALE · <reason>   — red, needs attention
 *   MARKET CLOSED      — neutral, shows last close day
 *   UNKNOWN            — pusher never sent / backend unreachable
 *
 * Deliberately does NOT auto-poll more than once every 10s. This is a
 * status chip, not a real-time feed.
 *
 * Click behaviour:
 *   Clicking the badge opens the FreshnessInspector modal, revealing
 *   per-subsystem health, live subscriptions, cache TTL plan, and
 *   pusher RPC state. This makes the badge a true "command entry
 *   point" — one glance shows status, one click reveals why.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { FreshnessInspector } from './sentcom/v5/FreshnessInspector';

const API = process.env.REACT_APP_BACKEND_URL;
const POLL_MS = 10_000;

// Simple ET market-hours gate — good enough for a status chip. Full holiday
// calendar lives in the backend; don't duplicate it here.
const marketState = () => {
  try {
    const etNow = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
    const day = etNow.getDay(); // 0 Sun, 6 Sat
    if (day === 0 || day === 6) return 'weekend';
    const minutes = etNow.getHours() * 60 + etNow.getMinutes();
    const open = 9 * 60 + 30;
    const close = 16 * 60;
    const premktOpen = 4 * 60;
    const postmktClose = 20 * 60;
    if (minutes >= open && minutes < close) return 'rth';
    if (minutes >= premktOpen && minutes < open) return 'pre';
    if (minutes >= close && minutes < postmktClose) return 'post';
    return 'overnight';
  } catch {
    return 'rth';
  }
};

const formatAge = (secs) => {
  if (secs == null || !Number.isFinite(secs)) return '—';
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
};

export const DataFreshnessBadge = () => {
  const [pusher, setPusher] = useState(null);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [err, setErr] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API}/api/ib/pusher-health`, {
          credentials: 'include',
        });
        if (!res.ok) throw new Error('bad status');
        const j = await res.json();
        if (!alive) return;
        setPusher(j);
        setFetchedAt(Date.now());
        setErr(false);
      } catch {
        if (!alive) return;
        setErr(true);
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const mkt = marketState();
  const { label, tone, title } = useMemo(() => {
    if (err && !pusher) {
      return {
        label: 'UNREACHABLE',
        tone: 'red',
        title: 'Backend not reachable — check DGX connectivity.',
      };
    }
    if (!pusher) {
      return { label: '…', tone: 'grey', title: 'Loading pusher health…' };
    }
    const { health, age_seconds } = pusher;
    if (health === 'unknown') {
      return {
        label: 'NO PUSH YET',
        tone: 'grey',
        title: 'Backend is up but has never received a push from the Windows pusher. Start ib_data_pusher.py.',
      };
    }
    if (health === 'green') {
      return {
        label: `LIVE · ${formatAge(age_seconds)}`,
        tone: 'green',
        title: `Pusher feeding backend normally (${age_seconds}s ago). Market state: ${mkt}.`,
      };
    }
    if (health === 'amber') {
      // Amber during RTH is a warning; outside RTH it's normal.
      if (mkt === 'rth') {
        return {
          label: `DELAYED · ${formatAge(age_seconds)}`,
          tone: 'amber',
          title: `Pusher last fed ${age_seconds}s ago during market hours — expected <10s. Check Windows pusher.`,
        };
      }
      return {
        label: mkt === 'weekend'
          ? 'WEEKEND · CLOSED'
          : mkt === 'overnight' ? 'OVERNIGHT · QUIET' : 'EXT HOURS',
        tone: 'grey',
        title: `Pusher quiet (${age_seconds}s ago) — normal for ${mkt}. Last session close shown.`,
      };
    }
    // red
    return {
      label: mkt === 'rth' ? 'STALE · PUSHER DOWN' : 'STALE · LAST CLOSE',
      tone: mkt === 'rth' ? 'red' : 'amber',
      title: `Pusher hasn't pushed in ${formatAge(age_seconds)}. ${mkt === 'rth'
        ? 'During market hours this is a failure — restart ib_data_pusher.py on Windows.'
        : 'Expected outside market hours; data you see is from last session close.'}`,
    };
  }, [pusher, err, mkt]);

  const toneClasses = {
    green: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
    red:   'bg-rose-500/10 text-rose-300 border-rose-500/30',
    grey:  'bg-zinc-800/60 text-zinc-400 border-zinc-700',
  }[tone] || 'bg-zinc-800/60 text-zinc-400 border-zinc-700';

  const dotClasses = {
    green: 'bg-emerald-400 animate-pulse',
    amber: 'bg-amber-400',
    red:   'bg-rose-400 animate-pulse',
    grey:  'bg-zinc-500',
  }[tone] || 'bg-zinc-500';

  return (
    <>
      <button
        type="button"
        data-testid="data-freshness-badge"
        data-help-id="data-freshness-badge"
        title={`${title}\n\nClick for details.`}
        onClick={() => setInspectorOpen(true)}
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-[10px] font-mono uppercase tracking-wider select-none transition-colors hover:brightness-125 cursor-pointer ${toneClasses}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${dotClasses}`} />
        <span>{label}</span>
        {fetchedAt && (
          <span className="opacity-40 ml-1 hidden sm:inline">
            · {Math.max(0, Math.floor((Date.now() - fetchedAt) / 1000))}s
          </span>
        )}
      </button>
      <FreshnessInspector
        isOpen={inspectorOpen}
        onClose={() => setInspectorOpen(false)}
      />
    </>
  );
};

export default DataFreshnessBadge;
