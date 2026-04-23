/**
 * useMorningBriefing — shared hook for the V5 Briefings panel and (if needed)
 * the legacy MorningBriefingModal.
 *
 * Fans out to the endpoints the modal uses:
 *   • /api/journal/gameplan/today      — user's pre-market game plan
 *   • /api/journal/drc/today           — daily risk check
 *   • /api/portfolio                   — positions snapshot (for summary)
 *   • /api/live-scanner/status         — is the scanner running, how many hits
 *   • /api/trading-bot/status          — bot running state
 *   • /api/safety/status               — kill switch / awaiting quotes (2026-04-23)
 *   • /api/sentcom/drift               — per-model drift snapshot (2026-04-23)
 *
 * All calls use `Promise.allSettled` so one missing endpoint doesn't zero the
 * whole briefing. Refreshes every `refreshMs` (default 60s).
 */
import { useEffect, useState, useCallback } from 'react';
import api from '../../../utils/api';

export const useMorningBriefing = ({ refreshMs = 60_000, enabled = true } = {}) => {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [gp, drc, pf, sc, bot, safety, drift] = await Promise.allSettled([
        api.get('/api/journal/gameplan/today', { timeout: 8000 }),
        api.get('/api/journal/drc/today',      { timeout: 8000 }),
        api.get('/api/portfolio',              { timeout: 8000 }),
        api.get('/api/live-scanner/status',    { timeout: 8000 }),
        api.get('/api/trading-bot/status',     { timeout: 8000 }),
        api.get('/api/safety/status',          { timeout: 8000 }),
        api.get('/api/sentcom/drift',          { timeout: 8000 }),
      ]);

      setData({
        game_plan: gp.status === 'fulfilled' ? (gp.value.data?.game_plan ?? gp.value.data ?? null) : null,
        drc:       drc.status === 'fulfilled' ? (drc.value.data?.drc ?? drc.value.data ?? null) : null,
        positions: pf.status === 'fulfilled' ? (pf.value.data?.positions ?? []) : [],
        summary:   pf.status === 'fulfilled' ? (pf.value.data?.summary ?? null) : null,
        scanner:   sc.status === 'fulfilled' ? sc.value.data : null,
        bot:       bot.status === 'fulfilled' ? bot.value.data : null,
        safety:    safety.status === 'fulfilled' ? safety.value.data : null,
        drift:     drift.status === 'fulfilled' ? (drift.value.data?.results ?? []) : [],
        fetched_at: new Date().toISOString(),
      });
    } catch (err) {
      setError(err?.message || 'briefing fetch failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    reload();
  }, [enabled, reload]);

  useEffect(() => {
    if (!enabled || !refreshMs) return undefined;
    const id = setInterval(reload, refreshMs);
    return () => clearInterval(id);
  }, [enabled, refreshMs, reload]);

  return { loading, data, error, reload };
};

export default useMorningBriefing;
