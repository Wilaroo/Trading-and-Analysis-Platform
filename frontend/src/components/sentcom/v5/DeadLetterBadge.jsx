/**
 * DeadLetterBadge — small count pill showing historical-data requests that
 * are stuck in permanent failure. Appears in the PipelineHUD `rightExtra`.
 *
 * Reads the existing `/api/ib-collector/queue-progress-detailed` endpoint
 * (no new backend surface). Pills's color:
 *   • 0 failed      — hidden (don't add chrome for a clean queue)
 *   • 1-49 failed   — amber warn
 *   • 50+ failed    — rose alarm
 *
 * Clicking scrolls to / opens the existing Failed Items panel via URL hash
 * so users can inspect and retry. Keeping this extremely read-only — no
 * mutation from here.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { AlertTriangle } from 'lucide-react';
import api from '../../../utils/api';

export const DeadLetterBadge = ({ onClick }) => {
  const [failed, setFailed] = useState(0);

  const fetchFailed = useCallback(async () => {
    try {
      const res = await api.get('/api/ib-collector/queue-progress-detailed');
      if (res?.data?.success) {
        setFailed(res.data.overall?.failed || 0);
      }
    } catch {
      // swallow — badge just stays at last known value
    }
  }, []);

  useEffect(() => {
    fetchFailed();
    const t = setInterval(fetchFailed, 30000);
    return () => clearInterval(t);
  }, [fetchFailed]);

  if (!failed) return null;

  const tone = failed >= 50 ? 'v5-chip-veto' : 'v5-chip-close';
  const label = failed >= 1000 ? `${Math.floor(failed / 1000)}k` : failed.toString();

  const handleClick = () => {
    if (onClick) {
      onClick();
      return;
    }
    // Default: route to the NIA tab and let the collection panel handle it.
    try {
      window.dispatchEvent(new CustomEvent('v5-open-failed-items'));
    } catch { /* noop */ }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`v5-chip ${tone} flex items-center gap-1 hover:brightness-125 transition-all`}
      data-testid="v5-dead-letter-badge"
      title={`${failed.toLocaleString()} historical-data requests permanently failed. Click to inspect.`}
    >
      <AlertTriangle className="w-2.5 h-2.5" />
      <span>{label} DLQ</span>
    </button>
  );
};

export default DeadLetterBadge;
