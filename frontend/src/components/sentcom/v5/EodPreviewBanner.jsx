/**
 * EodPreviewBanner — auto-expanding banner that surfaces what the EOD
 * sweep WILL do, BEFORE the operator reaches the EOD close (3:45 PM ET,
 * dynamic via `eod_hour_et`/`eod_minute_et`).
 *
 * Behaviour (per operator spec 2026-05-13):
 *   • Hidden until 3:30 PM ET (server-computed `is_eod_window`).
 *   • Auto-expands inside the window with a per-category breakdown.
 *   • Click X to dismiss for the session (sessionStorage flag).
 *   • Re-emerges if a RED disagreement appears after dismiss
 *     (RED state always wins — dismiss only suppresses GREEN/AMBER).
 *
 * 2026-02-13 v19.34.152
 */
import React, { useState, useEffect } from 'react';
import { AlertTriangle, Clock, X, CheckCircle2 } from 'lucide-react';
import { useEodPreview } from '../../../hooks/useEodPreview';

const DISMISS_KEY = 'eod-preview-banner-dismissed';

const HEALTH_BG = {
  red: 'bg-rose-900/85 border-rose-500 text-rose-100',
  amber: 'bg-amber-900/85 border-amber-500 text-amber-100',
  green: 'bg-emerald-900/40 border-emerald-700 text-emerald-200',
  unknown: 'bg-zinc-900/85 border-zinc-700 text-zinc-200',
};

const HEALTH_PULSE = { red: 'animate-pulse', amber: '', green: '', unknown: '' };

export const EodPreviewBanner = () => {
  const data = useEodPreview();
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem(DISMISS_KEY) === '1'
  );

  // Reset dismiss flag at midnight ET so it doesn't carry across days
  // on a long-running browser tab.
  useEffect(() => {
    const id = setInterval(() => {
      const today = new Date().toDateString();
      const stored = sessionStorage.getItem(`${DISMISS_KEY}-day`);
      if (stored !== today) {
        sessionStorage.removeItem(DISMISS_KEY);
        sessionStorage.setItem(`${DISMISS_KEY}-day`, today);
        setDismissed(false);
      }
    }, 60000);
    return () => clearInterval(id);
  }, []);

  if (!data) return null;
  if (!data.is_eod_window) return null;

  const health = data.health || 'unknown';
  // RED state always wins — dismiss only suppresses GREEN/AMBER.
  if (dismissed && health !== 'red') return null;

  const handleDismiss = () => {
    sessionStorage.setItem(DISMISS_KEY, '1');
    sessionStorage.setItem(`${DISMISS_KEY}-day`, new Date().toDateString());
    setDismissed(true);
  };

  const minsToEod = data.minutes_to_eod_close;
  const minsToMC = data.minutes_to_market_close;
  const eodTimeStr = `${data.eod_hour_et}:${String(data.eod_minute_et).padStart(2, '0')} ET`;
  const summary = data.summary || {};

  return (
    <div
      data-testid="v5-eod-preview-banner"
      className={`w-full border-b-2 px-4 py-2 v5-mono text-xs ${HEALTH_BG[health]} ${HEALTH_PULSE[health]}`}
      style={{ zIndex: 58 }}
    >
      <div className="flex items-center gap-3 flex-wrap">
        {health === 'red' ? (
          <AlertTriangle className="w-4 h-4 shrink-0" />
        ) : health === 'green' ? (
          <CheckCircle2 className="w-4 h-4 shrink-0" />
        ) : (
          <Clock className="w-4 h-4 shrink-0" />
        )}

        <span
          data-testid="v5-eod-preview-headline"
          className="font-bold tracking-wider"
        >
          {health === 'red'
            ? 'EOD PRE-CLOSE — ACTION REQUIRED'
            : `EOD PRE-CLOSE PREVIEW · close at ${eodTimeStr}`}
        </span>

        <span className="opacity-80">
          {minsToEod > 0
            ? `T-${minsToEod}m to EOD close`
            : minsToMC > 0
              ? `T-${minsToMC}m to market close (EOD already fired)`
              : 'Market closed'}
        </span>

        <div className="flex items-center gap-3 ml-auto">
          {/* Counts */}
          {summary.ib_vs_bot_disagreement > 0 && (
            <span
              data-testid="v5-eod-preview-disagreement-count"
              className="px-2 py-0.5 rounded bg-rose-700/70 text-rose-100 font-bold tracking-wider border border-rose-400"
              title={(data.ib_vs_bot_disagreement || [])
                .map((u) => `${u.symbol}: ${u.qty}`).join('\n')}
            >
              🚨 {summary.ib_vs_bot_disagreement} UNTRACKED
            </span>
          )}
          {summary.positions_to_close > 0 && (
            <span data-testid="v5-eod-preview-close-count" className="opacity-90">
              <b>{summary.positions_to_close}</b> to close
            </span>
          )}
          {summary.pending_entries_to_cancel > 0 && (
            <span
              data-testid="v5-eod-preview-cancel-count"
              className="opacity-90"
              title={(data.pending_entries_to_cancel || [])
                .map((o) => `${o.symbol} ${o.action} ${o.quantity} @ ${o.limit_price ?? o.stop_price}`).join('\n')}
            >
              <b>{summary.pending_entries_to_cancel}</b> to cancel
            </span>
          )}
          {summary.swing_positions_to_roll > 0 && (
            <span data-testid="v5-eod-preview-roll-count" className="opacity-70">
              <b>{summary.swing_positions_to_roll}</b> roll overnight
            </span>
          )}

          {/* Dismiss — only show for non-RED states */}
          {health !== 'red' && (
            <button
              data-testid="v5-eod-preview-dismiss"
              onClick={handleDismiss}
              className="ml-2 opacity-60 hover:opacity-100 transition-opacity"
              title="Dismiss until tomorrow"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* RED disagreement detail rows */}
      {health === 'red' && (data.ib_vs_bot_disagreement || []).length > 0 && (
        <div
          data-testid="v5-eod-preview-disagreement-detail"
          className="mt-2 pl-7 flex flex-wrap gap-x-4 gap-y-1 text-[11px] opacity-90"
        >
          <span className="font-bold">Untracked at IB:</span>
          {(data.ib_vs_bot_disagreement || []).map((u) => (
            <span key={u.symbol} className="text-rose-50">
              {u.symbol}={u.qty > 0 ? '+' : ''}{Math.round(u.qty)}
            </span>
          ))}
          <span className="ml-2 opacity-80">
            → bot will NOT auto-close. Adopt or flatten in TWS NOW.
          </span>
        </div>
      )}
    </div>
  );
};

export default EodPreviewBanner;
