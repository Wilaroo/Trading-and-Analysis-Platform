/**
 * useTaxonomy — v19.34.272 (T4)
 *
 * React hook that re-renders a component when the live SSOT taxonomy
 * (GET /api/sentcom/taxonomy) finishes hydrating in tradeStyleMeta.js.
 *
 * Why: `resolveTradeStyle`/`getTradeStyleMeta`/`isScalpStyle` read a
 * module-level `_dynamicStyleMap`. Without this hook, a view that mounted
 * before hydration would render the static fallback for the whole session.
 * Subscribing here guarantees the SSOT map becomes authoritative the instant
 * it arrives — killing the last bit of static-mirror staleness.
 *
 * Kept in its own file so tradeStyleMeta.js stays React-free (the node smoke
 * test imports it directly).
 */
import { useEffect, useState } from 'react';

import { subscribeTaxonomy, getTaxonomyVersion } from './tradeStyleMeta';

export const useTaxonomyVersion = () => {
  const [version, setVersion] = useState(getTaxonomyVersion());
  useEffect(() => subscribeTaxonomy(setVersion), []);
  return version;
};

export default useTaxonomyVersion;
