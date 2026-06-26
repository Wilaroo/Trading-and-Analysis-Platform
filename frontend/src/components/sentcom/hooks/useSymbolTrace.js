/**
 * useSymbolTrace — fetches /api/scanner/symbol-trace?symbol=X for the V6
 * Chart+Verdict panel. Refetches on symbol change + slow 15s poll while a
 * symbol is selected (the trace is forensic, not tick-level). Fail-soft.
 */
import { useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

export const useSymbolTrace = (symbol, { pollMs = 15_000 } = {}) => {
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    if (!symbol) { setTrace(null); return undefined; }
    const run = async () => {
      setLoading(true);
      try {
        const r = await fetch(`${BACKEND_URL}/api/scanner/symbol-trace?symbol=${encodeURIComponent(symbol)}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (alive.current) setTrace(d);
      } catch {
        /* keep last good trace */
      } finally {
        if (alive.current) setLoading(false);
      }
    };
    run();
    const t = setInterval(run, pollMs);
    return () => { alive.current = false; clearInterval(t); };
  }, [symbol, pollMs]);

  return { trace, loading };
};

export default useSymbolTrace;
