/**
 * EdgeRingForSymbol — drop-in Entry-Edge decision donut for any cockpit row.
 *
 * Reads the latest Edge triple for `symbol` from the shared store and renders the
 * EdgeProvenanceRing; click opens the shared Edge drawer (edgeDrawerBus). By default
 * renders NOTHING when the symbol has not been scored yet (keeps rows clean) — set
 * `showWhenEmpty` for a muted "scoring…" ring (used by the Verdict header / preview).
 */
import React from 'react';
import EdgeProvenanceRing from './EdgeProvenanceRing';
import { useEdgeTriple } from './useEdgeTriple';
import { openEdgeDrawer } from './edgeDrawerBus';

export default function EdgeRingForSymbol({
  symbol,
  size = 28,
  showWhenEmpty = false,
  setupType,
  direction,
  className = '',
}) {
  const { triple, item } = useEdgeTriple(symbol);
  if (!triple && !showWhenEmpty) return null;

  const drawerItem = item || {
    symbol,
    setup_type: setupType,
    direction,
    triple: triple || null,
  };

  return (
    <EdgeProvenanceRing
      triple={triple}
      size={size}
      className={className}
      onClick={() => openEdgeDrawer(drawerItem)}
      testIdSuffix={symbol}
    />
  );
}
