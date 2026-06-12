/**
 * IntegrityCardV5 — v333 "System Integrity" briefing surfaces.
 *
 * Exports:
 *   useIntegrityReport — shared polling hook (morning-report + feed)
 *   IntegrityBody      — checklist + integrity feed (regime demotions
 *                        with before/after stops); used by the briefing
 *                        deep-dive modal (briefingKey="integrity")
 *   IntegrityCardV5    — compact always-on card for the BriefingsV5 panel
 *
 * Backend: GET /api/integrity/morning-report + GET /api/integrity/feed.
 * A live pass/fail scorecard proving the pipeline fixes are holding —
 * scalp count, data uptime, ingest freshness, daily-bar leak (v328),
 * RTH backfill gate, M0 ladder fills, regime + demotions (v332).
 */
import React, { useEffect, useState, useCallback } from 'react';
import api from '../../../utils/api';

const STATUS_STYLE = {
  pass: 'text-emerald-400',
  warn: 'text-amber-400',
  fail: 'text-rose-400',
  info: 'text-zinc-500',
};

const STATUS_ICON = { pass: '✓', warn: '!', fail: '✗', info: '·' };

const CHECK_LABEL = {
  scalps_fired: 'Scalps fired',
  data_uptime: 'Data uptime',
  ingest_freshness: 'Ingest freshness',
  daily_bar_leak: 'Daily-bar leak',
  backfill_gate: 'Backfill gate',
  m0_ladder: 'M0 ladder',
  regime: 'Regime',
  integrity_events: 'Integrity events',
};

const fmtFeedTs = (ts) => {
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', hour12: true,
    });
  } catch {
    return '';
  }
};

export const useIntegrityReport = ({ enabled = true, refreshMs = 60000 } = {}) => {
  const [report, setReport] = useState(null);
  const [feed, setFeed] = useState([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      const [rep, fd] = await Promise.allSettled([
        api.get('/api/integrity/morning-report', { timeout: 12000 }),
        api.get('/api/integrity/feed?limit=15', { timeout: 12000 }),
      ]);
      if (rep.status === 'fulfilled' && rep.value.data?.success) setReport(rep.value.data);
      if (fd.status === 'fulfilled' && fd.value.data?.success) setFeed(fd.value.data.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    reload();
    if (!refreshMs) return undefined;
    const id = setInterval(reload, refreshMs);
    return () => clearInterval(id);
  }, [enabled, refreshMs, reload]);

  return { report, feed, loading, reload };
};

const Checklist = ({ checks }) => (
  <div className="space-y-1 text-[13px]" data-testid="integrity-checklist">
    {(checks || []).map((c) => (
      <div key={c.name} className="flex justify-between gap-3">
        <span className="text-zinc-400 min-w-0">
          <span className={`v5-mono ${STATUS_STYLE[c.status] || 'text-zinc-500'}`}>
            {STATUS_ICON[c.status] || '·'}
          </span>{' '}
          {CHECK_LABEL[c.name] || c.name}
          {c.detail && <span className="text-zinc-600"> — {c.detail}</span>}
        </span>
        <span className={`whitespace-nowrap v5-mono ${STATUS_STYLE[c.status] || 'text-zinc-400'}`}>
          {c.value}
        </span>
      </div>
    ))}
  </div>
);

const FeedList = ({ feed, maxHeight = 'max-h-56' }) => (
  <div className={`${maxHeight} overflow-y-auto v5-scroll space-y-0.5 text-[13px]`} data-testid="integrity-feed">
    {feed.length === 0 && <div className="text-zinc-600">No integrity events recorded.</div>}
    {feed.map((it, i) => (
      <div key={`${it.ts}-${i}`} className="flex gap-2">
        <span className="v5-mono text-zinc-600 whitespace-nowrap">{fmtFeedTs(it.ts)}</span>
        <span className={
          it.severity === 'high' ? 'text-rose-400'
            : it.severity === 'medium' ? 'text-amber-400' : 'text-zinc-400'
        }>
          {it.text}
        </span>
      </div>
    ))}
  </div>
);

/** Full deep-dive body — rendered inside the briefing modal. */
export const IntegrityBody = () => {
  const { report, feed, loading } = useIntegrityReport({ refreshMs: 60000 });
  const verdict = report?.verdict;
  const verdictCls = verdict === 'PASS' ? 'v5-up' : verdict === 'WARN' ? 'v5-warn' : 'v5-down';

  return (
    <section data-testid="briefing-section-integrity" className="border-t border-zinc-800">
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-900 bg-zinc-950/40">
        <div className="v5-mono text-[13px] font-bold tracking-widest uppercase text-cyan-400">
          System Integrity
        </div>
        {verdict && (
          <span data-testid="integrity-verdict" className={`v5-mono text-xs font-bold ${verdictCls}`}>
            {verdict} {report?.score}
          </span>
        )}
      </div>
      <div className="px-4 py-3 space-y-3">
        {loading && !report && <div className="text-zinc-500 text-[13px]">Loading…</div>}
        {!loading && !report && (
          <div className="text-zinc-500 text-[13px]">Integrity endpoint unavailable.</div>
        )}
        {report && <Checklist checks={report.checks} />}
        <div>
          <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wider mb-1">
            Integrity feed — automatic risk actions (regime demotions show before → after stops)
          </div>
          <FeedList feed={feed} />
        </div>
      </div>
    </section>
  );
};

/** Compact always-on card for the BriefingsV5 4-card panel. */
export const IntegrityCardV5 = ({ expanded, onToggle }) => {
  const { report, feed, loading } = useIntegrityReport({ refreshMs: 60000 });
  const verdict = report?.verdict;
  const verdictCls = verdict === 'PASS' ? 'v5-up' : verdict === 'WARN' ? 'v5-warn' : 'v5-down';

  return (
    <div data-testid="v5-briefing-integrity" className="v5-briefing-card" onClick={onToggle}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="v5-mono font-bold text-xs text-cyan-400">SYSTEM INTEGRITY</span>
          {verdict && (
            <span className={`v5-mono text-xs font-bold ${verdictCls}`}>
              {verdict} {report?.score}
            </span>
          )}
        </div>
        <span className="v5-mono text-[14px] v5-dim">live · 60s</span>
      </div>
      <div className="v5-why mt-1" data-testid="integrity-summary">
        {loading && !report && <span className="text-zinc-500">Loading…</span>}
        {!loading && !report && <span className="text-zinc-500">Integrity endpoint unavailable.</span>}
        {report && (
          <>
            <span>{report.scalps_today} scalps</span>
            {report.uptime_pct != null && (
              <span> · data <span className={report.uptime_pct >= 80 ? 'v5-up' : report.uptime_pct >= 40 ? 'v5-warn' : 'v5-down'}>{report.uptime_pct}%</span></span>
            )}
            <span> · leaks <span className={report.leaked_daily_bars === 0 ? 'v5-up' : 'v5-down'}>{report.leaked_daily_bars}</span></span>
            {report.demotions_today > 0 && (
              <span> · <span className="v5-warn">{report.demotions_today} demotion{report.demotions_today > 1 ? 's' : ''}</span></span>
            )}
          </>
        )}
      </div>
      {expanded && report && (
        <div className="mt-2 pt-2 border-t border-zinc-800" onClick={(e) => e.stopPropagation()}>
          <Checklist checks={report.checks} />
          {feed.length > 0 && (
            <div className="pt-1 mt-1 border-t border-zinc-800/60">
              <div className="text-zinc-500 text-[12px] mb-0.5">Integrity feed</div>
              <FeedList feed={feed} maxHeight="max-h-32" />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default IntegrityCardV5;
