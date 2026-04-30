/**
 * V5 ScannerCards — unified live feed of setups / alerts / open positions /
 * recently closed trades, styled to match option-1-v5-command-center.html.
 *
 * Each card shows:
 *   - Symbol + stage chip
 *   - Mini 5-stage pipeline bar (scan → eval → order → manage → close)
 *   - Bot narrative (if any)
 *   - Gate score / P(win) / Sharpe metrics
 *
 * This component is purely presentational — it takes the setups / alerts /
 * positions / messages arrays that the existing SentCom hooks already
 * produce and folds them into a single ranked list.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLiveSubscriptions } from '../../../hooks/useLiveSubscription';

const STAGE_ORDER = ['scan', 'eval', 'order', 'manage', 'close'];
const STAGE_CLASS = {
  scan:   'v5-chip-scan',
  eval:   'v5-chip-eval',
  order:  'v5-chip-order',
  manage: 'v5-chip-manage',
  close:  'v5-chip-close',
  veto:   'v5-chip-veto',
};

const BOT_TEXT_COLOR = {
  scan: 'text-violet-400',
  eval: 'text-blue-400',
  order: 'text-yellow-400',
  manage: 'text-emerald-400',
  close: 'text-slate-400',
  veto: 'text-red-400',
};

const Mini5Stage = ({ stage, closedOutcome }) => {
  const idx = STAGE_ORDER.indexOf(stage);
  const isVeto = stage === 'veto';
  return (
    <div className="v5-mini-5stage">
      {STAGE_ORDER.map((s, i) => {
        if (isVeto && (s === 'eval' || s === 'scan')) return <span key={s} className={`on-${s}`} />;
        if (isVeto && i >= 2) return <span key={s} className="on-veto" />;
        if (i <= idx) {
          // On CLOSE, colour the final block red/green to encode win/loss
          if (s === 'close' && closedOutcome) {
            return <span key={s} className={closedOutcome === 'win' ? 'on-manage' : 'on-veto'} />;
          }
          return <span key={s} className={`on-${s}`} />;
        }
        return <span key={s} />;
      })}
    </div>
  );
};

// Accepts either a fraction (0.59 → "59%") or an already-scaled percentage
// (59 → "59%"). Backend mixes the two depending on field, so treat any
// value > 1 as already a percentage to prevent the 5900% bug.
const formatPct = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const pct = Math.abs(n) > 1 ? n : n * 100;
  return `${pct.toFixed(0)}%`;
};
const formatNum = (v, d = 2) => (v == null || Number.isNaN(Number(v))) ? '—' : Number(v).toFixed(d);
const formatPriceChange = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};

/**
 * Reduce the raw hook arrays into an ordered list of display cards.
 * Later stages outrank earlier: close > manage > order > eval > scan.
 * Within same stage, most recent first.
 */
const buildCards = ({ setups, alerts, positions, messages }) => {
  const bySymbol = new Map();

  // 1. Scanner setups — stage=scan (or eval if has confidence_score)
  (setups || []).forEach((s) => {
    const sym = (s.symbol || s.ticker || '').toUpperCase();
    if (!sym) return;
    const stage = s.gate_score != null || s.confidence != null ? 'eval' : 'scan';
    const existing = bySymbol.get(sym);
    // Only treat p_win as a separate metric when the backend actually
    // supplies it. Falling back to `confidence` here caused operators to
    // see the same number twice ("conf 51% / P(win) 51%") which was
    // misleading. Leave null so the metrics chip is hidden when only
    // confidence is known.
    const pWin = s.p_win ?? null;
    const card = {
      symbol: sym,
      stage,
      stage_note: s.setup_type || s.type || 'setup',
      change_pct: s.change_pct ?? s.relative_change ?? null,
      bot_text: s.bot_note || s.narrative || `${s.setup_type || 'setup'} flagged${s.confidence ? ` · conf ${formatPct(s.confidence)}` : ''}${s.relative_volume ? ` · RVol ${formatNum(s.relative_volume, 1)}×` : ''}.`,
      metrics: {
        gate: s.gate_score,
        p_win: pWin,
        sharpe: s.sharpe,
      },
      timestamp: s.timestamp || s.detected_at || s.created_at,
    };
    if (!existing || STAGE_ORDER.indexOf(card.stage) >= STAGE_ORDER.indexOf(existing.stage)) {
      bySymbol.set(sym, card);
    }
  });

  // 2. Alerts — stage=eval (or veto if blocked)
  (alerts || []).forEach((a) => {
    const sym = (a.symbol || a.ticker || '').toUpperCase();
    if (!sym) return;
    const blocked = a.blocked || a.vetoed;
    const stage = blocked ? 'veto' : (a.gate_score ? 'eval' : 'scan');
    const existing = bySymbol.get(sym);
    const card = {
      symbol: sym,
      stage,
      stage_note: a.alert_type || a.setup_type || 'alert',
      change_pct: a.change_pct ?? null,
      // Wave-1 (#2) — counter-trend warning. Surfaces the v17 soft-gate
      // matrix decision so the operator can see when an alert is
      // firing AGAINST the daily Setup (Bellafiore matrix).
      is_countertrend: !!a.is_countertrend,
      market_setup: a.market_setup || null,
      // 2026-04-30 v19.8 — surface tier so the operator knows whether
      // the symbol came from the live-tick scanner (intraday) or the
      // bar-poll service (swing/investment).
      tier: a.tier || a.symbol_tier || null,
      bot_text: a.reason || a.note || `${a.setup_type || 'alert'} · ${a.direction || ''}${a.gate_score ? ` · gate ${a.gate_score}` : ''}`,
      metrics: {
        gate: a.gate_score,
        p_win: a.p_win,
        sharpe: a.sharpe,
      },
      timestamp: a.timestamp || a.created_at,
    };
    if (!existing || STAGE_ORDER.indexOf(card.stage) >= STAGE_ORDER.indexOf(existing.stage) || blocked) {
      bySymbol.set(sym, card);
    }
  });

  // 3. Open positions — stage=manage (overrides earlier stages)
  (positions || []).forEach((p) => {
    const sym = (p.symbol || p.ticker || '').toUpperCase();
    if (!sym) return;
    const dir = (p.direction || p.side || '').toLowerCase();
    const pnlR = p.pnl_r ?? p.r_multiple ?? p.unrealized_r;
    const pnlUsd = p.unrealized_pnl ?? p.pnl ?? p.pnl_usd;
    // Backend may return `target_prices` (array, one per scale-out) OR
    // `target_price` (legacy scalar). Pick the first usable value.
    const pt = p.target_price ?? (Array.isArray(p.target_prices) ? p.target_prices[0] : null);
    bySymbol.set(sym, {
      symbol: sym,
      stage: 'manage',
      stage_note: `${dir === 'short' ? 'SHORT' : 'LONG'}${p.setup_type ? ' ' + p.setup_type : ''}`,
      change_pct: p.change_pct ?? null,
      bot_text:
        p.bot_note ||
        `Holding ${sym}${p.entry_price ? ` @ ${formatNum(p.entry_price, 2)}` : ''}` +
        `${p.stop_price ? ` · SL ${formatNum(p.stop_price, 2)}` : ''}` +
        `${pt ? ` · PT ${formatNum(pt, 2)}` : ''}.`,
      metrics: {
        gate: p.gate_score,
        p_win: p.p_win,
        sharpe: p.sharpe,
        r: pnlR,
        pnl: pnlUsd,
      },
      timestamp: p.opened_at || p.entry_time,
    });
  });

  // 4. Recently closed trades from messages — stage=close
  (messages || []).slice(0, 50).forEach((m) => {
    const sym = (m.symbol || m.ticker || '').toUpperCase();
    if (!sym) return;
    const kind = (m.event || m.kind || m.type || '').toLowerCase();
    if (!kind.includes('close') && !kind.includes('win') && !kind.includes('loss') && !kind.includes('exit')) return;
    const existing = bySymbol.get(sym);
    // Don't clobber an open position card with a closed message
    if (existing && existing.stage === 'manage') return;
    const outcome = kind.includes('win') || Number(m.realized_pnl) > 0 || Number(m.r_multiple) > 0 ? 'win'
                  : kind.includes('loss') || Number(m.realized_pnl) < 0 || Number(m.r_multiple) < 0 ? 'loss'
                  : null;
    bySymbol.set(sym, {
      symbol: sym,
      stage: 'close',
      stage_note: outcome === 'win' ? 'W' : outcome === 'loss' ? 'L' : '',
      closed_outcome: outcome,
      change_pct: null,
      bot_text: m.summary || m.text || m.message || 'Trade closed.',
      metrics: {
        r: m.r_multiple,
        pnl: m.realized_pnl,
      },
      timestamp: m.timestamp || m.created_at,
    });
  });

  // Rank: later stages first, then by timestamp desc
  return Array.from(bySymbol.values()).sort((a, b) => {
    const da = STAGE_ORDER.indexOf(a.stage);
    const db = STAGE_ORDER.indexOf(b.stage);
    if (da !== db) return db - da;
    return (new Date(b.timestamp || 0)) - (new Date(a.timestamp || 0));
  });
};


const relativeAge = (ts) => {
  if (!ts) return '';
  try {
    const diffS = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
    if (diffS < 60) return `${diffS}s`;
    if (diffS < 3600) return `${Math.floor(diffS / 60)}m`;
    return `${Math.floor(diffS / 3600)}h`;
  } catch { return ''; }
};


const ScannerCard = ({ card, active, previewed, onClick, hoveredSymbol, onHoverSymbol, dataCardIndex }) => {
  const chipClass = STAGE_CLASS[card.stage] || STAGE_CLASS.scan;
  const botColor = BOT_TEXT_COLOR[card.stage] || 'text-zinc-400';
  const hasMetrics = card.metrics && (
    card.metrics.gate != null || card.metrics.p_win != null
    || card.metrics.sharpe != null || card.metrics.r != null
  );
  const change = formatPriceChange(card.change_pct);
  const age = relativeAge(card.timestamp);
  const isHoverCross = hoveredSymbol && hoveredSymbol === card.symbol;

  // Stage chip label — mockup shows: "ORDER · 8s", "OPEN", "CLOSED W", "SKIP", "SCAN"
  let chipLabel;
  if (card.stage === 'veto') chipLabel = 'SKIP';
  else if (card.stage === 'manage') chipLabel = 'OPEN';
  else if (card.stage === 'close') chipLabel = card.closed_outcome === 'win' ? 'CLOSED W' : card.closed_outcome === 'loss' ? 'CLOSED L' : 'CLOSED';
  else chipLabel = card.stage.toUpperCase();

  return (
    <div
      data-testid={`v5-scanner-card-${card.symbol}`}
      data-card-index={dataCardIndex}
      onClick={onClick}
      onMouseEnter={onHoverSymbol ? () => onHoverSymbol(card.symbol) : undefined}
      onMouseLeave={onHoverSymbol ? () => onHoverSymbol(null) : undefined}
      className={`v5-scanner-card${active ? ' active' : ''}${previewed ? ' previewed' : ''}${isHoverCross ? ' v5-card-hover-cross' : ''}${card.is_countertrend ? ' v5-card-counter-trend' : ''}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="v5-mono font-bold text-sm text-zinc-100 hover:text-cyan-300 hover:underline transition-colors"
            data-testid={`scanner-card-symbol-${card.symbol}`}
          >
            {card.symbol}
          </span>
          <span className={`v5-chip ${chipClass}`}>
            {chipLabel}{age && card.stage === 'order' ? ` · ${age}` : ''}
          </span>
          {card.is_countertrend && (
            <span
              className="v5-chip v5-chip-counter-trend"
              title={card.market_setup ? `Counter-trend vs daily setup: ${card.market_setup}` : 'Firing against the daily setup matrix'}
              data-testid={`scanner-card-counter-${card.symbol}`}
            >
              ⚠ CT
            </span>
          )}
        </div>
        {change && (
          <span className={`v5-mono text-[13px] font-bold ${Number(card.change_pct) >= 0 ? 'v5-up' : 'v5-down'}`}>
            {card.stage === 'close' && card.metrics?.r != null
              ? `${Number(card.metrics.r) >= 0 ? '+' : ''}${Number(card.metrics.r).toFixed(1)}R`
              : change
            }
          </span>
        )}
      </div>

      <Mini5Stage stage={card.stage} closedOutcome={card.closed_outcome} />

      {card.bot_text && (
        <div className="v5-why mt-2">
          <span className={`${botColor} v5-bot-tag`}>Bot:</span>{' '}
          <span className="text-zinc-200">"{card.bot_text}"</span>
        </div>
      )}

      {hasMetrics && (
        <div className="flex items-center gap-3 mt-2 text-[12px] v5-mono">
          {card.metrics.gate != null && (
            <div className="flex items-center gap-1">
              <span className="v5-dim">gate</span>
              <span className={`font-bold ${card.metrics.gate >= 60 ? 'v5-up' : card.metrics.gate >= 45 ? 'v5-warn' : 'v5-down'}`}>
                {Math.round(card.metrics.gate)}
              </span>
            </div>
          )}
          {card.metrics.p_win != null && (() => {
            const n = Number(card.metrics.p_win);
            // Normalise to 0-1 fraction for the threshold comparison
            const frac = Math.abs(n) > 1 ? n / 100 : n;
            return (
              <div className="flex items-center gap-1">
                <span className="v5-dim">P(win)</span>
                <span className={`font-bold ${frac >= 0.55 ? 'v5-up' : 'v5-down'}`}>
                  {formatPct(card.metrics.p_win)}
                </span>
              </div>
            );
          })()}
          {card.metrics.sharpe != null && (
            <div className="flex items-center gap-1">
              <span className="v5-dim">Sharpe</span>
              <span className="font-bold text-zinc-200">{formatNum(card.metrics.sharpe, 2)}</span>
            </div>
          )}
          {card.metrics.r != null && card.stage !== 'close' && (
            <div className="flex items-center gap-1">
              <span className="v5-dim">R</span>
              <span className={`font-bold ${Number(card.metrics.r) >= 0 ? 'v5-up' : 'v5-down'}`}>
                {formatNum(card.metrics.r, 2)}
              </span>
            </div>
          )}
          {card.metrics.pnl != null && Math.abs(card.metrics.pnl) > 0 && (
            <span className={`ml-auto font-bold ${Number(card.metrics.pnl) >= 0 ? 'v5-up' : 'v5-down'}`}>
              {Number(card.metrics.pnl) >= 0 ? '+$' : '−$'}{Math.abs(Number(card.metrics.pnl)).toFixed(0)}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

// Wave 3 (#1) — group cards by Market Setup. Cards without a market_setup
// label fall into "OTHER" so nothing disappears. Empty groups are dropped.
// Stable section order: known-setup names first (sorted by card count
// desc), "neutral" / "OTHER" last so the operator's eye lands on the
// REGIME-shaping setups before the noise.
const _SETUP_LABEL_ORDER = [
  'gap_and_go', 'range_break', 'day_2_continuation', 'day_2_failure',
  'opening_drive', 'climactic_reversal', 'rotation_session',
  'neutral', null,
];

const _humanizeSetup = (s) => {
  if (!s) return 'OTHER';
  return s.replace(/_/g, ' ').toUpperCase();
};

const groupCardsBySetup = (cards) => {
  const groups = new Map();
  for (const c of cards) {
    const key = c.market_setup || null;  // null collapses to "OTHER"
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(c);
  }
  // Sort: explicit order first, unknown setups (not in _SETUP_LABEL_ORDER)
  // sort by count desc, then "neutral" / null at the end.
  const known = _SETUP_LABEL_ORDER;
  return Array.from(groups.entries()).sort(([a], [b]) => {
    const ai = known.indexOf(a);
    const bi = known.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    // Both unknown — sort alphabetically for stability
    return String(a).localeCompare(String(b));
  });
};

export const ScannerCardsV5 = ({
  setups,
  alerts,
  positions,
  messages,
  selectedSymbol,
  onSelectSymbol,
  hoveredSymbol,
  onHoverSymbol,
  onScanProgress,
}) => {
  const cards = useMemo(
    () => buildCards({ setups, alerts, positions, messages }),
    [setups, alerts, positions, messages]
  );

  // Wave 3 (#1) — operator-toggleable grouping by Market Setup.
  // Persisted to localStorage so the operator's choice survives reload.
  // Defaults OFF so existing layout is preserved on first encounter
  // — operator opts INTO grouping deliberately.
  const [groupBySetup, setGroupBySetup] = useState(() => {
    try { return localStorage.getItem('v5_scanner_group_by_setup') === 'true'; }
    catch { return false; }
  });
  const toggleGrouping = useCallback(() => {
    setGroupBySetup((v) => {
      const next = !v;
      try { localStorage.setItem('v5_scanner_group_by_setup', String(next)); } catch (_) { /* noop */ }
      return next;
    });
  }, []);

  // Collapsed-section state (per-setup). Operator can fold a section
  // they don't care about right now (e.g. "Day 2 Failure").
  const [collapsedGroups, setCollapsedGroups] = useState(() => new Set());
  const toggleGroup = useCallback((key) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  const groups = useMemo(
    () => groupBySetup ? groupCardsBySetup(cards) : null,
    [groupBySetup, cards],
  );

  // 2026-04-30 v19.10 — sticky "X / N hits" counter in the panel
  // header. Tracks the topmost-visible card via a scroll listener on
  // the closest scrollable ancestor and emits {topIdx, total} to the
  // parent. RAF-throttled so 60fps scrolling stays smooth.
  const wrapperRef = useRef(null);
  useEffect(() => {
    if (!onScanProgress || !wrapperRef.current) return;
    onScanProgress({ topIdx: 0, total: cards.length });

    // Walk up to find the closest overflow-y: auto/scroll ancestor.
    let scrollParent = wrapperRef.current.parentElement;
    while (scrollParent && scrollParent !== document.body) {
      const oy = window.getComputedStyle(scrollParent).overflowY;
      if (oy === 'auto' || oy === 'scroll') break;
      scrollParent = scrollParent.parentElement;
    }
    if (!scrollParent || scrollParent === document.body) return;

    let raf = 0;
    const update = () => {
      raf = 0;
      if (!wrapperRef.current) return;
      const rootTop = scrollParent.getBoundingClientRect().top;
      const cardEls = wrapperRef.current.querySelectorAll('[data-card-index]');
      for (let i = 0; i < cardEls.length; i++) {
        const r = cardEls[i].getBoundingClientRect();
        // First card whose bottom is below the scroll root's top edge
        // is the topmost-visible card. +2px tolerance to avoid
        // flicker on the boundary.
        if (r.bottom > rootTop + 2) {
          const idx = parseInt(cardEls[i].dataset.cardIndex, 10);
          if (!Number.isNaN(idx)) onScanProgress({ topIdx: idx, total: cards.length });
          return;
        }
      }
      // Below all cards (scrolled past) — clamp to last
      onScanProgress({ topIdx: Math.max(cards.length - 1, 0), total: cards.length });
    };

    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };

    scrollParent.addEventListener('scroll', onScroll, { passive: true });
    update();
    return () => {
      if (raf) cancelAnimationFrame(raf);
      scrollParent.removeEventListener('scroll', onScroll);
    };
  }, [cards.length, groupBySetup, collapsedGroups, onScanProgress]);

  // 2026-04-30 v19.11 — Keyboard navigation for power-user workflow.
  //
  //   ↓ / ↑   move a "preview cursor" through cards (visual only —
  //            doesn't reload the chart, so scanning 47 cards isn't
  //            47 chart reloads)
  //   Enter   commits the cursor: opens the chart for that ticker
  //
  // Mouse click still works exactly as before (commits immediately).
  // Pairs with the data-card-index attributes the scroll-counter
  // already uses, so we get free auto-scroll-into-view via
  // `scrollIntoView({block:'nearest'})`.
  const [previewIdx, setPreviewIdx] = useState(-1);

  // Sync the cursor when the parent changes selectedSymbol externally
  // (e.g., from chart click). Keeps Enter and arrows in lockstep.
  useEffect(() => {
    if (!selectedSymbol) return;
    const idx = cards.findIndex(c => c.symbol === selectedSymbol);
    if (idx >= 0) setPreviewIdx(idx);
  }, [selectedSymbol, cards]);

  // Reset the cursor when the deck shrinks below the cursor (e.g.,
  // alerts time out and `cards` rebuilds smaller). Avoids a stale
  // cursor pointing past the end.
  useEffect(() => {
    if (previewIdx >= cards.length) setPreviewIdx(cards.length - 1);
  }, [cards.length, previewIdx]);

  useEffect(() => {
    const onKey = (e) => {
      // Ignore when the operator is typing — text inputs, search
      // boxes (Deep Feed), chat composer, code editors, etc. all
      // need their arrows.
      const t = e.target;
      if (t && t.nodeType === 1) {
        const tag = t.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
            || t.isContentEditable) return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (cards.length === 0) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setPreviewIdx((idx) => Math.min((idx < 0 ? -1 : idx) + 1, cards.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setPreviewIdx((idx) => Math.max((idx < 0 ? cards.length : idx) - 1, 0));
      } else if (e.key === 'Enter') {
        // Only act if there's a cursor — don't surprise the operator
        // when Enter is pressed in some other context.
        if (previewIdx >= 0 && cards[previewIdx]) {
          e.preventDefault();
          onSelectSymbol?.(cards[previewIdx].symbol);
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [cards, previewIdx, onSelectSymbol]);

  // Auto-scroll the preview card into view as the cursor moves.
  // `block:'nearest'` minimises scroll thrash when the card is
  // already visible.
  useEffect(() => {
    if (previewIdx < 0 || !wrapperRef.current) return;
    const el = wrapperRef.current.querySelector(`[data-card-index="${previewIdx}"]`);
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [previewIdx]);

  // Phase 2: auto-promote the top-10 scanner symbols to tick-level live
  // subs. As the ranked list shifts, the diff-based useLiveSubscriptions
  // hook adds new symbols and drops ones that fell out of the top-10.
  // Backend ref-counts handle overlap with ChartPanel / modal subs.
  const topSymbols = useMemo(
    () => cards.slice(0, 10).map((c) => c.symbol).filter(Boolean),
    [cards]
  );
  useLiveSubscriptions(topSymbols, { max: 10 });

  if (cards.length === 0) {
    return (
      <div className="px-3 py-6 text-center text-[13px] text-zinc-500">
        <div className="v5-mono">Scanner idle.</div>
        <div className="mt-1 v5-why-dim">No setups, alerts, or open positions yet.</div>
      </div>
    );
  }

  return (
    <div ref={wrapperRef} data-testid="v5-scanner-cards-list" data-help-id="scanner-panel" className="flex flex-col">
      {/* Wave 3 (#1) — grouping toggle. Tiny chip in the panel header
          row so the operator can flip between FLAT (legacy) and
          GROUPED-BY-SETUP views without leaving the panel. */}
      <div className="flex items-center justify-end gap-1 px-3 py-1 border-b border-zinc-900 bg-zinc-950/80 sticky top-0 z-[5]">
        <button
          type="button"
          data-testid="v5-scanner-group-toggle"
          onClick={toggleGrouping}
          className={`v5-filter-chip ${groupBySetup ? 'active' : ''}`}
          title={groupBySetup ? 'Switch to flat ranked view' : 'Group cards by Market Setup'}
        >
          {groupBySetup ? 'grouped ▾' : 'flat'}
        </button>
      </div>

      {!groupBySetup && cards.map((c, i) => (
        <ScannerCard
          key={c.symbol + c.stage}
          card={c}
          active={selectedSymbol === c.symbol}
          previewed={previewIdx === i}
          onClick={() => onSelectSymbol?.(c.symbol)}
          hoveredSymbol={hoveredSymbol}
          onHoverSymbol={onHoverSymbol}
          dataCardIndex={i}
        />
      ))}

      {groupBySetup && groups && (() => {
        // Walk groups in render order, assigning a flat 0..N-1 index
        // to each card so the scroll-position tracker reports a
        // consistent "card 12 of 47" regardless of grouping mode.
        let flatIdx = 0;
        return groups.map(([setupKey, groupCards]) => {
          const isCollapsed = collapsedGroups.has(setupKey ?? '__OTHER__');
          const label = _humanizeSetup(setupKey);
          const ctCount = groupCards.filter(c => c.is_countertrend).length;
          return (
            <div
              key={setupKey ?? '__OTHER__'}
              data-testid={`v5-scanner-group-${setupKey ?? 'OTHER'}`}
              className="flex flex-col"
            >
              <button
                type="button"
                onClick={() => toggleGroup(setupKey ?? '__OTHER__')}
                className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-zinc-900 bg-zinc-900/40 hover:bg-zinc-900/70 transition-colors"
                data-testid={`v5-scanner-group-header-${setupKey ?? 'OTHER'}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="v5-mono text-[11px] uppercase tracking-widest text-zinc-300 font-bold truncate">
                    {label}
                  </span>
                  <span className="v5-mono text-[11px] text-zinc-500">
                    ({groupCards.length})
                  </span>
                  {ctCount > 0 && (
                    <span className="v5-chip v5-chip-counter-trend" title={`${ctCount} counter-trend trades in this section`}>
                      {ctCount} CT
                    </span>
                  )}
                </div>
                <span className="v5-mono text-[11px] text-zinc-500">
                  {isCollapsed ? '▸' : '▾'}
                </span>
              </button>
              {!isCollapsed && groupCards.map((c) => {
                const idx = flatIdx++;
                return (
                  <ScannerCard
                    key={c.symbol + c.stage}
                    card={c}
                    active={selectedSymbol === c.symbol}
                    previewed={previewIdx === idx}
                    onClick={() => onSelectSymbol?.(c.symbol)}
                    hoveredSymbol={hoveredSymbol}
                    onHoverSymbol={onHoverSymbol}
                    dataCardIndex={idx}
                  />
                );
              })}
              {isCollapsed && (() => { flatIdx += groupCards.length; return null; })()}
            </div>
          );
        });
      })()}
    </div>
  );
};

export default ScannerCardsV5;
