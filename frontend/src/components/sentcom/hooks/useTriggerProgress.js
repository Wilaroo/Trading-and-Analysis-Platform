/**
 * useTriggerProgress — polls /api/scanner/trigger-progress/{symbol} (1s) for the
 * V6 Thinking-pane micro-bars. Only polls while a symbol is selected. Fail-soft.
 */
import { useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

export const useTriggerProgress = (symbol, { pollMs = 1_000 } = {}) => {
  const [data, setData] = useState(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    if (!symbol) { setData(null); return undefined; }
    const run = async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/api/scanner/trigger-progress/${encodeURIComponent(symbol)}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (alive.current) setData(d);
      } catch {
        /* keep last good */
      }
    };
    run();
    const t = setInterval(run, pollMs);
    return () => { alive.current = false; clearInterval(t); };
  }, [symbol, pollMs]);

  return data;
};

export default useTriggerProgress;
