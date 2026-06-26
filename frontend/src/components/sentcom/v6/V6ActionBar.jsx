/**
 * V6ActionBar — §4 "D" CRITICAL sticky action bar.
 *
 * Auto-appears ONLY when app-state is `rose` (drives off useAppState's
 * { state, signals }). One-click operator remediation, each gated behind an
 * explicit confirm (FLATTEN requires typing the word). Buttons are CONTEXTUAL:
 *   • FLATTEN ALL        — always on rose  → POST /api/safety/flatten-all?confirm=FLATTEN
 *   • CANCEL ORPHAN-GTC  — always on rose  → audit then POST /api/safety/cancel-orphan-gtc
 *   • RESET KILL-SWITCH  — only if signals.kill_switch_active → POST /api/safety/reset-kill-switch
 *   • PUSHER STATUS      — only if pushes stale → GET /api/ib/pusher-health (READ-ONLY:
 *                          there is no backend pusher-reconnect endpoint; the pusher is an
 *                          external service, so this surfaces its health instead of faking a reset)
 *
 * Additive/preview component — wired into ?preview=v6shell. The mutating calls
 * hit the LIVE account, so every one is behind a confirm; the sandbox cannot
 * exercise them (no IB) — fire-path validation happens on the DGX.
 */
import React, { useState, useCallback } from 'react';
import { AlertTriangle, X, Loader2, Check } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const req = async (path, { method = 'GET', body } = {}) => {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(`${BACKEND_URL}${path}`, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
  return d;
};

const SAFE_ORPHAN = new Set(['naked_no_position', 'orphan_no_trade']);

const ActionButton = ({ testId, onClick, children, tone = 'rose' }) => {
  const tones = {
    rose: 'bg-rose-600 hover:bg-rose-500 text-white',
    amber: 'bg-amber-500 hover:bg-amber-400 text-zinc-950',
    zinc: 'bg-white/10 hover:bg-white/20 text-zinc-100',
  };
  return (
    <button
      data-testid={testId}
      onClick={onClick}
      className={`px-3 py-1.5 rounded text-xs font-bold uppercase tracking-wider transition-colors ${tones[tone]}`}
    >
      {children}
    </button>
  );
};

export const V6ActionBar = ({ state, signals = {}, forceShow = false }) => {
  const [dismissed, setDismissed] = useState(false);
  const [modal, setModal] = useState(null);        // 'flatten'|'orphans'|'reset'|'pusher'|null
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);      // {ok, text}
  const [orphanIds, setOrphanIds] = useState([]);
  const [info, setInfo] = useState('');

  const close = useCallback(() => {
    setModal(null); setTyped(''); setBusy(false); setInfo(''); setOrphanIds([]);
  }, []);

  const openOrphans = useCallback(async () => {
    setModal('orphans'); setBusy(true); setInfo('Auditing working GTC orders…'); setResult(null);
    try {
      const audit = await req('/api/safety/orphan-gtc-orders');
      const verdicts = audit.verdicts || [];
      const ids = verdicts
        .filter((v) => SAFE_ORPHAN.has(v.classification || v.verdict))
        .map((v) => v.ib_order_id ?? v.order_id ?? v.orderId)
        .filter((x) => x != null);
      setOrphanIds(ids);
      setInfo(ids.length
        ? `${ids.length} orphan/naked GTC order(s) safe to cancel.`
        : 'No orphan/naked GTC orders found — nothing to cancel.');
    } catch (e) {
      setInfo(`Audit failed: ${String(e.message || e)}`);
    } finally {
      setBusy(false);
    }
  }, []);

  const fire = useCallback(async (kind) => {
    setBusy(true); setResult(null);
    try {
      let d;
      if (kind === 'flatten') {
        d = await req('/api/safety/flatten-all?confirm=FLATTEN', { method: 'POST' });
      } else if (kind === 'orphans') {
        d = await req('/api/safety/cancel-orphan-gtc', {
          method: 'POST', body: { ib_order_ids: orphanIds, confirm: 'CANCEL_ORPHANS' },
        });
      } else if (kind === 'reset') {
        d = await req('/api/safety/reset-kill-switch', { method: 'POST' });
      }
      setResult({ ok: d?.success !== false, text: `${kind}: done` });
      close();
    } catch (e) {
      setResult({ ok: false, text: `${kind} failed: ${String(e.message || e)}` });
      setBusy(false);
    }
  }, [orphanIds, close]);

  const checkPusher = useCallback(async () => {
    setModal('pusher'); setBusy(true); setInfo('Querying pusher health…'); setResult(null);
    try {
      const d = await req('/api/ib/pusher-health');
      setInfo(JSON.stringify(d, null, 2).slice(0, 1200));
    } catch (e) {
      setInfo(`pusher-health failed: ${String(e.message || e)}`);
    } finally {
      setBusy(false);
    }
  }, []);

  if ((state !== 'rose' && !forceShow) || dismissed) return null;

  return (
    <>
      <div
        data-testid="v6-action-bar"
        className="fixed bottom-0 inset-x-0 z-50 bg-rose-950/90 backdrop-blur-md border-t-2 border-rose-500 px-4 py-2.5 flex items-center gap-3"
        style={{ boxShadow: '0 -8px 30px rgba(244,63,94,0.25)' }}
      >
        <AlertTriangle className="w-5 h-5 text-rose-300 shrink-0 animate-pulse" />
        <span className="text-rose-100 text-sm font-bold uppercase tracking-widest shrink-0">Critical</span>

        <div className="flex items-center gap-2 flex-1">
          <ActionButton testId="v6-action-flatten" onClick={() => { setModal('flatten'); setResult(null); }}>
            Flatten All
          </ActionButton>
          <ActionButton testId="v6-action-cancel-orphans" onClick={openOrphans}>
            Cancel Orphan-GTC
          </ActionButton>
          {signals.kill_switch_active && (
            <ActionButton testId="v6-action-reset-killswitch" tone="amber" onClick={() => { setModal('reset'); setResult(null); }}>
              Reset Kill-Switch
            </ActionButton>
          )}
          {signals.pusher_push_fresh === false && (
            <ActionButton testId="v6-action-pusher-status" tone="zinc" onClick={checkPusher}>
              Pusher Status
            </ActionButton>
          )}
        </div>

        {result && (
          <span
            data-testid="v6-action-result"
            className={`text-xs font-mono ${result.ok ? 'text-emerald-300' : 'text-rose-300'}`}
          >
            {result.text}
          </span>
        )}
        <button
          data-testid="v6-action-dismiss"
          onClick={() => setDismissed(true)}
          className="ml-2 text-rose-300 hover:text-white transition-colors shrink-0"
          title="Dismiss (re-appears if state stays rose on next poll)"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {modal && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm" data-testid="v6-action-modal">
          <div className="w-[440px] max-w-[90vw] rounded-lg border border-rose-500/40 bg-zinc-950 p-5 shadow-2xl">
            {modal === 'flatten' && (
              <>
                <h3 className="text-rose-300 font-bold uppercase tracking-wider text-sm mb-1">Flatten everything</h3>
                <p className="text-zinc-400 text-xs mb-3">
                  Cancels ALL pending orders and market-closes ALL open positions, and trips the
                  kill-switch. This hits the live account. Type <b className="text-rose-300">FLATTEN</b> to confirm.
                </p>
                <input
                  data-testid="v6-action-flatten-input"
                  autoFocus value={typed} onChange={(e) => setTyped(e.target.value)}
                  className="w-full bg-zinc-900 border border-white/15 rounded px-3 py-2 text-sm text-zinc-100 mb-3 font-mono"
                  placeholder="FLATTEN"
                />
                <div className="flex justify-end gap-2">
                  <button data-testid="v6-action-modal-cancel" onClick={close} className="px-3 py-1.5 rounded text-xs text-zinc-400 hover:text-zinc-200">Cancel</button>
                  <button
                    data-testid="v6-action-flatten-confirm"
                    disabled={typed !== 'FLATTEN' || busy}
                    onClick={() => fire('flatten')}
                    className="px-3 py-1.5 rounded text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                  >
                    {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Flatten Now
                  </button>
                </div>
              </>
            )}

            {modal === 'orphans' && (
              <>
                <h3 className="text-rose-300 font-bold uppercase tracking-wider text-sm mb-1">Cancel orphan / naked GTC</h3>
                <p className="text-zinc-400 text-xs mb-3 whitespace-pre-wrap">{info || '…'}</p>
                <div className="flex justify-end gap-2">
                  <button data-testid="v6-action-modal-cancel" onClick={close} className="px-3 py-1.5 rounded text-xs text-zinc-400 hover:text-zinc-200">Close</button>
                  <button
                    data-testid="v6-action-orphans-confirm"
                    disabled={busy || orphanIds.length === 0}
                    onClick={() => fire('orphans')}
                    className="px-3 py-1.5 rounded text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                  >
                    {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Cancel {orphanIds.length || ''}
                  </button>
                </div>
              </>
            )}

            {modal === 'reset' && (
              <>
                <h3 className="text-amber-300 font-bold uppercase tracking-wider text-sm mb-1">Reset kill-switch</h3>
                <p className="text-zinc-400 text-xs mb-3">
                  Unlocks trading. The bot resumes placing entries on the next scan. Only do this
                  after you understand WHY it tripped: <span className="text-amber-300">{signals.kill_switch_reason || 'manual'}</span>.
                </p>
                <div className="flex justify-end gap-2">
                  <button data-testid="v6-action-modal-cancel" onClick={close} className="px-3 py-1.5 rounded text-xs text-zinc-400 hover:text-zinc-200">Cancel</button>
                  <button
                    data-testid="v6-action-reset-confirm"
                    disabled={busy}
                    onClick={() => fire('reset')}
                    className="px-3 py-1.5 rounded text-xs font-bold bg-amber-500 hover:bg-amber-400 text-zinc-950 disabled:opacity-40 flex items-center gap-1.5"
                  >
                    {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Reset Now
                  </button>
                </div>
              </>
            )}

            {modal === 'pusher' && (
              <>
                <h3 className="text-zinc-200 font-bold uppercase tracking-wider text-sm mb-1 flex items-center gap-1.5">
                  <Check className="w-4 h-4 text-zinc-400" /> Pusher health (read-only)
                </h3>
                <p className="text-zinc-500 text-[11px] mb-2">No reconnect endpoint exists — the pusher is an external service. This shows its current health so you know whether to restart it on the host.</p>
                <pre className="bg-zinc-900 border border-white/10 rounded p-2 text-[10px] text-zinc-300 overflow-auto max-h-[260px] whitespace-pre-wrap">{info || '…'}</pre>
                <div className="flex justify-end mt-3">
                  <button data-testid="v6-action-modal-cancel" onClick={close} className="px-3 py-1.5 rounded text-xs text-zinc-400 hover:text-zinc-200">Close</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
};

export default V6ActionBar;
