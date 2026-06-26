/**
 * useRiskRail — polls /api/safety/risk-rail for the V6 Risk rail (DLP headroom).
 * DLP changes slowly, so a 5s cadence is plenty. Fail-soft: keeps last good data.
 */
import { useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const POLL_MS = 5_000;

export const useRiskRail = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const fetchOnce = async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/api/safety/risk-rail`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (alive.current) setData(d);
      } catch {
        /* keep last good data */
      } finally {
        if (alive.current) setLoading(false);
      }
    };
    fetchOnce();
    const t = setInterval(fetchOnce, POLL_MS);
    return () => { alive.current = false; clearInterval(t); };
  }, []);

  return { data, loading };
};

export default useRiskRail;
