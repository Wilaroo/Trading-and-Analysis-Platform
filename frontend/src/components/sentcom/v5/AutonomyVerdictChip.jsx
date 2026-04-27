/**
 * AutonomyVerdictChip — permanent at-a-glance "am I cleared to flip
 * auto-execute?" indicator. Renders next to the SENTCOM wordmark in the
 * V5 header so the operator never has to open a modal to know whether
 * autonomous trading is gated by a blocker.
 *
 * Verdict source: `useAutonomyReadiness()` (canonical 30s-poll context).
 *   green  · `verdict='green' && ready_for_autonomous=true` — emerald, gentle pulse
 *   amber  · `verdict='amber'`                              — amber dot
 *   red    · `verdict='red'`                                — rose dot, fast pulse
 *   zinc   · loading / error / unconfigured                 — neutral
 *
 * Click behaviour: opens the FreshnessInspector deep-linked to the
 * AutonomyReadinessCard via `scrollToTestId`. Same modal everyone else
 * uses — clean operator muscle memory ("dot + click → autonomy details").
 */
import React, { useState } from 'react';
import { useAutonomyReadiness } from '../../../contexts';
import { FreshnessInspector } from './FreshnessInspector';

const TONE = {
  green: {
    dot: 'bg-emerald-400 animate-pulse',
    ring: 'ring-emerald-400/40 hover:ring-emerald-400/70',
    label: 'READY',
    title: 'Autonomous trading: cleared. All pre-flight checks green — safe to flip auto-execute.',
  },
  amber: {
    dot: 'bg-amber-400',
    ring: 'ring-amber-400/40 hover:ring-amber-400/70',
    label: 'WARN',
    title: 'Autonomous trading: warnings present — review the Autonomy card before flipping auto-execute.',
  },
  red: {
    dot: 'bg-rose-400 animate-pulse',
    ring: 'ring-rose-400/40 hover:ring-rose-400/70',
    label: 'BLOCKED',
    title: 'Autonomous trading: blocked. Clear the listed blockers before flipping auto-execute.',
  },
  zinc: {
    dot: 'bg-zinc-500',
    ring: 'ring-zinc-600/40 hover:ring-zinc-500/70',
    label: '…',
    title: 'Autonomy readiness loading…',
  },
};

export const AutonomyVerdictChip = () => {
  const { data, loading, error } = useAutonomyReadiness();
  const [open, setOpen] = useState(false);

  // Pick the strictest verdict we can: only show GREEN if both
  // verdict='green' AND ready_for_autonomous (auto-execute eligibility).
  let key = 'zinc';
  if (!loading && !error && data) {
    if (data.verdict === 'red') key = 'red';
    else if (data.verdict === 'amber') key = 'amber';
    else if (data.verdict === 'green' && data.ready_for_autonomous) key = 'green';
    else if (data.verdict === 'green') key = 'amber';   // green-but-not-ready → caution
  }
  const tone = TONE[key];

  return (
    <>
      <button
        type="button"
        data-testid="autonomy-verdict-chip"
        data-verdict={key}
        title={`${tone.title}\n\nClick to open the Freshness Inspector at the Autonomy card.`}
        onClick={() => setOpen(true)}
        className={`group inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded-full ring-1 ${tone.ring} transition-colors cursor-pointer`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${tone.dot}`} />
        <span className="v5-mono text-[8px] uppercase tracking-wider text-zinc-300/80 group-hover:text-zinc-100 hidden sm:inline">
          AUTO · {tone.label}
        </span>
      </button>
      <FreshnessInspector
        isOpen={open}
        onClose={() => setOpen(false)}
        scrollToTestId="autonomy-readiness-card"
      />
    </>
  );
};

export default AutonomyVerdictChip;
