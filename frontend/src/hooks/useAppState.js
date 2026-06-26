/**
 * useAppState — V6 §3 app-state ('cyan' | 'amber' | 'rose') that drives the
 * V6 Heartbeat + TopStrip state pill + CRITICAL action bar.
 *
 * Phase B (2026-06-26): now polls the dedicated server-side
 * `GET /api/safety/system-state` (faithful compute_app_state). If that endpoint
 * is unavailable (older backend), it transparently FALLS BACK to mapping
 * `/api/system/health` (red→rose, yellow→amber, green→cyan) so the hook never
 * goes dark mid-rollout. Contract is unchanged: { state, reasons, detail, stateMeta }.
 */
import { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const POLL_MS = 2_000;

const OVERALL_TO_STATE = { red: 'rose', yellow: 'amber', green: 'cyan' };
const STATE_LABEL = { rose: 'CRITICAL', amber: 'ELEVATED', cyan: 'ALL SYSTEMS' };

export const useAppState = () => {
  const [state, setState] = useState('cyan');
  const [reasons, setReasons] = useState([]);
  const [detail, setDetail] = useState('—');
  const [signals, setSignals] = useState({});

  const fromHealth = useCallback(async () => {
    const resp = await fetch(`${BACKEND_URL}/api/system/health`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const next = OVERALL_TO_STATE[data.overall] || 'amber';
    const offenders = (data.subsystems || [])
      .filter((s) => s.status !== 'green')
      .map((s) => `${s.name}: ${s.detail || s.status}`);
    const counts = data.counts || {};
    setState(next);
    setReasons(offenders);
    setDetail(
      next === 'cyan'
        ? `${counts.green ?? 0} systems ok`
        : `${counts.red ?? 0} red · ${counts.yellow ?? 0} warn`,
    );
  }, []);

  const fetchState = useCallback(async () => {
    try {
      const resp = await fetch(`${BACKEND_URL}/api/safety/system-state`);
      if (resp.status === 404) return fromHealth(); // older backend
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data?.success === false && !data.state) throw new Error('state unavailable');
      const next = data.state || 'amber';
      const why = data.reasons || [];
      setState(next);
      setReasons(why);
      setSignals(data.signals || {});
      const counts = data.health_counts || {};
      setDetail(
        next === 'cyan'
          ? (why[0] || 'all systems nominal')
          : `${counts.red ?? 0} red · ${counts.yellow ?? 0} warn`,
      );
    } catch (e) {
      // last-resort fallback to health; if THAT fails, flag rose.
      try {
        await fromHealth();
      } catch (e2) {
        setState('rose');
        setReasons([`state offline: ${String(e2.message || e2)}`]);
        setDetail('state offline');
      }
    }
  }, [fromHealth]);

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

  return { state, reasons, detail, signals, stateMeta };
};

export default useAppState;
