/**
 * useLayoutVariant — centralized layout-variant resolver.
 *
 * v19.34.30 — Prep for the V6 migration. Before this hook, the
 * `?v4=1` escape hatch lived inline in SentCom.jsx as a one-off
 * `URLSearchParams(window.location.search).get('v4')` read. That
 * made every future layout flip (`?v6=1` rollout, then `?v5=1`
 * rollback) a multi-file edit.
 *
 * With this hook, the read logic is ONE line and layouts are
 * promoted/demoted by changing the DEFAULT_VARIANT constant —
 * no other file edit needed.
 *
 * Precedence (highest → lowest):
 *   1. `?layout=<name>` query param (explicit override, highest
 *      priority, intentionally not persisted — one-shot preview)
 *   2. `?v5=1` / `?v6=1` legacy aliases (operator muscle memory —
 *      once V6 is default, `?v5=1` is the rollback handle)
 *   3. localStorage `sentcom_layout` (sticky preference set via
 *      the variant switcher UI, if/when we add one)
 *   4. DEFAULT_VARIANT (single source of truth for "what ships")
 *
 * If a URL variant is passed that isn't in VALID_VARIANTS, we fall
 * through as if the param wasn't there. Prevents `?layout=typo`
 * from rendering nothing.
 *
 * NOTE: we intentionally do NOT listen for URL changes at runtime.
 * React Router + hash navigation would cause re-reads that drop
 * operator context (e.g. focused symbol). Variant changes require
 * a full page reload — that's a feature, not a bug.
 */
import { useMemo } from 'react';

export const VALID_VARIANTS = ['v5', 'v6', 'new', 'classic'];

// Single source of truth for "what ships by default". Flip this
// and redeploy to promote a new layout to default.
// v19.34.31 — V5 is now the ONLY reachable primary layout for
// the command-center tab. `new` and `classic` are rollback modes
// kept for emergency use (accessible via `?layout=new` or
// `?layout=classic`). `v6` is reserved for the upcoming Phase B.
export const DEFAULT_VARIANT = 'v5';

const STORAGE_KEY = 'sentcom_layout';

/**
 * Read + normalize the active layout variant. Pure function, safe
 * to call during render. Returns one of VALID_VARIANTS.
 */
export function resolveLayoutVariant() {
  if (typeof window === 'undefined') return DEFAULT_VARIANT;

  try {
    const params = new URLSearchParams(window.location.search);

    // 1. ?layout=v5|v6 explicit override
    const explicit = params.get('layout');
    if (explicit && VALID_VARIANTS.includes(explicit)) {
      return explicit;
    }

    // 2. ?v5=1 / ?v6=1 legacy alias flags
    for (const v of VALID_VARIANTS) {
      if (params.get(v) === '1') return v;
    }

    // 3. localStorage sticky preference
    try {
      const stored = window.localStorage?.getItem(STORAGE_KEY);
      if (stored && VALID_VARIANTS.includes(stored)) {
        return stored;
      }
    } catch {
      // localStorage blocked (private mode / SSR) — fall through.
    }
  } catch {
    // Querystring parse failed — fall through.
  }

  return DEFAULT_VARIANT;
}

/**
 * Persist a variant as the sticky preference. Returns the stored
 * value or null if storage was blocked. No-op for invalid variants.
 */
export function setStickyLayoutVariant(variant) {
  if (typeof window === 'undefined') return null;
  if (!VALID_VARIANTS.includes(variant)) return null;
  try {
    window.localStorage?.setItem(STORAGE_KEY, variant);
    return variant;
  } catch {
    return null;
  }
}

/**
 * Clear the sticky preference. Useful for "reset to default" UX.
 */
export function clearStickyLayoutVariant() {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage?.removeItem(STORAGE_KEY);
  } catch {
    // Storage blocked — nothing to clear.
  }
}

/**
 * React hook — memoized variant read. Re-computes only when the
 * component re-mounts (which is what we want — changing layouts
 * mid-session is intentionally a full reload).
 */
export function useLayoutVariant() {
  return useMemo(() => resolveLayoutVariant(), []);
}
