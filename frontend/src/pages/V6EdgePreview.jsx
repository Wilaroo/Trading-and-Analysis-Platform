/**
 * V6EdgePreview — ?preview=v6edge
 *
 * Focused vertical slice of the V6 cockpit: the Entry Edge Score (1C) surfaced as the
 * locked-spec ⑧ Verdict-block provenance ring + the Edge "why" drawer, plus a recent-
 * trades rail with the C mini-arc. Reads GET /api/slow-learning/entry-edge/recent.
 * Real data flows the moment the gate stamps entry_context.entry_edge.triple at entry;
 * until then rows render a muted "scoring…" ring.
 */
import React, { useEffect, useState, useCallback } from 'react';
import EdgeProvenanceRing from '../components/sentcom/v6/EdgeProvenanceRing';
import EdgeDrawer from '../components/sentcom/v6/EdgeDrawer';

const API = process.env.REACT_APP_BACKEND_URL || '';

const verdictTone = (t) =>
  !t ? 'text-zinc-400' : t.verdict === 'GO' ? 'text-emerald-400' : 'text-rose-400';

function VerdictBlock({ item }) {
  const t = item?.triple || null;
  return (
    <div
      data-testid="v6edge-verdict-block"
      className="relative rounded-2xl border border-white/10 bg-white/[0.03] backdrop-blur-xl p-8 flex flex-col items-center"
    >
      <div className="absolute top-4 left-5 text-[11px] uppercase tracking-[0.2em] text-zinc-500">Verdict</div>
      <div className="text-2xl font-bold text-zinc-50 tracking-tight mt-3" data-testid="v6edge-focus-symbol">
        {item?.symbol || '—'}
      </div>
      <div className="text-[12px] text-zinc-500 capitalize mb-6">
        {item ? `${item.setup_type || '—'} · ${item.direction || '—'}` : 'no focused trade'}
      </div>

      <div className="w-[200px] h-[200px]">
        <EdgeProvenanceRing triple={t} fill testIdSuffix="focus" />
      </div>

      <div className={`mt-6 text-lg font-bold tracking-wide ${verdictTone(t)}`} data-testid="v6edge-focus-verdict">
        {t ? (t.verdict === 'GO' ? '✓ GO' : '✕ STAND-DOWN') : 'scoring…'}
      </div>
      {t && (
        <div className="mt-4 grid grid-cols-3 gap-6 text-center">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">Edge</div>
            <div className={`font-mono font-bold ${Number(t.edge_r) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
              {t.edge_r != null ? `${Number(t.edge_r) >= 0 ? '+' : ''}${Number(t.edge_r).toFixed(2)}R` : '—'}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">Grade</div>
            <div className="font-mono font-bold text-zinc-100">{t.grade ?? '—'}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">Conf.</div>
            <div className="font-mono font-bold text-zinc-100 capitalize">{t.confidence || '—'}</div>
          </div>
        </div>
      )}
    </div>
  );
}

function TradeRow({ item, active, onClick }) {
  const t = item.triple;
  return (
    <button
      type="button"
      data-testid={`v6edge-row-${item.symbol}`}
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border transition-colors text-left ${
        active ? 'border-cyan-400/40 bg-cyan-400/5' : 'border-white/5 bg-white/[0.02] hover:bg-white/[0.05]'
      }`}
    >
      <EdgeProvenanceRing triple={t} size={34} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-zinc-100 text-sm">{item.symbol}</span>
          <span className="text-[10px] text-zinc-600 uppercase">{item.status}</span>
        </div>
        <div className="text-[11px] text-zinc-500 capitalize truncate">
          {item.setup_type || '—'} · {item.direction || '—'}
        </div>
      </div>
      <div className={`text-[11px] font-semibold ${verdictTone(t)}`}>
        {t ? (t.verdict === 'GO' ? '✓ GO' : '✕ SD') : '·'}
      </div>
    </button>
  );
}

export function V6EdgePreview() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [focusIdx, setFocusIdx] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/slow-learning/entry-edge/recent?limit=24`);
      const data = await res.json();
      setItems(Array.isArray(data.items) ? data.items : []);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const focused = items[focusIdx] || null;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100" data-testid="v6edge-preview">
      {/* heartbeat bar (① locked spec) */}
      <div className="h-[5px] w-full bg-gradient-to-r from-cyan-500/0 via-cyan-400/70 to-cyan-500/0" />

      <div className="max-w-6xl mx-auto px-6 py-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-zinc-50">Entry Edge — Provenance</h1>
            <p className="text-[12px] text-zinc-500 mt-0.5">
              ⑧ decision donut + Edge drawer · live from <span className="font-mono">/api/slow-learning/entry-edge/recent</span>
            </p>
          </div>
          <a href="?preview=v6" className="text-cyan-400 hover:underline text-[12px]">← back to V6 (locked)</a>
        </div>

        {loading ? (
          <div className="text-zinc-500 text-sm py-20 text-center" data-testid="v6edge-loading">loading edge data…</div>
        ) : err ? (
          <div className="text-rose-400 text-sm py-20 text-center" data-testid="v6edge-error">{err}</div>
        ) : items.length === 0 ? (
          <div className="text-zinc-500 text-sm py-20 text-center" data-testid="v6edge-empty">
            No recent trades yet. The Edge triple appears here once the gate scores alerts at entry.
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6">
            <div className="flex flex-col gap-4">
              <VerdictBlock item={focused} />
              <button
                data-testid="v6edge-open-drawer"
                onClick={() => setDrawerOpen(true)}
                disabled={!focused}
                className="self-center px-4 py-2 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-sm text-zinc-200 transition-colors disabled:opacity-40"
              >
                Open Edge drawer →
              </button>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-3" data-testid="v6edge-rail">
              <div className="text-[11px] uppercase tracking-wider text-zinc-500 px-2 py-2">Recent ({items.length})</div>
              <div className="flex flex-col gap-1.5 max-h-[70vh] overflow-y-auto">
                {items.map((it, i) => (
                  <TradeRow
                    key={it.id || i}
                    item={it}
                    active={i === focusIdx}
                    onClick={() => { setFocusIdx(i); setDrawerOpen(true); }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <EdgeDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} item={focused} />
    </div>
  );
}

export default V6EdgePreview;
