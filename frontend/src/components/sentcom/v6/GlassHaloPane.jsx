/**
 * GlassHaloPane — V6 §4 ④ glass-morphism + ambient halo.
 *
 * Per spec, the halo applies to the THINKING pane ONLY and its color/breathe
 * cadence reflect §3 app-state (cyan NORMAL / amber ELEVATED / rose CRITICAL),
 * matching the Heartbeat (cyan 2s / amber 1.2s / rose 0.7s). The breathe is an
 * opacity pulse on an inset overlay (cheap + smooth) rather than animating
 * box-shadow. Pure, prop-driven.
 */
import React from 'react';

export const HALO_STATE = {
  cyan:  { color: '#22d3ee', speed: '2s' },
  amber: { color: '#fbbf24', speed: '1.2s' },
  rose:  { color: '#fb7185', speed: '0.7s' },
};

export const haloColor = (state) => (HALO_STATE[state] || HALO_STATE.cyan).color;

export const GlassHaloPane = ({
  state = 'cyan',
  className = '',
  style = {},
  testId = 'v6-glass-halo-pane',
  children,
}) => {
  const { color, speed } = HALO_STATE[state] || HALO_STATE.cyan;
  return (
    <div
      data-testid={testId}
      data-state={state}
      className={`relative rounded-lg border bg-white/[0.03] backdrop-blur-xl overflow-hidden ${className}`}
      style={{ borderColor: `${color}40`, boxShadow: `0 0 26px -10px ${color}66`, ...style }}
    >
      <div
        className="pointer-events-none absolute inset-0 rounded-lg"
        style={{
          boxShadow: `inset 0 0 44px -14px ${color}`,
          animation: `v6-halo-pulse-${state} ${speed} ease-in-out infinite`,
        }}
      />
      <div className="relative z-10 flex flex-col h-full">{children}</div>
      <style>{`@keyframes v6-halo-pulse-${state} { 0%,100% { opacity: .25; } 50% { opacity: .6; } }`}</style>
    </div>
  );
};

export default GlassHaloPane;
