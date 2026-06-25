/**
 * RowMetaChips — V6 Plan A Phase A shared primitive (§10, V6_INTEGRATION_v110_v114).
 *
 * A thin, presentational layout wrapper that keeps the per-row meta-chip
 * CLUSTER (TradeStyleChip + SetupGradeChip + any future row chip) spaced
 * consistently across every panel — V5 (OpenPositionsV5 / ScannerCardsV5)
 * and the upcoming V6 panes. The chips themselves stay independent; this
 * only owns the inline layout so the chip set never drifts panel-to-panel.
 *
 * Children-based by design (locked spec example):
 *
 *   <RowMetaChips testId={`row-meta-chips-${row.symbol}`}>
 *     <TradeStyleChip row={row} compact size="xs" />
 *     <SetupGradeChip setupType={row.setup_type} compact size="xs" />
 *   </RowMetaChips>
 *
 * Renders inline (`inline-flex`), so a SINGLE child renders byte-identically
 * to that child alone — which is exactly the V5 case today (only TradeStyleChip
 * is shown on the card face; SetupGradeChip is folded into the TQS drawer).
 * V6 panes can pass the full duo without any further wrapper work.
 *
 * Returns null when there are no renderable children (keeps cards uncluttered).
 */
import React from 'react';

export const RowMetaChips = ({ children, className = '', testId = 'row-meta-chips' }) => {
  const items = React.Children.toArray(children).filter(Boolean);
  if (items.length === 0) return null;
  return (
    <span
      data-testid={testId}
      className={`inline-flex items-center gap-1 ${className}`.trim()}
    >
      {items}
    </span>
  );
};

export default RowMetaChips;
