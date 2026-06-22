/**
 * WhyTraceModal — v19.34.285 (UI Track A · A3)
 *
 * Plain-language "why did the bot do this?" trace. Renders the trade's life
 * as 7 sequential stages — scan → setup → grade → gate → size → manage → exit —
 * each with a DONE / NOW / NEXT / SKIPPED status and a one-line explanation in
 * human words (no jargon, no raw scores without context).
 *
 * Data: the card object (passed through tqsDrawerBus) merged with the persisted
 * GET /api/tqs/card-detail payload the drawer already fetched. No extra request.
 * Opened from the TQS drill-down drawer header; closes on Esc / backdrop / ✕.
 */
import React, { useEffect, useMemo } from 'react';
import {
  X, Search, Crosshair, Award, ShieldCheck, Scale, Activity, LogOut,
} from 'lucide-react';

// 5-stage pipeline the cards use → index into the 7 narrative stages.
const PIPE_ORDER = ['scan', 'eval', 'order', 'manage', 'close'];
// scan→[scan,setup,grade], eval→+gate, order→+size, manage→+manage, close→+exit
const PIPE_TO_REACHED = { scan: 2, eval: 3, order: 4, manage: 5, close: 6 };

const fmtPx = (v) => (v == null || Number.isNaN(Number(v)) ? '—' : `$${Number(v).toFixed(2)}`);
const fmtR = (v) => (v == null || Number.isNaN(Number(v)) ? null : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}R`);
const fmtPct = (v) => {
  if (v == null || Number.isNaN(Number(v))) return null;
  const n = Number(v);
  return `${(Math.abs(n) <= 1 ? n * 100 : n).toFixed(0)}%`;
};
const titleCase = (s) => String(s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

const PILLAR_LABEL = { setup: 'Setup', technical: 'Technical', fundamental: 'Fundamental', context: 'Context', execution: 'Execution' };
const GRADE_RANK = { 'A+': 9, A: 8, 'B+': 7, B: 6, 'C+': 5, C: 4, D: 3, F: 1 };

const STATUS_STYLE = {
  done: { label: 'DONE', cls: 'text-emerald-300 border-emerald-700/60 bg-emerald-950/40' },
  now: { label: 'NOW', cls: 'text-sky-300 border-sky-700/60 bg-sky-950/40' },
  next: { label: 'NEXT', cls: 'text-zinc-400 border-zinc-700/60 bg-zinc-900/40' },
  skipped: { label: 'STOOD DOWN', cls: 'text-amber-300 border-amber-700/60 bg-amber-950/40' },
};

function buildStages(card = {}, detail = {}) {
  const c = card || {};
  const d = detail || {};
  const stage = c.stage || 'scan';
  const isVeto = stage === 'veto';
  const reached = isVeto ? 3 : (PIPE_TO_REACHED[stage] ?? 2);

  const setup = titleCase(d.setup_type || c.setup_type || c.scoring_style || 'setup');
  const dir = String(d.direction || c.direction || 'long').toLowerCase();
  const dirWord = dir === 'short' ? 'short' : 'long';
  const score = d.tqs_score ?? c.tqs_score;
  const grade = d.tqs_grade || c.tqs_grade || '';
  const pillars = (d.breakdown && d.breakdown.pillar_grades) || c.tqs_pillar_grades || {};
  const perf = d.setup_perf || {};
  const pos = d.position || {};
  const stop = pos.stop_price ?? c.stop_price;
  const target = pos.target_price ?? c.target_price ?? (Array.isArray(c.target_prices) ? c.target_prices[0] : null);
  const entry = pos.entry_price ?? c.trigger_price ?? c.current_price;
  const shares = pos.shares ?? c.shares ?? c.sizing;
  const rr = c.risk_reward;

  // strongest / weakest pillar
  const ranked = Object.entries(pillars)
    .filter(([, g]) => GRADE_RANK[String(g).toUpperCase()])
    .sort((a, b) => GRADE_RANK[String(b[1]).toUpperCase()] - GRADE_RANK[String(a[1]).toUpperCase()]);
  const strongest = ranked[0] ? PILLAR_LABEL[ranked[0][0]] || ranked[0][0] : null;
  const weakest = ranked.length > 1 ? PILLAR_LABEL[ranked[ranked.length - 1][0]] || ranked[ranked.length - 1][0] : null;

  // catalyst / gap one-liner
  const catalyst = d.catalyst_tag ? titleCase(d.catalyst_tag) : null;
  const gap = d.gap_pct != null ? `gap ${fmtPct(d.gap_pct)}` : null;
  const catBits = [catalyst, gap].filter(Boolean).join(' · ');

  // gate reasoning from bot text (skip lines)
  const botText = String(c.bot_text || '').trim();

  const statusFor = (idx) => {
    if (isVeto && idx === 3) return 'skipped';
    if (isVeto && idx > 3) return 'next';
    if (idx <= reached) return 'done';
    if (idx === reached + 1) return 'now';
    return 'next';
  };

  return [
    {
      key: 'scan', icon: Search, label: 'Scan',
      title: `Flagged ${c.symbol || ''} as a ${setup} ${dirWord} candidate`,
      lines: [catBits ? `Catalyst context: ${catBits}.` : 'No specific catalyst — surfaced on pattern + relative strength.'],
    },
    {
      key: 'setup', icon: Crosshair, label: 'Setup',
      title: `Recognized the ${setup} pattern`,
      lines: [
        perf.win_rate != null
          ? `30-day track record for this setup: ${fmtPct(perf.win_rate)} win${perf.avg_r != null ? ` · avg ${fmtR(perf.avg_r)}` : ''}${perf.sample_size != null ? ` · n=${perf.sample_size}` : ''}.`
          : 'No 30-day sample on this exact setup yet.',
        perf.expected_value_r != null ? `Expected value per trade: ${fmtR(perf.expected_value_r)}.` : null,
      ].filter(Boolean),
    },
    {
      key: 'grade', icon: Award, label: 'Grade',
      title: score != null ? `Quality score ${Math.round(score)} (grade ${grade || '—'})` : 'Quality score pending',
      lines: [
        strongest ? `Strongest pillar: ${strongest}${weakest ? `; weakest: ${weakest}.` : '.'}` : 'Per-pillar breakdown not captured for this card.',
        'Weighs 5 pillars — setup, technical, fundamental, context, execution.',
      ],
    },
    {
      key: 'gate', icon: ShieldCheck, label: 'Gate',
      title: isVeto ? 'Stood down at the confidence gate' : (statusFor(3) === 'done' ? 'Cleared the confidence gate' : 'Confidence gate'),
      lines: [
        isVeto
          ? (botText || 'Did not meet the bar for this setup — passed rather than force a borderline trade.')
          : (d.tqs_action ? `Verdict: ${d.tqs_action}.` : 'Compares the score against the per-style action threshold.'),
      ],
    },
    {
      key: 'size', icon: Scale, label: 'Size',
      title: shares != null ? `Sized to ${shares} shares` : 'Position sizing',
      lines: [shares != null ? 'Sized by the risk model so a stop-out costs ~1R.' : 'On a take, size is set by the R-based risk model (≈1R to the stop).'],
    },
    {
      key: 'manage', icon: Activity, label: 'Manage',
      title: stop != null || target != null ? `Bracket: stop ${fmtPx(stop)} → target ${fmtPx(target)}` : 'Trade management',
      lines: [
        entry != null ? `Reference entry ${fmtPx(entry)}${rr ? ` · ${rr}` : ''}.` : (rr ? `Planned reward:risk ${rr}.` : 'Stop and target are set at entry and trailed by the manager.'),
      ],
    },
    {
      key: 'exit', icon: LogOut, label: 'Exit',
      title: stage === 'close'
        ? `Closed ${c.closed_outcome === 'win' ? 'a winner' : c.closed_outcome === 'loss' ? 'a loser' : 'out'}`
        : 'Exit plan',
      lines: [
        stage === 'close'
          ? (c.bot_text || 'Position closed.')
          : `Exits at the target (${fmtPx(target)}) or the stop (${fmtPx(stop)}) — or earlier if the thesis is invalidated.`,
      ],
    },
  ].map((s, i) => ({ ...s, status: statusFor(i) }));
}

const WhyTraceModal = ({ open, onClose, card, detail }) => {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    if (open) document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const stages = useMemo(() => buildStages(card, detail), [card, detail]);
  if (!open) return null;

  const symbol = (card && card.symbol) || (detail && detail.symbol) || '';

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4" data-testid="why-trace-modal">
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        data-testid="why-trace-backdrop"
      />
      <div className="relative z-[81] w-full max-w-xl max-h-[88vh] overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-zinc-800">
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">Why-Trace</span>
            <span className="v5-mono text-xl font-bold text-white tracking-tight truncate">
              {symbol} <span className="text-zinc-500 text-sm font-normal">· how the bot got here</span>
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            data-testid="why-trace-close"
            className="text-zinc-500 hover:text-zinc-200 transition-colors shrink-0"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Stages */}
        <div className="flex-1 overflow-y-auto v5-scroll px-5 py-4">
          <ol className="relative border-l border-zinc-800 ml-3">
            {stages.map((s, i) => {
              const Icon = s.icon;
              const st = STATUS_STYLE[s.status] || STATUS_STYLE.next;
              const dim = s.status === 'next';
              return (
                <li key={s.key} className="mb-5 ml-6 last:mb-0" data-testid={`why-trace-stage-${s.key}`}>
                  <span
                    className={`absolute -left-[13px] flex h-6 w-6 items-center justify-center rounded-full border ${
                      s.status === 'done' ? 'border-emerald-700 bg-emerald-950'
                        : s.status === 'now' ? 'border-sky-600 bg-sky-950'
                        : s.status === 'skipped' ? 'border-amber-700 bg-amber-950'
                        : 'border-zinc-700 bg-zinc-900'
                    }`}
                  >
                    <Icon className={`h-3 w-3 ${
                      s.status === 'done' ? 'text-emerald-300'
                        : s.status === 'now' ? 'text-sky-300'
                        : s.status === 'skipped' ? 'text-amber-300'
                        : 'text-zinc-500'
                    }`} />
                  </span>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500">{i + 1}. {s.label}</span>
                    <span className={`text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded border ${st.cls}`}>{st.label}</span>
                  </div>
                  <p className={`mt-0.5 text-[13px] font-semibold ${dim ? 'text-zinc-400' : 'text-zinc-100'}`}>{s.title}</p>
                  {s.lines.map((ln, k) => (
                    <p key={k} className={`text-[12px] leading-snug ${dim ? 'text-zinc-600' : 'text-zinc-400'}`}>{ln}</p>
                  ))}
                </li>
              );
            })}
          </ol>
        </div>

        <div className="px-5 py-2.5 border-t border-zinc-800 text-[10px] text-zinc-600">
          Plain-language trace · grades & levels reflect what the bot actually used for this trade.
        </div>
      </div>
    </div>
  );
};

export default WhyTraceModal;
export { WhyTraceModal };
