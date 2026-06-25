/**
 * Heartbeat — V6 shell primitive (§4 ① full-width 5px state bar).
 *
 * Pure, prop-driven: the sliding pulse color + speed reflect app state
 * (cyan NORMAL / amber ELEVATED / rose CRITICAL — see §3 compute_app_state).
 * Lifted from the V6NextMockup so the real shell and the mockup share one
 * look. Props in, JSX out.
 */
import React from 'react';

const STATE_COLOR = { rose: '#fb7185', amber: '#fbbf24', cyan: '#22d3ee' };
const STATE_SPEED = { rose: '0.7s', amber: '1.2s', cyan: '2s' };

export const Heartbeat = ({ state = 'cyan' }) => {
  const color = STATE_COLOR[state] || STATE_COLOR.cyan;
  const speed = STATE_SPEED[state] || STATE_SPEED.cyan;
  return (
    <>
      <div
        data-testid="v6-heartbeat"
        data-state={state}
        className="h-[5px] w-full bg-zinc-950 relative overflow-hidden flex-shrink-0 border-b border-zinc-900"
      >
        <div
          className="absolute inset-y-0 left-0 w-[25%] opacity-95"
          style={{
            background: `linear-gradient(90deg, transparent, ${color}, ${color}, transparent)`,
            filter: `drop-shadow(0 0 4px ${color})`,
            animation: `v6-pulse-slide ${speed} ease-in-out infinite`,
          }}
        />
      </div>
      <style>{`@keyframes v6-pulse-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(500%); } }`}</style>
    </>
  );
};

export default Heartbeat;
