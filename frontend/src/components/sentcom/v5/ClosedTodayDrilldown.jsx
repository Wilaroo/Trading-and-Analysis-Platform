/**
 * ClosedTodayDrilldown — v19.31.9 (2026-05-04)
 *
 * Now a thin adapter on top of <PipelineStageDrilldown>. Kept as its
 * own export for back-compat with existing testids
 * (drilldown-winrate, drilldown-realized, drilldown-sum-r, etc.).
 */
import React, { useMemo } from 'react';
import { PipelineStageDrilldown } from './PipelineStageDrilldown';
import { closeStageConfig } from './pipelineStageColumns';

export const ClosedTodayDrilldown = ({
  open,
  onClose,
  closedToday = [],
  totalRealized = 0,
  winsToday = 0,
  lossesToday = 0,
  anchorRef,
  onJumpToTrade,
}) => {
  const cfg = useMemo(
    () => closeStageConfig({
      totalRealized, winsToday, lossesToday, sortedRows: closedToday,
    }),
    [totalRealized, winsToday, lossesToday, closedToday],
  );
  return (
    <PipelineStageDrilldown
      open={open}
      onClose={onClose}
      anchorRef={anchorRef}
      title={cfg.title}
      versionTag={cfg.versionTag}
      headerExtras={cfg.headerExtras}
      columns={cfg.columns}
      rows={closedToday}
      defaultSortKey={cfg.defaultSortKey}
      onRowClick={onJumpToTrade}
      emptyText={cfg.emptyText}
      testIdPrefix="closed-today-drilldown"
      footerHint="Click row to focus the symbol · Esc to close"
    />
  );
};

export default ClosedTodayDrilldown;
