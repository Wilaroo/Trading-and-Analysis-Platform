/**
 * GamePlanStockCard — Per-stock briefing card that renders the enriched
 * narrative returned by `GET /api/journal/gameplan/narrative/{symbol}`.
 *
 * Shipped 2026-05-01 (v19.20) in response to operator feedback that the
 * Morning Briefing "Stocks in play" section was dumping `SYMBOL · Technical
 * Setup` with no guidance. This card renders:
 *
 *   • Setup header + direction + one-line setup description
 *   • Deterministic bullets (key levels, trigger, invalidation) — always
 *     render, even when Ollama is offline.
 *   • Key-levels grid (Entry / Stop / T1 / T2 / VWAP / HOD / LOD / ORH / ORL)
 *   • Trader narrative paragraph from Ollama GPT-OSS 120B (optional)
 *   • Inline clickable $TICKER chips — clicking a chip dispatches the
 *     `sentcom:focus-symbol` custom event so other panels (quick-chart,
 *     chat, deep feed) can react.
 *
 * Lazy-loads the narrative only when the card is expanded so a 5-stock
 * briefing doesn't fan out 5 simultaneous LLM calls on modal open.
 */
import React, { memo, useEffect, useState, useCallback, useMemo } from 'react';
import { ChevronRight, TrendingUp, TrendingDown, Loader2 } from 'lucide-react';
import api from '../../../utils/api';

const fmtPrice = (v) =>
  v == null || Number.isNaN(Number(v)) ? '—' : `$${Number(v).toFixed(2)}`;

// Regex used both for parsing `$TICKER` tokens in narrative text and for
// drawing inline clickable chips. Capture group lets us reconstruct the
// text with tickers swapped for interactive spans.
const TICKER_TOKEN = /\$([A-Z]{1,5})\b/g;

/**
 * Broadcast a symbol-focus intent. Listeners elsewhere in the app can
 * `window.addEventListener('sentcom:focus-symbol', fn)` and open a quick
 * chart, scroll their stream, etc.
 */
const focusSymbol = (symbol) => {
  try {
    window.dispatchEvent(
      new CustomEvent('sentcom:focus-symbol', { detail: { symbol } }),
    );
  } catch {
    // no-op — custom events are a best-effort enrichment.
  }
};

/**
 * Render a string with any `$TICKER` tokens converted to clickable chips.
 * Pure function; no hooks so we can use it inside bullet lists too.
 */
const renderWithTickerChips = (text, onClickSymbol) => {
  if (!text) return null;
  const pieces = [];
  let lastIndex = 0;
  let match;
  TICKER_TOKEN.lastIndex = 0;
  while ((match = TICKER_TOKEN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      pieces.push(text.slice(lastIndex, match.index));
    }
    const sym = match[1];
    pieces.push(
      <button
        key={`${match.index}-${sym}`}
        type="button"
        data-testid={`gp-card-ticker-chip-${sym}`}
        onClick={(e) => {
          e.stopPropagation();
          onClickSymbol(sym);
        }}
        className="inline-flex items-center rounded px-1.5 py-0 mx-0.5 v5-mono text-[12px] font-bold text-violet-300 bg-violet-500/10 hover:bg-violet-500/20 hover:text-violet-200 transition-colors border border-violet-500/20"
      >
        ${sym}
      </button>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    pieces.push(text.slice(lastIndex));
  }
  return pieces;
};

const LevelCell = ({ label, value, highlight = false, testid }) => (
  <div
    data-testid={testid}
    className={`flex flex-col gap-0.5 py-1.5 px-2 rounded ${highlight ? 'bg-zinc-900/70 border border-zinc-800' : ''}`}
  >
    <span className="v5-mono text-[10px] uppercase tracking-widest text-zinc-500">
      {label}
    </span>
    <span className={`v5-mono text-[13px] ${value === '—' ? 'text-zinc-600' : 'text-zinc-200'}`}>
      {value}
    </span>
  </div>
);

const GamePlanStockCard = memo(({ stock, date, marketBias, onSymbolClick }) => {
  const symbol = (stock?.symbol || stock?.ticker || '').toUpperCase();
  const [expanded, setExpanded] = useState(false);
  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSymbolClick = useCallback(
    (sym) => {
      focusSymbol(sym);
      if (onSymbolClick) onSymbolClick(sym);
    },
    [onSymbolClick],
  );

  const loadNarrative = useCallback(async () => {
    if (!symbol || card || loading) return;
    setLoading(true);
    setError(null);
    try {
      const url = `/api/journal/gameplan/narrative/${encodeURIComponent(symbol)}${date ? `?date=${date}` : ''}`;
      const res = await api.get(url, { timeout: 60000 });
      const j = res?.data;
      if (!j?.success || !j?.card) throw new Error('Empty card payload');
      setCard(j.card);
    } catch (e) {
      setError(e?.message || 'Failed to load narrative');
    } finally {
      setLoading(false);
    }
  }, [symbol, date, card, loading]);

  useEffect(() => {
    if (expanded) loadNarrative();
  }, [expanded, loadNarrative]);

  // Precompute display strings so JSX stays clean.
  const direction = (card?.direction || stock?.direction || 'long').toLowerCase();
  const setupType = card?.setup_type || stock?.setup_type || '';
  const prettySetup = setupType
    ? setupType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    : stock?.catalyst || 'Technical Setup';
  const DirIcon = direction === 'short' ? TrendingDown : TrendingUp;
  const dirAccent =
    direction === 'short' ? 'text-rose-400' : 'text-emerald-400';

  const levels = card?.levels || stock?.key_levels || {};
  const bullets = card?.bullets || [];
  const narrative = card?.narrative;

  // If we have levels pre-hydrated from the stock_in_play (i.e. the
  // gameplan_service already filled key_levels) we can render the grid even
  // BEFORE the user clicks expand, which gives operators an instant "at a
  // glance" view of all 5 stocks without any network round-trip.
  const instantLevels = useMemo(
    () => ({
      entry: levels.entry,
      stop: levels.stop,
      target_1: levels.target_1,
      target_2: levels.target_2,
      current_price: levels.current_price,
      vwap: levels.vwap,
      high_of_day: levels.high_of_day,
      low_of_day: levels.low_of_day,
      or_high: levels.or_high,
      or_low: levels.or_low,
      support: levels.support,
      resistance: levels.resistance,
    }),
    [levels],
  );

  const hasAnyLevel = Object.values(instantLevels).some(
    (v) => v != null && v !== '' && v !== 0,
  );

  return (
    <div
      data-testid={`gp-card-${symbol}`}
      className="rounded-md border border-zinc-800 bg-zinc-950/60 overflow-hidden"
    >
      {/* Compact header — always visible */}
      <button
        type="button"
        data-testid={`gp-card-toggle-${symbol}`}
        onClick={() => setExpanded((x) => !x)}
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-zinc-900/50 transition-colors text-left"
      >
        <ChevronRight
          className={`w-4 h-4 text-zinc-500 transition-transform ${expanded ? 'rotate-90' : ''}`}
        />
        <button
          type="button"
          data-testid={`gp-card-symbol-${symbol}`}
          onClick={(e) => {
            e.stopPropagation();
            handleSymbolClick(symbol);
          }}
          className="v5-mono text-[14px] font-bold text-violet-300 hover:text-violet-100 transition-colors"
        >
          ${symbol}
        </button>
        <DirIcon className={`w-3.5 h-3.5 ${dirAccent}`} />
        <span className="v5-mono text-[11px] uppercase tracking-wider text-zinc-400 truncate flex-1">
          {prettySetup}
        </span>
        {levels.entry && (
          <span className="v5-mono text-[11px] text-zinc-500 hidden sm:inline">
            @ {fmtPrice(levels.entry)}
          </span>
        )}
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-zinc-900 px-3 py-3 space-y-3">
          {card?.setup_description && (
            <div
              data-testid={`gp-card-description-${symbol}`}
              className="text-[12px] text-zinc-400 italic v5-why"
            >
              {card.setup_description}
            </div>
          )}

          {/* Bullets — always render (deterministic) */}
          {bullets.length > 0 && (
            <ul
              data-testid={`gp-card-bullets-${symbol}`}
              className="space-y-1 text-[12.5px] text-zinc-300"
            >
              {bullets.map((b, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-zinc-600 shrink-0">›</span>
                  <span>{renderWithTickerChips(b, handleSymbolClick)}</span>
                </li>
              ))}
            </ul>
          )}

          {/* Key-levels grid */}
          {hasAnyLevel && (
            <div
              data-testid={`gp-card-levels-${symbol}`}
              className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-1.5 pt-1"
            >
              <LevelCell label="Entry"    value={fmtPrice(instantLevels.entry)} highlight
                         testid={`gp-card-level-entry-${symbol}`} />
              <LevelCell label="Stop"     value={fmtPrice(instantLevels.stop)}  highlight
                         testid={`gp-card-level-stop-${symbol}`} />
              <LevelCell label="T1"       value={fmtPrice(instantLevels.target_1)}
                         testid={`gp-card-level-t1-${symbol}`} />
              <LevelCell label="T2"       value={fmtPrice(instantLevels.target_2)}
                         testid={`gp-card-level-t2-${symbol}`} />
              <LevelCell label="VWAP"     value={fmtPrice(instantLevels.vwap)}
                         testid={`gp-card-level-vwap-${symbol}`} />
              <LevelCell label="Price"    value={fmtPrice(instantLevels.current_price)}
                         testid={`gp-card-level-price-${symbol}`} />
              <LevelCell label="HOD"      value={fmtPrice(instantLevels.high_of_day)}
                         testid={`gp-card-level-hod-${symbol}`} />
              <LevelCell label="LOD"      value={fmtPrice(instantLevels.low_of_day)}
                         testid={`gp-card-level-lod-${symbol}`} />
              <LevelCell label="OR High"  value={fmtPrice(instantLevels.or_high)}
                         testid={`gp-card-level-orh-${symbol}`} />
              <LevelCell label="OR Low"   value={fmtPrice(instantLevels.or_low)}
                         testid={`gp-card-level-orl-${symbol}`} />
              <LevelCell label="Support"  value={fmtPrice(instantLevels.support)}
                         testid={`gp-card-level-sup-${symbol}`} />
              <LevelCell label="Resist."  value={fmtPrice(instantLevels.resistance)}
                         testid={`gp-card-level-res-${symbol}`} />
            </div>
          )}

          {/* AI narrative paragraph */}
          <div data-testid={`gp-card-narrative-wrap-${symbol}`}>
            <div className="flex items-center justify-between mb-1">
              <span className="v5-mono text-[10px] uppercase tracking-widest text-zinc-500">
                AI Read {card?.llm_used ? '(gpt-oss 120B)' : ''}
              </span>
              {loading && (
                <Loader2 className="w-3 h-3 text-violet-400 animate-spin" />
              )}
            </div>
            {error && (
              <div className="text-[12px] text-rose-400/80 italic">
                Narrative unavailable ({error}). Bullets above still apply.
              </div>
            )}
            {!error && narrative && (
              <div
                data-testid={`gp-card-narrative-${symbol}`}
                className="text-[13px] leading-relaxed text-zinc-300"
              >
                {renderWithTickerChips(narrative, handleSymbolClick)}
              </div>
            )}
            {!error && !narrative && !loading && card && (
              <div className="text-[12px] text-zinc-500 italic">
                AI narrative unavailable — Ollama offline or quiet. The
                deterministic bullets above cover the plan.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

GamePlanStockCard.displayName = 'GamePlanStockCard';

export default GamePlanStockCard;
export { renderWithTickerChips, focusSymbol };
