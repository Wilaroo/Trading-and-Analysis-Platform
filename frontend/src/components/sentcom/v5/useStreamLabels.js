/**
 * Wave 4 (#8) — useStreamLabels hook + ReactionButtons component.
 *
 * Operator hits 👍 / 👎 on a stream row → posts to
 * /api/sentcom/stream/label. Returned label state is held in a Map
 * keyed by event_id so all visible rows reflect any single click
 * instantly (optimistic update; server is source of truth on next
 * fetch).
 *
 * Hydrates from /api/sentcom/stream/labels on mount so reloads /
 * tab-switches don't lose the operator's prior reactions for
 * currently-visible events.
 */
import React, { useCallback, useEffect, useState } from 'react';

const LABEL_HYDRATION_MINUTES = 60 * 24;  // hydrate last 24h on mount
const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

export const useStreamLabels = () => {
  // Map<event_id, 'up' | 'down'>. Only labelled events appear.
  const [labels, setLabels] = useState(() => new Map());

  // Hydrate on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `${API_BASE}/api/sentcom/stream/labels?minutes=${LABEL_HYDRATION_MINUTES}&limit=2000`
        );
        if (!r.ok) return;
        const data = await r.json();
        if (cancelled || !data?.success) return;
        const next = new Map();
        for (const row of data.labels || []) {
          if (row.event_id && row.label) next.set(row.event_id, row.label);
        }
        setLabels(next);
      } catch (_) { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const setLabel = useCallback(async (event_id, label, ctx = {}) => {
    if (!event_id) return;
    // Optimistic update.
    setLabels((prev) => {
      const next = new Map(prev);
      const current = next.get(event_id);
      if (label === 'clear' || current === label) {
        next.delete(event_id);
      } else {
        next.set(event_id, label);
      }
      return next;
    });
    // POST. If the user double-clicked the same emoji we send "clear"
    // to remove the row server-side (matches the Map.delete above).
    const isToggle = labels.get(event_id) === label;
    const sendLabel = isToggle ? 'clear' : label;
    try {
      await fetch(`${API_BASE}/api/sentcom/stream/label`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_id,
          label: sendLabel,
          symbol: ctx.symbol || null,
          kind: ctx.kind || null,
          action_type: ctx.action_type || null,
        }),
      });
    } catch (_) { /* silent — optimistic UI already updated */ }
  }, [labels]);

  return { labels, setLabel };
};


/**
 * ReactionButtons — tiny inline 👍 / 👎. Renders empty if no event_id.
 * Hidden by default; shows on row hover via CSS (`.v5-stream-item:hover .v5-reactions`).
 */
export const ReactionButtons = ({ event_id, ctx, labels, setLabel }) => {
  if (!event_id) return null;
  const current = labels.get(event_id);

  const onClick = (e, label) => {
    e.stopPropagation();
    setLabel(event_id, label, ctx);
  };

  return (
    <span
      className="v5-reactions inline-flex items-center gap-0.5 ml-1"
      data-testid={`v5-reactions-${event_id}`}
    >
      <button
        type="button"
        onClick={(e) => onClick(e, 'up')}
        className={`v5-reaction-btn ${current === 'up' ? 'active up' : ''}`}
        title={current === 'up' ? 'Remove 👍' : 'Mark as good signal (👍)'}
        data-testid={`v5-reaction-up-${event_id}`}
      >
        👍
      </button>
      <button
        type="button"
        onClick={(e) => onClick(e, 'down')}
        className={`v5-reaction-btn ${current === 'down' ? 'active down' : ''}`}
        title={current === 'down' ? 'Remove 👎' : 'Mark as bad signal (👎)'}
        data-testid={`v5-reaction-down-${event_id}`}
      >
        👎
      </button>
    </span>
  );
};

export default ReactionButtons;
