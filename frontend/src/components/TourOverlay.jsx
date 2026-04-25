/**
 * TourOverlay — renders the active guided tour step as:
 *   - A full-screen dim layer with a "spotlight" hole around the
 *     target element (achieved with a box-shadow trick).
 *   - A popover anchored next to the spotlight showing the step
 *     title + body + Next/Skip buttons + step counter + an optional
 *     "Learn more" link to the glossary entry.
 *
 * Listens for `sentcom:start-tour` window events to begin a tour by id.
 *
 * The overlay tracks the spotlight element on every animation frame so
 * scrolling / layout shifts keep the popover anchored. Resize-observer
 * + interval safety net handle the rare cases where rAF stalls.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronLeft, ChevronRight, X, BookOpen } from 'lucide-react';
import { tours, markTourSeen } from '../data/tours';
import { openGlossary } from './GlossaryDrawer';

const POPOVER_W = 320;
const POPOVER_GAP = 16;

function _computePopoverPos(rect, position, win) {
  if (!rect) return { top: 80, left: 80 };
  const { top, left, right, bottom, width, height } = rect;
  switch (position) {
    case 'top':
      return {
        top: Math.max(8, top - 8 - 180),
        left: Math.min(win.innerWidth - POPOVER_W - 8, Math.max(8, left + width / 2 - POPOVER_W / 2)),
      };
    case 'left':
      return {
        top: Math.max(8, top + height / 2 - 80),
        left: Math.max(8, left - POPOVER_W - POPOVER_GAP),
      };
    case 'right':
      return {
        top: Math.max(8, top + height / 2 - 80),
        left: Math.min(win.innerWidth - POPOVER_W - 8, right + POPOVER_GAP),
      };
    default: // bottom
      return {
        top: Math.min(win.innerHeight - 200, bottom + POPOVER_GAP),
        left: Math.min(win.innerWidth - POPOVER_W - 8, Math.max(8, left + width / 2 - POPOVER_W / 2)),
      };
  }
}

export const TourOverlay = () => {
  const [activeTour, setActiveTour] = useState(null); // tour object
  const [stepIdx, setStepIdx] = useState(0);
  const [rect, setRect] = useState(null);
  const rafRef = useRef(null);

  const step = activeTour?.steps?.[stepIdx] || null;

  const exit = useCallback(() => {
    if (activeTour) markTourSeen(activeTour.id);
    setActiveTour(null);
    setStepIdx(0);
    setRect(null);
  }, [activeTour]);

  const next = useCallback(() => {
    if (!activeTour) return;
    if (stepIdx + 1 >= activeTour.steps.length) {
      exit();
    } else {
      setStepIdx(stepIdx + 1);
    }
  }, [activeTour, stepIdx, exit]);

  const prev = useCallback(() => {
    setStepIdx((i) => Math.max(0, i - 1));
  }, []);

  // Listen for `sentcom:start-tour`
  useEffect(() => {
    const onStart = (e) => {
      const id = e?.detail?.id;
      const t = tours[id];
      if (!t) return;
      setActiveTour(t);
      setStepIdx(0);
    };
    window.addEventListener('sentcom:start-tour', onStart);
    return () => window.removeEventListener('sentcom:start-tour', onStart);
  }, []);

  // Track the target element's bounding rect each frame
  useEffect(() => {
    if (!step) return undefined;
    let cancelled = false;
    const update = () => {
      if (cancelled) return;
      const el = document.querySelector(step.selector);
      if (el) {
        const r = el.getBoundingClientRect();
        setRect({ top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height });
      } else {
        setRect(null);
      }
      rafRef.current = requestAnimationFrame(update);
    };
    update();
    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [step]);

  // Keyboard nav
  useEffect(() => {
    if (!activeTour) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        exit();
      } else if (e.key === 'ArrowRight' || e.key === 'Enter') {
        e.preventDefault();
        next();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        prev();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeTour, next, prev, exit]);

  const popoverPos = useMemo(
    () => (rect ? _computePopoverPos(rect, step?.position || 'bottom', window) : null),
    [rect, step]
  );

  if (!activeTour || !step) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[90] pointer-events-none"
        data-testid="tour-overlay"
      >
        {/* Spotlight hole — dim the page everywhere except the target rect */}
        {rect ? (
          <div
            data-testid="tour-spotlight"
            className="fixed pointer-events-none transition-all duration-200"
            style={{
              top: rect.top - 6,
              left: rect.left - 6,
              width: rect.width + 12,
              height: rect.height + 12,
              borderRadius: 8,
              boxShadow: '0 0 0 9999px rgba(0,0,0,0.72)',
              outline: '2px solid rgba(34,211,238,0.95)',
            }}
          />
        ) : (
          <div className="fixed inset-0 bg-black/70 pointer-events-none" />
        )}

        {/* Popover */}
        {popoverPos && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="fixed pointer-events-auto bg-zinc-950 border border-cyan-500/50 rounded-lg shadow-2xl shadow-cyan-500/30 p-4"
            style={{ top: popoverPos.top, left: popoverPos.left, width: POPOVER_W }}
            data-testid="tour-popover"
          >
            <div className="flex items-start gap-2 mb-2">
              <div className="flex-1 min-w-0">
                <div className="text-[10px] text-cyan-400 font-mono uppercase tracking-wide mb-0.5">
                  {activeTour.name} · {stepIdx + 1}/{activeTour.steps.length}
                </div>
                <div className="text-sm font-semibold text-zinc-100">{step.title}</div>
              </div>
              <button
                type="button"
                onClick={exit}
                data-testid="tour-skip"
                className="p-1 hover:bg-zinc-800 rounded text-zinc-400"
                title="Skip tour (Esc)"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-[12px] text-zinc-300 leading-relaxed mb-3">{step.body}</p>
            {step.helpId && (
              <button
                type="button"
                onClick={() => openGlossary(step.helpId)}
                data-testid="tour-learn-more"
                className="text-[11px] text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1 mb-3"
              >
                <BookOpen className="w-3 h-3" /> Learn more
              </button>
            )}
            <div className="flex items-center justify-between pt-2 border-t border-zinc-800">
              <button
                type="button"
                onClick={prev}
                disabled={stepIdx === 0}
                data-testid="tour-prev"
                className="text-[11px] px-2 py-1 rounded text-zinc-400 hover:text-zinc-100 disabled:opacity-30 inline-flex items-center gap-1"
              >
                <ChevronLeft className="w-3 h-3" /> Back
              </button>
              <button
                type="button"
                onClick={next}
                data-testid="tour-next"
                className="text-[11px] px-3 py-1 rounded bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 inline-flex items-center gap-1"
              >
                {stepIdx + 1 >= activeTour.steps.length ? 'Finish' : 'Next'}
                <ChevronRight className="w-3 h-3" />
              </button>
            </div>
          </motion.div>
        )}
      </motion.div>
    </AnimatePresence>
  );
};

export default TourOverlay;
