/**
 * DrawerSplitHandle — vertical drag handle that re-sizes the V5 bottom
 * drawer's 2-column split (SentCom Intelligence | Stream Deep Feed).
 * Shipped 2026-04-29 afternoon-11 per operator request.
 *
 * Behavior:
 *   - Drag horizontally → live width update for the left column
 *   - Constrained to [25%, 80%] so neither side ever fully collapses
 *   - Persists the chosen percent to localStorage under
 *     `v5_drawer_left_pct` so it survives page refreshes
 *   - Double-click → reset to default (60%)
 *   - Hover/drag visual: emerald accent line through the centre of
 *     the handle column. Cursor switches to col-resize while active.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'v5_drawer_left_pct';
const MIN_PCT = 25;
const MAX_PCT = 80;
const DEFAULT_PCT = 60;

const _readSavedPct = () => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PCT;
    const v = parseFloat(raw);
    if (Number.isFinite(v) && v >= MIN_PCT && v <= MAX_PCT) return v;
  } catch (_e) { /* localStorage unavailable */ }
  return DEFAULT_PCT;
};

/**
 * Hook returning the current left-column percent + a setter that
 * clamps and persists. Used by `<SentComV5View>` to drive the
 * `gridTemplateColumns` style of the bottom drawer.
 */
export const useDrawerSplit = () => {
  const [leftPct, setLeftPct] = useState(_readSavedPct);

  const updateAndPersist = useCallback((pct) => {
    const clamped = Math.max(MIN_PCT, Math.min(MAX_PCT, pct));
    setLeftPct(clamped);
    try {
      window.localStorage.setItem(STORAGE_KEY, String(clamped));
    } catch (_e) { /* ignore quota / disabled */ }
  }, []);

  const resetToDefault = useCallback(() => {
    updateAndPersist(DEFAULT_PCT);
  }, [updateAndPersist]);

  return { leftPct, setLeftPct: updateAndPersist, resetToDefault };
};

/**
 * Visual + interaction handle. Renders as a 4px-wide column between
 * the two drawer panels. Caller is responsible for placing it at the
 * correct grid-column index inside the bottom drawer's grid.
 */
export const DrawerSplitHandle = ({ containerRef, onChange, onReset }) => {
  const [dragging, setDragging] = useState(false);
  const draggingRef = useRef(false);

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    draggingRef.current = true;
    setDragging(true);
  }, []);

  const handleDoubleClick = useCallback(() => {
    onReset?.();
  }, [onReset]);

  useEffect(() => {
    const onMove = (e) => {
      if (!draggingRef.current) return;
      const container = containerRef?.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      if (rect.width <= 0) return;
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      onChange?.(pct);
    };
    const onUp = () => {
      if (draggingRef.current) {
        draggingRef.current = false;
        setDragging(false);
      }
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [containerRef, onChange]);

  return (
    <div
      data-testid="drawer-split-handle"
      role="separator"
      aria-orientation="vertical"
      title="Drag to resize · double-click to reset"
      onMouseDown={handleMouseDown}
      onDoubleClick={handleDoubleClick}
      className={
        'relative w-1 h-full flex-shrink-0 ' +
        'cursor-col-resize select-none transition-colors duration-150 ' +
        (dragging
          ? 'bg-emerald-500/70'
          : 'bg-zinc-800 hover:bg-emerald-500/40')
      }
    >
      {/* Subtle vertical dot accent so the handle is discoverable when
          panels are dim. Three small dots in the middle, like a grip. */}
      <div className="absolute inset-y-0 -left-1 -right-1 flex items-center justify-center pointer-events-none">
        <div className="flex flex-col items-center gap-0.5 opacity-60">
          <div className="w-0.5 h-0.5 rounded-full bg-zinc-500" />
          <div className="w-0.5 h-0.5 rounded-full bg-zinc-500" />
          <div className="w-0.5 h-0.5 rounded-full bg-zinc-500" />
        </div>
      </div>
    </div>
  );
};

export default DrawerSplitHandle;
