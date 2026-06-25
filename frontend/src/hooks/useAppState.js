/**
 * useAppState — V6 Plan A→B bridge. Maps the EXISTING /api/system/health
 * payload into the §3 app-state ('cyan' | 'amber' | 'rose') that drives the
 * V6 Heartbeat + TopStrip state pill. Frontend-only (no new backend, no
 * restart): red → rose (CRITICAL), yellow → amber (ELEVATED), green → cyan
 * (NORMAL). Surfaces the non-green subsystems as `reasons`/`detail`.
 *
 * Phase B will swap the source to a dedicated GET /api/safety/system-state
 * (a faithful server-side compute_app_state); the hook contract stays the
 * same so callers don't change.
 */
import { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const POLL_MS = 20_000;

const OVERALL_TO_STATE = { red: 'rose', yellow: 'amber', green: 'cyan' };
const STATE_LABEL = { rose: 'CRITICAL', amber: 'ELEVATED', cyan: 'ALL SYSTEMS' };

export const useAppState = () => {
  const [state, setState] = useState('cyan');
  const [reasons, setReasons] = useState([]);
  const [detail, setDetail] = useState('—');

  const fetchState = useCallback(async () => {
    try {
      const resp = await fetch(`${BACKEND_URL}/api/system/health`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const next = OVERALL_TO_STATE[data.overall] || 'amber';
      const offenders = (data.subsystems || [])
        .filter((s) => s.status !== 'green')
        .map((s) => `${s.name}: ${s.detail || s.status}`);
      setState(next);
      setReasons(offenders);
      const counts = data.counts || {};
      setDetail(
        next === 'cyan'
          ? `${counts.green ?? 0} systems ok`
          : `${counts.red ?? 0} red · ${counts.yellow ?? 0} warn`,
      );
    } catch (e) {
      setState('rose');
      setReasons([`health offline: ${String(e.message || e)}`]);
      setDetail('health offline');
    }
  }, []);

  useEffect(() => {
    fetchState();
    const t = setInterval(fetchState, POLL_MS);
    return () => clearInterval(t);
  }, [fetchState]);

  const stateMeta = {
    cyan:  { color: 'cyan',  icon: '✓', label: STATE_LABEL.cyan,  detail },
    amber: { color: 'amber', icon: '⚠', label: STATE_LABEL.amber, detail },
    rose:  { color: 'rose',  icon: '✕', label: STATE_LABEL.rose,  detail },
  };

  return { state, reasons, detail, stateMeta };
};

export default useAppState;
