import React, { memo } from 'react';
import { ShieldCheck, ShieldAlert, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react';

const ValidationResultsPanel = memo(({ validationResults, onRefresh }) => {
  const { total = 0, promoted = 0, rejected = 0, records = [] } = validationResults || {};

  if (total === 0) {
    return (
      <div className="text-center py-8" data-testid="validation-empty">
        <ShieldCheck className="w-10 h-10 text-zinc-600 mx-auto mb-3" />
        <p className="text-sm text-zinc-400">No validation results yet</p>
        <p className="text-xs text-zinc-500 mt-1">Run the training pipeline — Phase 13 will auto-validate all trained models</p>
      </div>
    );
  }

  const promotedRecords = records.filter(r => r.status === 'promoted');
  const rejectedRecords = records.filter(r => r.status === 'rejected');
  const pendingRecords = records.filter(r => r.status !== 'promoted' && r.status !== 'rejected');

  return (
    <div data-testid="validation-results-panel">
      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="p-3 rounded-lg bg-white/[0.03] border border-white/5 text-center">
          <div className="text-2xl font-bold text-white">{total}</div>
          <div className="text-[10px] text-zinc-500 uppercase">Total Validated</div>
        </div>
        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-center">
          <div className="text-2xl font-bold text-emerald-400">{promoted}</div>
          <div className="text-[10px] text-emerald-500 uppercase">Promoted</div>
        </div>
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-center">
          <div className="text-2xl font-bold text-red-400">{rejected}</div>
          <div className="text-[10px] text-red-500 uppercase">Rejected</div>
        </div>
      </div>

      {/* Validation Records Table */}
      <div className="rounded-lg border border-white/5 overflow-hidden">
        <div className="grid grid-cols-12 gap-1 px-3 py-2 bg-white/[0.02] text-[10px] text-zinc-500 uppercase font-medium border-b border-white/5">
          <div className="col-span-3">Setup</div>
          <div className="col-span-2">Bar Size</div>
          <div className="col-span-2 text-center">Status</div>
          <div className="col-span-2 text-center">Phases</div>
          <div className="col-span-3 text-center">Train Acc</div>
        </div>

        <div className="max-h-[400px] overflow-y-auto">
          {records.map((record, idx) => {
            const isPromoted = record.status === 'promoted';
            const isRejected = record.status === 'rejected';
            const accuracy = record.training_accuracy || 0;
            const phases = record.phases_passed || 0;
            const maxPhases = 5;

            return (
              <div
                key={idx}
                className={`grid grid-cols-12 gap-1 px-3 py-2 text-xs border-b border-white/[0.03] ${
                  isPromoted ? 'bg-emerald-500/[0.03]' : isRejected ? 'bg-red-500/[0.03]' : 'bg-transparent'
                } hover:bg-white/[0.03] transition-colors`}
                data-testid={`validation-record-${idx}`}
              >
                <div className="col-span-3 text-zinc-300 font-mono truncate" title={record.setup_type}>
                  {record.setup_type || '?'}
                </div>
                <div className="col-span-2 text-zinc-400">
                  {record.bar_size || '?'}
                </div>
                <div className="col-span-2 text-center">
                  {isPromoted ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 text-[10px]">
                      <ShieldCheck className="w-3 h-3" /> Live
                    </span>
                  ) : isRejected ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 text-[10px]">
                      <ShieldAlert className="w-3 h-3" /> Fail
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-500/20 text-zinc-400 text-[10px]">
                      <AlertTriangle className="w-3 h-3" /> Pending
                    </span>
                  )}
                </div>
                <div className="col-span-2 text-center">
                  <div className="flex items-center justify-center gap-0.5">
                    {Array.from({ length: maxPhases }).map((_, i) => (
                      <div
                        key={i}
                        className={`w-2 h-2 rounded-full ${
                          i < phases ? 'bg-emerald-400' : 'bg-zinc-700'
                        }`}
                      />
                    ))}
                    <span className="ml-1 text-[10px] text-zinc-500">{phases}/{maxPhases}</span>
                  </div>
                </div>
                <div className="col-span-3 text-center">
                  <div className="flex items-center justify-center gap-1">
                    {accuracy > 0.55 ? (
                      <TrendingUp className="w-3 h-3 text-emerald-400" />
                    ) : accuracy > 0.45 ? (
                      <TrendingUp className="w-3 h-3 text-yellow-400" />
                    ) : accuracy > 0 ? (
                      <TrendingDown className="w-3 h-3 text-red-400" />
                    ) : null}
                    <span className={`font-mono ${
                      accuracy > 0.55 ? 'text-emerald-400' :
                      accuracy > 0.45 ? 'text-yellow-400' :
                      accuracy > 0 ? 'text-red-400' : 'text-zinc-500'
                    }`}>
                      {accuracy > 0 ? `${(accuracy * 100).toFixed(1)}%` : '--'}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3 text-[10px] text-zinc-500">
        <span className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-emerald-400" /> Promoted to live</span>
        <span className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-red-400" /> Rejected</span>
        <span className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-zinc-600" /> Phase not passed</span>
      </div>
    </div>
  );
});

export default ValidationResultsPanel;
