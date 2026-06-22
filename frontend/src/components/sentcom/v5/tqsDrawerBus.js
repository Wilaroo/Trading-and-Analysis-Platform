/**
 * tqsDrawerBus — v19.34.258 (Part B)
 *
 * Tiny window-event bus that lets any card (scanner / gameplan / open
 * position) open the single shared <TqsDrillDownDrawer/> without prop
 * drilling. Mirrors the existing `sentcom:focus-symbol` pattern used by
 * GamePlanStockCard.
 */
export const TQS_OPEN_EVENT = 'sentcom:open-tqs';

/**
 * Open the TQS drill-down drawer for a symbol.
 * @param {{symbol: string, source?: 'alert'|'position', card?: object}} payload
 */
export const openTqsDrawer = ({ symbol, source = 'alert', card = null } = {}) => {
  if (!symbol) return;
  try {
    window.dispatchEvent(
      new CustomEvent(TQS_OPEN_EVENT, {
        detail: { symbol: String(symbol).toUpperCase(), source, card },
      }),
    );
  } catch {
    /* no-op — best-effort */
  }
};
