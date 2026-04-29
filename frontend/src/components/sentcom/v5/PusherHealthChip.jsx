/**
 * PusherHealthChip — compact always-visible chip showing IB pusher state.
 *
 * Green   = last push within 10s (live market feed healthy)
 * Amber   = last push within 5 min (collection mode / quiet market)
 * Red     = last push > 5 min ago (pusher is gone — Windows box needs attention)
 * Unknown = backend has never received a push this session
 *
 * Hover / focus opens a popover with: subscribed account, quote/position/L2
 * counts, seconds since last push, and collection-mode state.
 *
 * Polls `/api/ib/pusher-health` every 8s. Backend endpoint is read-only and
 * never blocks the event loop.
 */
import React, { useEffect, useState, useCallback } from 'react';
import api from '../../../utils/api';

const fmtAge = (sec) => {
  if (sec == null) return '—';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
};

const HEALTH_CHIP_CLASS = {
  green: 'v5-chip-manage',    // emerald
  amber: 'v5-chip-close',     // amber
  red: 'v5-chip-veto',        // rose
  unknown: 'v5-chip-close',   // neutral amber
};

const HEALTH_LABEL = {
  green: 'LIVE',
  amber: 'SLOW',
  red: 'DOWN',
  unknown: '—',
};

export const PusherHealthChip = () => {
  const [data, setData] = useState(null);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await api.get('/api/ib/pusher-health');
      if (res?.data?.success) setData(res.data);
    } catch {
      // Swallow — chip will show DOWN after TTL if backend is unreachable
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const t = setInterval(fetchHealth, 8000);
    return () => clearInterval(t);
  }, [fetchHealth]);

  if (!data) return null;

  const chipClass = HEALTH_CHIP_CLASS[data.health] || 'v5-chip-close';
  const label = HEALTH_LABEL[data.health] || '—';
  const ageStr = fmtAge(data.age_seconds);

  return (
    <span className="v5-hover-wrap" data-testid="v5-pusher-health-chip-wrap" tabIndex={0}>
      <span className={`v5-chip ${chipClass}`} data-testid="v5-pusher-health-chip">
        Pusher {label}
        {data.health === 'green' || data.health === 'amber' ? (
          <span className="ml-1 opacity-70 v5-mono text-[11px]">· {ageStr}</span>
        ) : null}
      </span>

      <div className="v5-hover-panel" role="tooltip">
        <div className="row">
          <span className="k">State</span>
          <span className={`v ${data.health === 'green' ? 'match' : data.health === 'red' ? 'miss' : ''}`}>
            {data.health.toUpperCase()}{data.connected ? '' : ' (disconnected)'}
          </span>
        </div>
        <div className="row">
          <span className="k">Last push</span>
          <span className="v">{ageStr} ago</span>
        </div>
        <hr />
        <div className="row">
          <span className="k">Account</span>
          <span className="v">{data.subscribed_account || <span className="v5-dim">—</span>}</span>
        </div>
        <div className="row">
          <span className="k">Quotes</span>
          <span className="v">{data.counts?.quotes ?? 0} symbols</span>
        </div>
        <div className="row">
          <span className="k">Positions</span>
          <span className="v">{data.counts?.positions ?? 0}</span>
        </div>
        {data.counts?.level2_symbols > 0 && (
          <div className="row">
            <span className="k">Level 2</span>
            <span className="v">{data.counts.level2_symbols} symbols</span>
          </div>
        )}
        {data.collection_mode?.active && (
          <>
            <hr />
            <div className="row">
              <span className="k">Collection</span>
              <span className="v">{data.collection_mode.completed.toLocaleString()} done · {data.collection_mode.failed} failed</span>
            </div>
            <div className="row">
              <span className="k">Rate</span>
              <span className="v">{Math.round(data.collection_mode.rate_per_hour || 0).toLocaleString()}/hr</span>
            </div>
            <div className="row">
              <span className="k">Elapsed</span>
              <span className="v">{Math.round(data.collection_mode.elapsed_minutes || 0)}m</span>
            </div>
          </>
        )}
        {data.health === 'red' && (
          <>
            <hr />
            <div className="reason">
              Last push {ageStr} ago. Check the Windows pusher terminal — IB Gateway may have dropped the connection.
            </div>
          </>
        )}
      </div>
    </span>
  );
};

export default PusherHealthChip;
