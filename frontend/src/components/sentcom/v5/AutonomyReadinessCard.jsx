/**
 * AutonomyReadinessCard — single go/no-go SLA tile for autonomous
 * trading. Shows 7 sub-checks (account, pusher, live bars, trophy run,
 * kill switch, EOD, risk consistency) plus the auto-execute master gate
 * status. Designed to be the LAST thing the operator looks at before
 * flipping `auto-execute: enabled: true` on Monday morning.
 *
 * Endpoint: GET /api/autonomy/readiness
 *   verdict: 'green' | 'amber' | 'red'
 *   ready_for_autonomous: bool
 *   auto_execute_enabled: bool   (informational)
 *   blockers, warnings, next_steps, checks{...}
 */

import React, { useState } from 'react';
import { useAutonomyReadiness } from '../../../contexts';

const TONE = {
  green: 'bg-emerald-900/30 text-emerald-200 border-emerald-800',
  amber: 'bg-amber-900/30 text-amber-200 border-amber-800',
  red:   'bg-rose-900/30 text-rose-200 border-rose-800',
  zinc:  'bg-zinc-900/40 text-zinc-300 border-zinc-800',
};

const VERDICT_LABEL = { green: 'READY', amber: 'WARNINGS', red: 'NOT READY' };
const STATUS_LABEL = { green: 'OK', amber: 'WARN', red: 'FAIL' };
const STATUS_DOT = { green: 'bg-emerald-400', amber: 'bg-amber-400', red: 'bg-rose-400' };

const CHECK_LABELS = {
  account:          'Account active',
  pusher_rpc:       'Pusher RPC',
  live_bars:        'Live bars',
  trophy_run:       'Trophy run',
  kill_switch:      'Kill switch',
  eod_auto_close:   'EOD auto-close',
  risk_consistency: 'Risk params',
};

export const AutonomyReadinessCard = () => {
  // App-wide canonical autonomy snapshot. Same source as any future
  // header chip / ⌘K palette preview / pre-Monday checklist banner —
  // all surfaces flip in lock-step on a 30s cadence (see
  // contexts/AutonomyReadinessContext.jsx).
  const { data, loading, error } = useAutonomyReadiness();
  const [expanded, setExpanded] = useState(null);

  const verdict = data?.verdict || 'zinc';

  return (
    <section data-testid="autonomy-readiness-card"
             data-help-id="autonomy-readiness"
             data-verdict={verdict}
             className="space-y-2">
      <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide flex items-center gap-2">
        Autonomous trading readiness
        {loading && (
          <span data-testid="autonomy-loading" className="text-zinc-600">· loading…</span>
        )}
        <span className="ml-auto text-zinc-600 normal-case tracking-normal text-[11px]">
          go/no-go before flipping auto-execute
        </span>
      </div>

      <div className={`flex items-start gap-3 p-3 rounded border ${TONE[verdict] || TONE.zinc}`}
           data-testid="autonomy-verdict-pill">
        <div className="flex items-center gap-2 shrink-0">
          <span className={`w-2.5 h-2.5 rounded-full ${
            STATUS_DOT[verdict] || 'bg-zinc-500'
          } ${verdict === 'red' ? 'animate-pulse' : ''}`} />
          <span className="v5-mono font-bold text-sm uppercase tracking-wider">
            {VERDICT_LABEL[verdict] || '—'}
          </span>
        </div>
        <div className="flex-1 min-w-0 v5-mono text-[13px] leading-tight pt-0.5 break-words">
          {error && !data ? (
            <span className="text-rose-400" data-testid="autonomy-error">
              /api/autonomy/readiness unreachable — {error}
            </span>
          ) : (
            <span className="opacity-90">{data?.summary || '—'}</span>
          )}
        </div>
      </div>

      {data?.checks && (
        <div data-testid="autonomy-checks-grid"
             className="grid grid-cols-1 sm:grid-cols-2 gap-1">
          {Object.entries(data.checks).map(([k, c]) => {
            const tone = c.status;
            const isOpen = expanded === k;
            return (
              <div
                key={k}
                role="button"
                tabIndex={0}
                data-testid={`autonomy-check-${k}`}
                data-status={tone}
                data-expanded={isOpen}
                onClick={() => setExpanded(isOpen ? null : k)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setExpanded(isOpen ? null : k);
                  }
                }}
                className={`cursor-pointer text-left px-2 py-1.5 rounded border hover:brightness-110 transition focus:outline-none focus:ring-1 focus:ring-cyan-500/40 ${TONE[tone] || TONE.zinc}
                            ${isOpen ? 'sm:col-span-2 ring-1 ring-cyan-500/30' : ''}`}>
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[tone] || 'bg-zinc-500'}`} />
                  <span className="v5-mono text-[12px] font-bold flex-1 truncate">
                    {CHECK_LABELS[k] || k}
                  </span>
                  <span className={`v5-mono text-[11px] tabular-nums opacity-70`}>
                    {STATUS_LABEL[tone] || '—'}
                  </span>
                  <span className="v5-mono text-[12px] opacity-60 ml-1" aria-hidden>
                    {isOpen ? '▾' : '▸'}
                  </span>
                </div>
                <div className="v5-mono text-[9.5px] opacity-80 mt-0.5 truncate">
                  {c.detail}
                </div>
                {isOpen && (
                  <div data-testid={`autonomy-check-${k}-drawer`}
                       className="mt-2 pt-2 border-t border-current/20 v5-mono text-[12px] space-y-0.5"
                       onClick={(e) => e.stopPropagation()}>
                    {Object.entries(c).filter(([key]) =>
                      !['status', 'detail'].includes(key)
                    ).map(([key, value]) => (
                      <div key={key} className="flex gap-2">
                        <span className="opacity-60 shrink-0">{key}:</span>
                        <span className="break-all">
                          {typeof value === 'object' && value !== null
                            ? JSON.stringify(value)
                            : String(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Auto-execute master gate status */}
      {data && (
        <div data-testid="autonomy-auto-execute-banner"
             data-enabled={data.auto_execute_enabled}
             className={`px-2 py-1.5 rounded border v5-mono text-[12px] flex items-center gap-2 ${
               data.auto_execute_enabled
                 ? 'bg-cyan-900/40 text-cyan-200 border-cyan-700'
                 : 'bg-zinc-900/60 text-zinc-400 border-zinc-800'
             }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${
            data.auto_execute_enabled ? 'bg-cyan-300 animate-pulse' : 'bg-zinc-500'
          }`} />
          <span className="font-bold">
            Auto-execute: {data.auto_execute_enabled ? 'LIVE' : 'OFF (manual approval mode)'}
          </span>
        </div>
      )}

      {/* Next steps (if any) */}
      {data?.next_steps?.length > 0 && (
        <div data-testid="autonomy-next-steps" className="space-y-0.5">
          <div className="v5-mono text-[11px] uppercase text-zinc-500 tracking-wide">
            Next steps
          </div>
          {data.next_steps.slice(0, 5).map((s, i) => (
            <div key={i}
                 data-testid={`autonomy-next-step-${i}`}
                 className="v5-mono text-[12px] text-zinc-300 leading-snug">
              <span className="text-zinc-500 mr-1">→</span>{s}
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

export default AutonomyReadinessCard;
