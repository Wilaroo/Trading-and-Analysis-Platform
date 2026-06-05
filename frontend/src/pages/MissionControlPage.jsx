/**
 * MissionControlPage — v19.34.184
 *
 * Live multi-lane "cockpit" for the whole trade pipeline. Streams the bot's
 * decision bus over `/api/ws/stream` into 5 lanes (Scanner | Gates | Execution
 * | Position | Reconciler) + a System/Safety strip, with a heartbeat pip,
 * raw/aggregate scanner mode, severity filters, and click-through to a symbol's
 * recent-decision drawer.
 *
 * The bus persists to `sentcom_thoughts` 24/7 regardless of this tab; on mount
 * we backfill recent history, then tail live.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Radio, Activity, Trophy } from 'lucide-react';
import useStreamSocket from '../hooks/useStreamSocket';
import { classifyLane, severityOf, SEVERITIES } from '../lib/laneClassify';
import LaneColumn from '../components/missioncontrol/LaneColumn';
import SafetyRow from '../components/missioncontrol/SafetyRow';
import TrailDrawer from '../components/missioncontrol/TrailDrawer';
import EVLeaderboard from '../components/sentcom/v5/EVLeaderboard';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const COLUMN_LANES = ['scanner', 'gates', 'execution', 'position', 'reconciler'];
const CAP = 150;

const STATUS_META = {
  connected:   { dot: 'bg-emerald-500 animate-pulse', label: 'LIVE' },
  connecting:  { dot: 'bg-amber-500 animate-pulse', label: 'CONNECTING' },
  disconnected:{ dot: 'bg-amber-600', label: 'RECONNECTING' },
  fallback:    { dot: 'bg-rose-600', label: 'OFFLINE' },
  idle:        { dot: 'bg-zinc-600', label: 'IDLE' },
};

const emptyLanes = () => ({ scanner: [], gates: [], execution: [], position: [], reconciler: [], system: [] });

const MissionControlPage = () => {
  const [lanes, setLanes] = useState(emptyLanes);
  const [pulse, setPulse] = useState(null);
  const [mode, setMode] = useState('aggregate');
  const [activeSeverities, setActiveSeverities] = useState(() => new Set(SEVERITIES));
  const [drawerSymbol, setDrawerSymbol] = useState(null);
  const [lastEventTs, setLastEventTs] = useState(null);
  // v19.34.188 — locally-dismissed System/Safety rows (keyed by id|timestamp).
  const [dismissedSafety, setDismissedSafety] = useState(() => new Set());
  // v19.34.274 — EV Leaderboard slide-over panel toggle.
  const [showEvBoard, setShowEvBoard] = useState(false);

  const dismissSafety = useCallback((ev) => {
    const key = ev.id || ev.timestamp;
    setDismissedSafety((prev) => {
      const n = new Set(prev);
      n.add(key);
      return n;
    });
  }, []);

  const pushEvents = useCallback((events) => {
    if (!events?.length) return;
    setLastEventTs(Date.now());
    setLanes((prev) => {
      const next = { ...prev };
      for (const lane of Object.keys(next)) next[lane] = next[lane].slice();
      for (const ev of events) {
        const lane = ev.lane || 'system';
        if (!next[lane]) continue;
        next[lane].unshift(ev);
      }
      for (const lane of Object.keys(next)) next[lane] = next[lane].slice(0, CAP);
      return next;
    });
  }, []);

  const sub = useMemo(
    () => ({ lanes: [...COLUMN_LANES, 'system'], severities: [...activeSeverities], mode }),
    [activeSeverities, mode],
  );

  const { status } = useStreamSocket({ enabled: true, sub, onEvents: pushEvents, onPulse: setPulse });

  // Backfill recent history on mount (classified client-side).
  useEffect(() => {
    let cancelled = false;
    fetch(`${BACKEND_URL}/api/sentcom/stream/history?minutes=60&limit=400`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled || !d?.success) return;
        const msgs = (d.messages || [])
          .map((m) => {
            const source = m.metadata?.source;
            const action = m.action_type || m.event;
            return {
              id: m.id,
              lane: classifyLane(action, m.kind || m.type, source),
              severity: severityOf(m.kind || m.type, action),
              action_type: action,
              symbol: m.symbol,
              text: m.text || m.content || '',
              timestamp: m.timestamp,
            };
          })
          .sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp))); // oldest→newest
        pushEvents(msgs);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [pushEvents]);

  const toggleSeverity = (s) => setActiveSeverities((prev) => {
    const n = new Set(prev);
    if (n.has(s)) n.delete(s); else n.add(s);
    return n.size === 0 ? new Set(SEVERITIES) : n;
  });

  const sm = STATUS_META[status] || STATUS_META.idle;
  const ageS = lastEventTs ? Math.round((Date.now() - lastEventTs) / 1000) : null;
  const visibleSystem = useMemo(
    () => lanes.system.filter((ev) => !dismissedSafety.has(ev.id || ev.timestamp)),
    [lanes.system, dismissedSafety],
  );

  return (
    <div data-testid="mission-control-page" className="flex flex-col bg-zinc-950 text-zinc-200" style={{ height: 'calc(100vh - 6rem)' }}>
      {/* Header / heartbeat */}
      <div className="px-4 py-2.5 border-b border-zinc-800 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Radio size={16} className="text-cyan-400" />
          <span className="text-sm font-bold uppercase tracking-wider text-zinc-100">Mission Control</span>
        </div>
        <div data-testid="mc-heartbeat" className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${sm.dot}`} />
          <span className="text-[11px] font-mono text-zinc-400">{sm.label}</span>
          {ageS != null && <span className="text-[11px] text-zinc-600">· last {ageS}s ago</span>}
        </div>

        {/* EV Leaderboard toggle */}
        <button
          type="button"
          data-testid="mc-ev-board-toggle"
          onClick={() => setShowEvBoard((x) => !x)}
          className={`flex items-center gap-1.5 px-2 py-0.5 ml-auto text-[11px] uppercase tracking-wider rounded border transition-colors ${
            showEvBoard ? 'bg-amber-900/40 text-amber-200 border-amber-700' : 'border-zinc-800 text-zinc-500 hover:text-amber-300 hover:border-amber-800'
          }`}
          title="Expected-Value leaderboard per setup"
        >
          <Trophy size={12} />
          EV Board
        </button>

        {/* Scanner mode toggle */}
        <div className="flex items-center gap-1">
          <Activity size={12} className="text-zinc-500" />
          {['aggregate', 'raw'].map((m) => (
            <button
              key={m}
              type="button"
              data-testid={`mc-mode-${m}`}
              onClick={() => setMode(m)}
              className={`px-2 py-0.5 text-[11px] uppercase tracking-wider rounded border ${
                mode === m ? 'bg-cyan-900/50 text-cyan-200 border-cyan-700' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'
              }`}
              title={m === 'raw' ? 'Stream every scanner skip/reject (firehose)' : 'Aggregate scanner skips into the pulse'}
            >
              {m}
            </button>
          ))}
        </div>

        {/* Severity filters */}
        <div className="flex items-center gap-1">
          {SEVERITIES.map((s) => (
            <button
              key={s}
              type="button"
              data-testid={`mc-sev-${s}`}
              onClick={() => toggleSeverity(s)}
              className={`px-2 py-0.5 text-[11px] uppercase tracking-wider rounded border ${
                activeSeverities.has(s) ? 'bg-zinc-800 text-zinc-100 border-zinc-600' : 'border-zinc-800 text-zinc-600 hover:text-zinc-400'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* 5 lane columns — each scrolls INDEPENDENTLY (bounded grid row) */}
      <div
        className="flex-1 min-h-0 grid grid-cols-5 gap-2 p-2"
        style={{ gridTemplateRows: 'minmax(0, 1fr)' }}
      >
        {COLUMN_LANES.map((lane) => (
          <LaneColumn
            key={lane}
            lane={lane}
            events={lanes[lane]}
            pulse={lane === 'scanner' ? pulse : null}
            onSymbolClick={setDrawerSymbol}
          />
        ))}
      </div>

      {/* System / Safety strip */}
      <div data-testid="mc-system-strip" className="h-28 border-t border-zinc-800 bg-zinc-950 flex flex-col">
        <div className="px-3 py-1 border-b border-zinc-800 bg-zinc-900/40 flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-wider text-zinc-300 font-bold">System / Safety</span>
          <span className="text-[10px] text-zinc-600">{visibleSystem.length}</span>
        </div>
        <div className="flex-1 overflow-y-auto v5-scroll">
          {visibleSystem.length === 0 ? (
            <div className="px-3 py-3 text-[11px] text-zinc-600">No system/safety events.</div>
          ) : (
            visibleSystem.map((ev) => (
              <SafetyRow key={ev.id || `${ev.timestamp}-sys`} ev={ev} onDismiss={dismissSafety} />
            ))
          )}
        </div>
      </div>

      {/* EV Leaderboard slide-over */}
      {showEvBoard && (
        <>
          <div
            data-testid="mc-ev-board-backdrop"
            className="fixed inset-0 bg-black/50 z-40"
            onClick={() => setShowEvBoard(false)}
          />
          <div
            data-testid="mc-ev-board-panel"
            className="fixed top-0 right-0 h-full w-full sm:w-[460px] z-50 border-l border-zinc-800 shadow-2xl"
          >
            <EVLeaderboard days={30} />
          </div>
        </>
      )}

      <TrailDrawer symbol={drawerSymbol} onClose={() => setDrawerSymbol(null)} />
    </div>
  );
};

export default MissionControlPage;
