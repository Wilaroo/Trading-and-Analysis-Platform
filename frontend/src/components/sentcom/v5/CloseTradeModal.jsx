/**
 * v19.34.72 — Operator Close Panel
 *
 * Inline modal launched from each Open Position row. Lets the operator
 * exit a position immediately via IB with:
 *   - Order type: Market or Limit
 *   - Percentage slider: 25 / 50 / 75 / 100 (custom values allowed)
 *
 * The backend (POST /api/trading-bot/trades/{trade_id}/close with JSON
 * body) cancels any live bracket children at IB before sending the
 * close, so we never close on top of a live OCA leg. Partial closes
 * keep the trade open with reduced size; the periodic Bracket-State
 * Reconciler re-attaches a fresh bracket within 120s.
 */
import React, { useMemo, useState } from 'react';
import { X } from 'lucide-react';

const PCT_PRESETS = [25, 50, 75, 100];

const formatPx = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return Number(v).toFixed(2);
};

const CloseTradeModal = ({ position, onClose, onSubmitted }) => {
  const tradeId = position?.trade_id || position?.id;
  const symbol = position?.symbol || '?';
  const direction = (position?.direction || position?.side || 'long').toLowerCase();
  const isShort = direction === 'short';
  const remaining = Number(
    position?.remaining_shares ?? position?.shares ?? 0
  ) || 0;
  const currentPrice = Number(
    position?.current_price ?? position?.last_price ?? position?.entry_price ?? 0
  ) || 0;

  const [orderType, setOrderType] = useState('market'); // 'market' | 'limit'
  const [percentage, setPercentage] = useState(100);
  const [limitPrice, setLimitPrice] = useState(
    currentPrice ? currentPrice.toFixed(2) : ''
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const sharesToClose = useMemo(() => {
    const n = Math.max(1, Math.min(remaining, Math.round(remaining * percentage / 100)));
    return remaining > 0 ? n : 0;
  }, [remaining, percentage]);

  const handleSubmit = async () => {
    if (!tradeId) {
      setError('Missing trade_id — cannot close.');
      return;
    }
    if (orderType === 'limit') {
      const lmt = Number(limitPrice);
      if (!lmt || lmt <= 0) {
        setError('Enter a valid limit price > 0.');
        return;
      }
    }
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const base = process.env.REACT_APP_BACKEND_URL || '';
      const res = await fetch(
        `${base}/api/trading-bot/trades/${encodeURIComponent(tradeId)}/close`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            percentage: Number(percentage),
            order_type: orderType,
            limit_price: orderType === 'limit' ? Number(limitPrice) : null,
            reason: 'v5_operator_close_panel',
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.success === false) {
        const detail = data?.detail;
        const errMsg =
          (typeof detail === 'string' ? detail : detail?.error) ||
          data?.error ||
          `Close failed (${res.status})`;
        setError(errMsg);
      } else {
        setResult(data);
        onSubmitted?.(data);
      }
    } catch (e) {
      setError(`Network error: ${e.message || e}`);
    } finally {
      setSubmitting(false);
    }
  };

  const closeAction = isShort ? 'BUY-TO-COVER' : 'SELL';

  return (
    <div
      data-testid={`close-trade-modal-${symbol}`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
    >
      <div className="w-[420px] max-w-[95vw] rounded-lg border border-zinc-700 bg-zinc-950 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="v5-mono text-lg font-bold text-zinc-100">{symbol}</span>
            <span className={`px-1.5 py-0 text-[12px] uppercase tracking-wider rounded border ${
              isShort
                ? 'bg-rose-950/70 text-rose-300 border-rose-800'
                : 'bg-emerald-950/70 text-emerald-300 border-emerald-800'
            }`}>
              {direction}
            </span>
            <span className="text-xs text-zinc-500">
              {remaining} sh @ ${formatPx(currentPrice)}
            </span>
          </div>
          <button
            data-testid="close-trade-modal-x"
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-200 transition-colors"
            aria-label="Cancel"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-3 space-y-4">
          {/* Order type */}
          <div>
            <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1.5">
              Order type
            </div>
            <div className="grid grid-cols-2 gap-1 rounded bg-zinc-900 p-1">
              {['market', 'limit'].map((t) => (
                <button
                  key={t}
                  data-testid={`close-trade-order-type-${t}`}
                  onClick={() => setOrderType(t)}
                  className={`py-1.5 text-xs uppercase tracking-wider rounded transition-colors ${
                    orderType === t
                      ? 'bg-zinc-800 text-cyan-300 font-semibold'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Limit price input — visible only when Limit */}
          {orderType === 'limit' && (
            <div>
              <div className="text-xs uppercase tracking-wider text-zinc-500 mb-1.5">
                Limit price
              </div>
              <input
                data-testid="close-trade-limit-price"
                type="number"
                step="0.01"
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
                className="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1.5 text-sm text-zinc-100 font-mono focus:outline-none focus:border-cyan-700"
                placeholder="e.g., 148.20"
              />
              <div className="text-[11px] text-zinc-600 mt-1">
                Current mark: ${formatPx(currentPrice)}
              </div>
            </div>
          )}

          {/* Percentage */}
          <div>
            <div className="flex items-center justify-between text-xs uppercase tracking-wider text-zinc-500 mb-1.5">
              <span>Size to close</span>
              <span className="text-zinc-300 font-mono">
                {percentage}% · {sharesToClose} sh
              </span>
            </div>
            <div className="grid grid-cols-4 gap-1 mb-2">
              {PCT_PRESETS.map((p) => (
                <button
                  key={p}
                  data-testid={`close-trade-pct-${p}`}
                  onClick={() => setPercentage(p)}
                  className={`py-1 text-xs rounded transition-colors ${
                    percentage === p
                      ? 'bg-cyan-900/60 text-cyan-200 border border-cyan-800'
                      : 'bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200'
                  }`}
                >
                  {p}%
                </button>
              ))}
            </div>
            <input
              data-testid="close-trade-pct-slider"
              type="range"
              min="1"
              max="100"
              value={percentage}
              onChange={(e) => setPercentage(Number(e.target.value))}
              className="w-full accent-cyan-500"
            />
          </div>

          {/* Confirmation line */}
          <div className="rounded border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-xs">
            <span className="text-zinc-500">About to: </span>
            <span className="text-zinc-200 font-mono">
              {closeAction} {sharesToClose} {symbol}
              {orderType === 'limit'
                ? ` @ LMT $${Number(limitPrice || 0).toFixed(2)}`
                : ' @ MKT'}
            </span>
            <div className="text-[11px] text-zinc-500 mt-1">
              Any live bracket SL/PT will be cancelled at IB first.
            </div>
          </div>

          {/* Error */}
          {error && (
            <div
              data-testid="close-trade-error"
              className="rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-xs text-rose-300"
            >
              {error}
            </div>
          )}

          {/* Result */}
          {result && (
            <div
              data-testid="close-trade-success"
              className="rounded border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-300 space-y-0.5"
            >
              <div className="font-semibold">
                ✓ {result.status === 'working' ? 'Order resting at IB' : 'Close submitted'}
              </div>
              {result.fill_price != null && (
                <div>Fill: ${Number(result.fill_price).toFixed(2)} · {result.shares_closed} sh</div>
              )}
              {result.shares_remaining > 0 && (
                <div>Remaining: {result.shares_remaining} sh (bracket will re-attach within 120s)</div>
              )}
              {result.order_id && (
                <div className="text-emerald-500">IB order #{result.order_id}</div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-zinc-800 px-4 py-3">
          <button
            data-testid="close-trade-cancel-btn"
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 text-xs uppercase tracking-wider rounded border border-zinc-700 text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
          >
            {result ? 'Done' : 'Cancel'}
          </button>
          {!result && (
            <button
              data-testid="close-trade-confirm-btn"
              onClick={handleSubmit}
              disabled={submitting || remaining <= 0}
              className="px-3 py-1.5 text-xs uppercase tracking-wider rounded bg-rose-700 text-white hover:bg-rose-600 disabled:opacity-50 disabled:cursor-not-allowed font-semibold"
            >
              {submitting ? 'Closing…' : `Close ${sharesToClose} sh`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default CloseTradeModal;
