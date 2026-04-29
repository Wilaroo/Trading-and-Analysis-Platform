/**
 * BriefingsCompactStrip — 4 pulse-buttons for the V5 right sidebar / TopBar.
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
 * 2026-04-29 morning rewire (operator-flagged): clicking a button now
 * routes directly to the parent's deep-dive modal (`onOpenDeepDive(key)`)
 * — the previous intermediate compact-modal step rendered a stripped
 * card with only ~5 lines of detail, which the operator rightly called
 * "pointless". Buttons now jump straight to the full-screen briefing
 * surface. The deep-dive modal owns its own `briefingKey`-aware
 * rendering for morning / midday / powerhour / eod variants.
 */
import React from 'react';
import { Sun, Coffee, Zap, Moon } from 'lucide-react';
import { statusFor } from './BriefingsV5';

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
      className={`relative flex items-center gap-2 px-3 py-2 rounded-md
                  border text-sm font-medium transition-all duration-200
                  ${STATE_STYLES[state] || STATE_STYLES.pending}`}
      data-testid={`briefing-btn-${def.key}`}
      data-state={state}
      title={`${def.label} — ${state}`}
    >
      <Icon className="w-4 h-4" />
      <span className="hidden sm:inline">{def.label}</span>
      <span className="sm:hidden">{def.short}</span>
      <StateDot state={state} />
    </button>
  );
};

export const BriefingsCompactStrip = ({
  onOpenDeepDive,
  className = '',
}) => {
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
            // Operator-flagged 2026-04-29: skip the intermediate compact
            // modal entirely — buttons jump straight to the full deep-dive.
            // Parent owns the modal; we just hand it the briefing key.
            onClick={() => onOpenDeepDive && onOpenDeepDive(def.key)}
          />
        );
      })}
    </div>
  );
};

export default BriefingsCompactStrip;
