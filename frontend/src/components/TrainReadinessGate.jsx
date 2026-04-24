/**
 * TrainReadinessGate — render-prop wrapper that gates a "train" action
 * against `/api/backfill/readiness`.
 *
 * Usage:
 *   <TrainReadinessGate>
 *     {({ready, verdict, blockers, warnings, gateProps, badge}) => (
 *       <button
 *         onClick={handleTrain}
 *         disabled={!ready || isTraining}
 *         {...gateProps}   // merges title attr with the blockers tooltip
 *       >
 *         Train All {badge /* ⓘ compact colored dot *\/}
 *       </button>
 *     )}
 *   </TrainReadinessGate>
 *
 * Important: the gate does NOT force `disabled` on its own — the caller
 * decides. We merge readiness into the button's existing disabled /
 * title / className conditions so we don't fight the component's own
 * loading state.
 *
 * Shift+click override:
 *   The gate exposes `isOverride(event)` so a button can detect a
 *   shift-click and allow the user to consciously train on a red
 *   dataset (escape hatch for debug / partial retrains). The caller is
 *   responsible for calling this in its own click handler.
 *
 * Also exposes:
 *   - `tooltipText`: the full human-readable reason string to show
 *   - `summary`: the API's one-line summary
 */

import React from 'react';
import { useTrainReadiness } from '../hooks/useTrainReadiness';

const DOT_BY_VERDICT = {
  green:   'bg-emerald-400',
  yellow:  'bg-amber-400',
  red:     'bg-rose-400 animate-pulse',
  unknown: 'bg-zinc-500',
};

/**
 * Compose the tooltip text shown on the train button when it is gated.
 * Lists the blockers and warnings so the user knows exactly what's
 * stopping them. Keeps it short enough to fit in a native `title`.
 */
function _buildTooltip({ ready, verdict, blockers, warnings, error }) {
  if (error) {
    return `Readiness check unreachable — ${error}. Shift+click to train anyway.`;
  }
  if (ready) {
    return 'Backfill ready — safe to train. Click to proceed.';
  }
  const parts = [];
  if (verdict === 'red') parts.push('🔴 NOT READY — blockers:');
  else if (verdict === 'yellow') parts.push('🟡 NOT READY — warnings:');
  else parts.push(`Readiness: ${verdict}`);

  blockers.slice(0, 3).forEach((b) => parts.push(`• ${b}`));
  warnings.slice(0, 2).forEach((w) => parts.push(`• ${w}`));
  parts.push('');
  parts.push('Shift+click to train anyway (override).');
  return parts.join('\n');
}

/**
 * True when the click event is a conscious override (shift+click or
 * alt+click). Callers wire this into their onClick handler to bypass
 * the gate.
 */
export function isOverrideClick(event) {
  return !!(event && (event.shiftKey || event.altKey));
}

export const TrainReadinessGate = ({ children }) => {
  const { ready, verdict, blockers, warnings, loading, error, readiness, refresh } =
    useTrainReadiness();

  const tooltipText = _buildTooltip({ ready, verdict, blockers, warnings, error });

  const badge = (
    <span
      data-testid="train-readiness-badge"
      data-verdict={verdict}
      title={tooltipText}
      className={`inline-block w-1.5 h-1.5 rounded-full ${
        DOT_BY_VERDICT[verdict] || DOT_BY_VERDICT.unknown
      }`}
    />
  );

  // Props the consumer can spread onto the button to get a
  // readiness-aware title and data-testid without wiring those
  // manually.
  const gateProps = {
    title: tooltipText,
    'data-train-readiness': verdict,
  };

  return children({
    ready,
    verdict,
    blockers,
    warnings,
    loading,
    error,
    readiness,
    refresh,
    tooltipText,
    summary: readiness?.summary || null,
    badge,
    gateProps,
    isOverride: isOverrideClick,
  });
};

export default TrainReadinessGate;
