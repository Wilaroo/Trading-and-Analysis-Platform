/**
 * EdgeDrawer — V6 ⑧ "why" drawer for the Entry Edge Score (1C).
 *
 * Right-side overlay (does not push content, per locked spec F) that breaks down the
 * Edge TRIPLE the provenance ring summarizes: edge-R + conservative lower bound,
 * the per-archetype GRADE (vs which cohort), CONFIDENCE (band + n + ±CI), and the
 * archetype CELL the score was conditioned on (the "why"). Shows a clean "scoring…"
 * state when the trade has not been scored yet.
 */
import React from 'react';
import EdgeProvenanceRing from './EdgeProvenanceRing';

const fmtR = (v) => (v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}R`);
const cellChips = (cell) =>
  String(cell || '')
    .split('|')
    .filter(Boolean)
    .map((kv) => {
      const [k, val] = kv.split('=');
      return { k: k.replace(/_/g, ' '), v: val };
    });

function Row({ label, children, testId }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3 border-b border-white/5" data-testid={testId}>
      <div className="text-[11px] uppercase tracking-wider text-zinc-500 pt-0.5">{label}</div>
      <div className="text-right text-zinc-100">{children}</div>
    </div>
  );
}

export default function EdgeDrawer({ open, onClose, item }) {
  const triple = item?.triple || null;
  const isGo = triple?.verdict === 'GO';
  const verdictColor = !triple ? 'text-zinc-400' : isGo ? 'text-emerald-400' : 'text-rose-400';
  const verdictBg = !triple ? 'bg-zinc-500/10 border-zinc-500/30' : isGo ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-rose-500/10 border-rose-500/30';

  return (
    <>
      {/* backdrop */}
      <div
        data-testid="edge-drawer-backdrop"
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-black/50 transition-opacity duration-200 ${open ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
      />
      {/* panel */}
      <aside
        data-testid="edge-drawer"
        className={`fixed top-0 right-0 z-50 h-full w-[360px] max-w-[92vw] bg-zinc-950/80 backdrop-blur-xl border-l border-white/10 shadow-2xl transition-transform duration-300 ease-out ${open ? 'translate-x-0' : 'translate-x-full'}`}
      >
        {item && (
          <div className="flex h-full flex-col">
            {/* header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
              <div>
                <div className="text-lg font-bold text-zinc-50 tracking-tight" data-testid="edge-drawer-symbol">
                  {item.symbol}
                </div>
                <div className="text-[11px] text-zinc-500 capitalize">
                  {item.setup_type || '—'} · {item.direction || '—'}
                </div>
              </div>
              <button
                data-testid="edge-drawer-close"
                onClick={onClose}
                className="text-zinc-500 hover:text-zinc-200 transition-colors text-xl leading-none px-2"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {/* ring + verdict */}
            <div className="flex flex-col items-center gap-3 px-5 py-6">
              <EdgeProvenanceRing triple={triple} size={110} testIdSuffix="drawer" />
              <div className={`px-3 py-1 rounded-full border text-xs font-semibold tracking-wide ${verdictBg} ${verdictColor}`} data-testid="edge-drawer-verdict">
                {triple ? (isGo ? '✓ GO' : '✕ STAND-DOWN') : 'scoring…'}
              </div>
            </div>

            {/* breakdown */}
            <div className="flex-1 overflow-y-auto px-5 pb-6">
              {!triple ? (
                <div className="text-center text-zinc-500 text-sm py-10" data-testid="edge-drawer-empty">
                  This trade has not been scored by the Edge model yet.
                  <div className="text-[11px] mt-2 text-zinc-600">
                    The triple populates once the gate evaluates the alert at entry.
                  </div>
                </div>
              ) : (
                <>
                  <Row label="Edge (exp. R)" testId="edge-row-edge">
                    <span className={`font-mono font-bold ${Number(triple.edge_r) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                      {fmtR(triple.edge_r)}
                    </span>
                    <div className="text-[11px] text-zinc-500 mt-0.5">
                      conservative {fmtR(triple.conservative_edge)}
                    </div>
                  </Row>

                  <Row label="Grade" testId="edge-row-grade">
                    <span className="font-mono font-bold text-zinc-100">{triple.grade ?? '—'}<span className="text-zinc-500 text-xs">/100</span></span>
                    <div className="text-[11px] text-zinc-500 mt-0.5">
                      {triple.grade_basis === 'archetype'
                        ? `ranked within ${(triple.grade_cohort || 'its archetype').replace(/setup_type=|direction=/g, '').replace('|', ' · ')}`
                        : 'ranked vs all setups (thin cohort)'}
                    </div>
                  </Row>

                  <Row label="Confidence" testId="edge-row-confidence">
                    <span className="font-mono font-bold text-zinc-100 capitalize">{triple.confidence || '—'}</span>
                    <div className="text-[11px] text-zinc-500 mt-0.5">
                      n={triple.confidence_n ?? '—'}{triple.confidence_ci != null ? ` · ±${Number(triple.confidence_ci).toFixed(2)}R` : ''}
                    </div>
                  </Row>

                  {triple.verdict === 'STAND_DOWN' && triple.stand_down_reason && (
                    <Row label="Stand-down" testId="edge-row-standdown">
                      <span className="text-rose-300 text-sm">{String(triple.stand_down_reason).replace(/_/g, ' ')}</span>
                    </Row>
                  )}

                  <div className="pt-4">
                    <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-2">Archetype cell</div>
                    <div className="flex flex-wrap gap-1.5" data-testid="edge-row-cell">
                      {cellChips(triple.cell).length ? cellChips(triple.cell).map((c, i) => (
                        <span key={i} className="px-2 py-1 rounded-md bg-white/5 border border-white/10 text-[11px] text-zinc-300">
                          <span className="text-zinc-500">{c.k}:</span> {c.v}
                        </span>
                      )) : <span className="text-zinc-600 text-xs">no cell resolved (global prior)</span>}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
