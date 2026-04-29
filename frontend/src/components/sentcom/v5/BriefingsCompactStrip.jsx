/**
 * BriefingsCompactStrip — 4 compact pulse-buttons for the V5 right
 * sidebar / TopBar. Replaces the wide `BriefingsV5` panel when the
 * operator wants more vertical room for the live action surfaces
 * (Stream, Positions, SentCom Intelligence) — see 2026-04-29
 * afternoon-10 layout reorg.
 *
 * Each button represents one of the 4 daily briefings:
 *   - Morning Prep        (pre-open)
 *   - Mid-Day Recap       (lunch window)
 *   - Power Hour          (pre-close)
 *   - End-of-Day Recap    (after close)
 *
 * Pulse / highlight states (`statusFor` math, lifted from `BriefingsV5`):
 *   - `pending`  — window not yet open. Dim. Operator can still click
 *                  to view the staged briefing if data is available.
 *   - `active`   — window is currently open. **Pulses + glows.** This
 *                  is the "click me" state.
 *   - `passed`   — window closed. Static. Click still opens the
 *                  recorded briefing for review.
 *
 * Click → modal shows the full original briefing card (re-uses
 * `MorningPrepCard` / `MidDayRecapCard` / `PowerHourCard` /
 * `CloseRecapCard` from BriefingsV5 with `expanded={true}` so the
 * operator sees the full rendering, not a re-implementation).
 */
import React, { useState } from 'react';
import { Sun, Coffee, Zap, Moon, X } from 'lucide-react';
import {
  MorningPrepCard,
  MidDayRecapCard,
  PowerHourCard,
  CloseRecapCard,
  statusFor,
} from './BriefingsV5';
import { useMorningBriefing } from './useMorningBriefing';

const BRIEFINGS = [
  {
    key: 'morning',
    label: 'Morning Prep',
    short: 'AM',
    icon: Sun,
    // Active during the pre-open window (8:30 - 9:35 ET).
    windowStart: 8 * 60 + 30,
    windowEnd: 9 * 60 + 35,
  },
  {
    key: 'midday',
    label: 'Mid-Day Recap',
    short: 'MID',
    icon: Coffee,
    // Active during lunch (11:30 - 13:00 ET).
    windowStart: 11 * 60 + 30,
    windowEnd: 13 * 60,
  },
  {
    key: 'powerhour',
    label: 'Power Hour',
    short: 'PH',
    icon: Zap,
    // Active 14:30 - 16:00 ET.
    windowStart: 14 * 60 + 30,
    windowEnd: 16 * 60,
  },
  {
    key: 'close',
    label: 'EOD Recap',
    short: 'EOD',
    icon: Moon,
    // Active 16:00 - 17:00 ET.
    windowStart: 16 * 60,
    windowEnd: 17 * 60,
  },
];

const STATE_STYLES = {
  active:
    'border-emerald-400/60 bg-emerald-500/10 text-emerald-200 ' +
    'shadow-[0_0_18px_-2px_rgba(16,185,129,0.55)] animate-pulse-glow',
  pending: 'border-zinc-700 bg-zinc-900/60 text-zinc-400 hover:bg-zinc-800',
  passed:
    'border-zinc-800 bg-zinc-950 text-zinc-500 hover:bg-zinc-900 ' +
    'hover:text-zinc-300',
};

const StateDot = ({ state }) => {
  const cls =
    state === 'active'
      ? 'bg-emerald-400 animate-pulse'
      : state === 'pending'
        ? 'bg-amber-500/60'
        : 'bg-zinc-600';
  return (
    <span
      className={`inline-block w-1.5 h-1.5 rounded-full ${cls}`}
      data-testid={`briefing-state-dot-${state}`}
    />
  );
};

const BriefingButton = ({ def, state, onClick }) => {
  const Icon = def.icon;
  return (
    <button
      onClick={onClick}
      className={`relative flex items-center gap-2 px-3 py-1.5 rounded-md
                  border text-xs font-medium transition-all duration-200
                  ${STATE_STYLES[state] || STATE_STYLES.pending}`}
      data-testid={`briefing-btn-${def.key}`}
      data-state={state}
      title={`${def.label} — ${state}`}
    >
      <Icon className="w-3.5 h-3.5" />
      <span className="hidden sm:inline">{def.label}</span>
      <span className="sm:hidden">{def.short}</span>
      <StateDot state={state} />
    </button>
  );
};

const BriefingModal = ({ def, briefing, loading, positions, totalPnl,
                         onClose, onSymbolClick, onOpenDeepDive }) => {
  const cardCommon = {
    expanded: true,
    onToggle: () => {}, // no-op — modal owns expanded state
    onSymbolClick,
    onOpenDeepDive,
  };
  let card = null;
  if (def.key === 'morning') {
    card = <MorningPrepCard data={briefing} loading={loading} {...cardCommon} />;
  } else if (def.key === 'midday') {
    card = <MidDayRecapCard
      positions={positions} totalPnl={totalPnl} briefing={briefing}
      {...cardCommon} />;
  } else if (def.key === 'powerhour') {
    card = <PowerHourCard
      positions={positions} totalPnl={totalPnl} briefing={briefing}
      {...cardCommon} />;
  } else {
    card = <CloseRecapCard
      positions={positions} totalPnl={totalPnl} {...cardCommon} />;
  }
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center
                 bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
      data-testid="briefing-modal-backdrop"
    >
      <div
        className="bg-zinc-950 border border-zinc-800 rounded-xl
                   shadow-2xl w-full max-w-[min(144rem,95vw)] max-h-[85vh]
                   overflow-y-auto v5-scroll"
        onClick={(e) => e.stopPropagation()}
        data-testid={`briefing-modal-${def.key}`}
      >
        <div className="flex items-center justify-between px-4 py-3
                        border-b border-zinc-800 sticky top-0 bg-zinc-950 z-10">
          <div className="flex items-center gap-2">
            <def.icon className="w-4 h-4 text-emerald-400" />
            <span className="text-sm font-semibold text-white">
              {def.label}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-zinc-800 text-zinc-400
                       hover:text-white transition-colors"
            data-testid="briefing-modal-close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-2">{card}</div>
      </div>
    </div>
  );
};

export const BriefingsCompactStrip = ({
  context,
  positions,
  totalPnl,
  onSymbolClick,
  onOpenDeepDive,
  className = '',
}) => {
  const { loading, data } = useMorningBriefing({ refreshMs: 120_000 });
  const [openKey, setOpenKey] = useState(null);

  const briefing = data || {
    game_plan: context?.game_plan,
    drc: context?.drc,
    scanner: context?.scanner,
    bot: context?.bot,
  };

  const openDef = openKey ? BRIEFINGS.find((b) => b.key === openKey) : null;

  return (
    <div
      data-testid="briefings-compact-strip"
      className={`flex items-center gap-2 flex-wrap ${className}`}
    >
      {BRIEFINGS.map((def) => {
        const state = statusFor(def.windowStart, def.windowEnd);
        return (
          <BriefingButton
            key={def.key}
            def={def}
            state={state}
            onClick={() => setOpenKey(def.key)}
          />
        );
      })}
      {openDef && (
        <BriefingModal
          def={openDef}
          briefing={briefing}
          loading={loading}
          positions={positions}
          totalPnl={totalPnl}
          onClose={() => setOpenKey(null)}
          onSymbolClick={onSymbolClick}
          onOpenDeepDive={onOpenDeepDive}
        />
      )}
    </div>
  );
};

export default BriefingsCompactStrip;
