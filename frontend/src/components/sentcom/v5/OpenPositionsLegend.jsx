/**
 * OpenPositionsLegend — v19.34.2 (2026-05-04)
 *
 * `?` button anchored to the Open Positions panel header that opens a
 * popover explaining the REAL / SHADOW / MIXED model + chip semantics.
 *
 * Operator-recurring confusion was: "I see 12 positions but I can't
 * tell which are real, which are paper, and which are AI-only shadow
 * trades that never actually fired." The legend gives a 30-second
 * scannable answer + links to the Diagnostics → Shadow Decisions tab.
 *
 * Closes on click-outside or Escape. Pure presentational; no API.
 */
import React, { useEffect, useRef, useState } from 'react';

const _PROVENANCE_ROWS = [
  { name: 'BOT',         cls: 'bg-zinc-900 text-zinc-400 border-zinc-700',         desc: 'Default. The bot\'s own evaluation + execution path opened this trade. Setup math, R:R check, all green.' },
  { name: 'RECONCILED',  cls: 'bg-fuchsia-950/60 text-fuchsia-300 border-fuchsia-800', desc: 'Bot ADOPTED an IB orphan it did not open. Could be carry-over from prior session, manual TWS click, or stale bracket. SL/PT may be synthetic defaults. Manage carefully.' },
  { name: '⚠ CONFLICT',  cls: 'bg-amber-950/70 text-amber-300 border-amber-700',   desc: 'Reconciled position whose recent setup verdicts were REJECT (e.g. R:R below min). The bot inherited a position it would have rejected. Strongly consider closing or overriding SL/PT.' },
];

const _ROWS = [
  {
    name: 'PAPER',
    chip: 'bg-amber-950/60 text-amber-300 border-amber-800',
    desc: 'REAL trade · paper IB account (DU* prefix). Money is at risk inside the IB simulator. Bot is actively managing this row.',
  },
  {
    name: 'LIVE',
    chip: 'bg-rose-950/60 text-rose-300 border-rose-800',
    desc: 'REAL trade · live IB account. Real money is at risk. Bot is actively managing this row.',
  },
  {
    name: 'SHADOW',
    chip: 'bg-sky-950/60 text-sky-300 border-sky-800',
    desc: 'AI council "would have fired" record. NEVER touched IB; no money at risk. Lives only in the `shadow_decisions` collection.',
    note: 'Shadow trades NEVER appear in this Open Positions panel. They are only visible in Diagnostics → Shadow Decisions.',
  },
  {
    name: 'MIXED',
    chip: 'bg-slate-800 text-slate-200 border-slate-600',
    desc: 'Symbol has bot_trade rows of multiple concrete types (paper + live). Usually means the operator switched accounts mid-day and there are stale legs to clean up.',
  },
  {
    name: '?',
    chip: 'bg-slate-900/60 text-slate-400 border-slate-700',
    desc: 'No account context — pusher RPC unreachable. The chip falls back here only when the v19.34.1 pusher-account fallback ALSO fails. See `/api/system/account-mode` for the definitive answer.',
  },
];

const _QUOTE_ROWS = [
  { state: 'FRESH',  cls: 'bg-cyan-950/60 text-cyan-300 border-cyan-800',   desc: 'Last L1 quote < 5s old. Bot can fire stops on this position immediately.' },
  { state: 'AMBER',  cls: 'bg-amber-950/60 text-amber-300 border-amber-800', desc: 'Last L1 quote 5-30s old. Stop checks still run but you may see slight latency.' },
  { state: 'STALE',  cls: 'bg-rose-950/60 text-rose-300 border-rose-800',   desc: 'Last L1 quote > 30s old. Bot SKIPS stop checks — only IB-side bracket protects this row. v19.34.2 auto-requests pusher resubscribe to recover.' },
];

export default function OpenPositionsLegend() {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        data-testid="open-positions-legend-toggle"
        onClick={() => setOpen(v => !v)}
        title="Legend: REAL vs SHADOW vs MIXED (paper/live chip semantics + quote freshness)"
        className={`inline-flex items-center justify-center w-4 h-4 rounded-full border text-[10px] font-bold transition-colors ${
          open
            ? 'bg-cyan-900/40 text-cyan-300 border-cyan-700'
            : 'bg-zinc-900 text-zinc-500 border-zinc-700 hover:text-zinc-200'
        }`}
        aria-label="Open Positions legend"
      >
        ?
      </button>
      {open && (
        <div
          data-testid="open-positions-legend-popover"
          role="dialog"
          className="absolute right-0 top-6 z-50 w-[420px] max-w-[90vw] bg-zinc-950 border border-zinc-700 rounded-md shadow-2xl"
        >
          <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-200">
              Open Positions · Legend
            </span>
            <button
              type="button"
              data-testid="open-positions-legend-close"
              onClick={() => setOpen(false)}
              className="text-zinc-500 hover:text-zinc-200 text-xs"
              aria-label="Close legend"
            >×</button>
          </div>
          <div className="px-3 py-2.5 text-[11px] leading-relaxed text-zinc-300 space-y-3">
            <section>
              <div className="text-zinc-500 uppercase tracking-wider text-[10px] mb-1">Provenance chip (RECONCILED / CONFLICT)</div>
              <ul className="space-y-1.5">
                {_PROVENANCE_ROWS.map((r) => (
                  <li key={r.name} className="flex items-start gap-2">
                    <span className={`shrink-0 px-1.5 py-0 rounded border text-[10px] uppercase tracking-wider font-bold ${r.cls}`}>
                      {r.name}
                    </span>
                    <span className="text-zinc-300">{r.desc}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <div className="text-zinc-500 uppercase tracking-wider text-[10px] mb-1">Trade origin (mode chip)</div>
              <ul className="space-y-1.5">
                {_ROWS.map((r) => (
                  <li key={r.name} className="flex items-start gap-2">
                    <span className={`shrink-0 px-1.5 py-0 rounded border text-[10px] uppercase tracking-wider font-bold ${r.chip}`}>
                      {r.name}
                    </span>
                    <span>
                      <span className="text-zinc-300">{r.desc}</span>
                      {r.note && (
                        <span className="block text-zinc-500 mt-0.5 italic">{r.note}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <div className="text-zinc-500 uppercase tracking-wider text-[10px] mb-1">Quote freshness (right-side chip)</div>
              <ul className="space-y-1.5">
                {_QUOTE_ROWS.map((r) => (
                  <li key={r.state} className="flex items-start gap-2">
                    <span className={`shrink-0 px-1.5 py-0 rounded border text-[10px] uppercase tracking-wider font-bold ${r.cls}`}>
                      {r.state}
                    </span>
                    <span className="text-zinc-300">{r.desc}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="border-t border-zinc-800 pt-2 text-[10px] text-zinc-500">
              <div>
                Looking for what-would-have-happened on the trades the bot
                <em className="not-italic"> didn't </em>
                fire? Open
                <span className="mx-1 px-1 py-0 rounded bg-zinc-900 border border-zinc-800 text-zinc-300">Diagnostics → Shadow Decisions</span>
                — that's the only place SHADOW rows live.
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
