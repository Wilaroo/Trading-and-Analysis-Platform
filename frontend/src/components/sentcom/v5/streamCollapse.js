/**
 * collapseStreamMessages — Wave-1 (#5) repeat-event suppressor.
 *
 * Walks a time-DESC `messages` array and groups CONSECUTIVE rows
 * that share the same (symbol + action_type/event/kind) signature
 * into a single "collapsed" row carrying:
 *   • count: how many were collapsed (≥2 to be a group)
 *   • first_ts / last_ts: bookends so the UI can show "last 0:32 ago"
 *   • children: the original messages, preserved for click-to-expand
 *
 * Only CONSECUTIVE same-signature rows collapse. If the bot fires
 * AAPL skip → NVDA skip → AAPL skip, you still see 3 rows (the order
 * of events matters; non-adjacent runs are NOT merged).
 *
 * Why pure-function: trivially unit-testable; `UnifiedStreamV5`
 * imports and useMemo()s over `messages`. No React deps.
 */

const _signatureOf = (m) => {
  const sym = (m.symbol || m.ticker || '').toUpperCase();
  // Match the same hierarchy `classifyMessage` uses — `action_type` is
  // the specific signal, fall back through `event/kind/type`.
  const kind = (m.action_type || m.event || m.kind || m.type || '')
    .toString()
    .toLowerCase();
  return `${sym}|${kind}`;
};

/**
 * @param {Array<Object>} messages — time-DESC list (newest first).
 * @param {Object} [opts]
 * @param {number} [opts.minRunLength=2] — only collapse runs of this length+.
 *   Set to 999 to effectively disable (returns originals).
 * @param {Set<string>} [opts.expandedKeys] — collapsed keys the user has
 *   manually expanded; their groups are skipped (rendered uncollapsed).
 * @returns {Array<Object>} — array of either:
 *   • original message (single occurrence) OR
 *   • collapsed row: { _collapsed: true, key, count, signature,
 *                      first_ts, last_ts, children: [...] }
 */
export const collapseStreamMessages = (messages, opts = {}) => {
  const { minRunLength = 2, expandedKeys = null } = opts;
  if (!Array.isArray(messages) || messages.length === 0) return [];
  if (minRunLength > messages.length) return messages.slice();

  const out = [];
  let i = 0;
  const n = messages.length;

  while (i < n) {
    const head = messages[i];
    const sig = _signatureOf(head);

    // Walk forward while the signature matches (sym + action both present)
    // and there's actually a meaningful sym/kind to dedupe on. Rows with
    // empty signature ("|") never group — they're unique by definition.
    let j = i + 1;
    if (sig !== '|') {
      while (j < n && _signatureOf(messages[j]) === sig) j++;
    }

    const runLen = j - i;
    // Stable group key: `<sym>|<kind>|<oldest_ts_in_run>` — survives
    // re-renders so an expanded group stays expanded across WS pushes
    // that don't disturb the existing run.
    const oldest = messages[j - 1];
    const groupKey = `${sig}|${oldest.timestamp || oldest.created_at || oldest.time || ''}`;
    const isExpanded = expandedKeys && expandedKeys.has(groupKey);

    if (runLen >= minRunLength && !isExpanded) {
      out.push({
        _collapsed: true,
        key: groupKey,
        signature: sig,
        count: runLen,
        first_ts: head.timestamp || head.created_at || head.time, // newest
        last_ts: oldest.timestamp || oldest.created_at || oldest.time, // oldest
        // Newest of the run drives the row's headline / classification —
        // keeps colour / shadow-badge logic identical to single-row mode.
        head,
        children: messages.slice(i, j),
      });
    } else {
      // Either run too short OR explicitly expanded — emit each row
      // as-is so the rest of the pipeline (filters, severity, shadow
      // badges) sees the original objects.
      for (let k = i; k < j; k++) out.push(messages[k]);
    }
    i = j;
  }

  return out;
};

// Exported for tests only.
export const _signatureOfForTests = _signatureOf;
