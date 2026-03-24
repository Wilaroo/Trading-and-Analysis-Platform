import React, { useState, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  GitBranch, ChevronDown, ChevronRight, FlaskConical,
  Rocket, Clock, AlertTriangle, CheckCircle2, Loader2
} from 'lucide-react';
import { phaseColors, phaseIcons } from './constants';

const StrategyPipelinePanel = memo(({ phases, candidates, loading, onPromote, onDemote }) => {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState('lifecycle');
  const [promotingStrategy, setPromotingStrategy] = useState(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState(null);

  const readyCandidates = candidates?.filter(c => c.meets_requirements) || [];
  const pendingCandidates = candidates?.filter(c => !c.meets_requirements) || [];

  const phaseOrder = ['simulation', 'paper', 'live'];
  const phaseCounts = phaseOrder.map(p => ({
    phase: p,
    count: phases?.by_phase?.[p]?.length || 0
  }));

  const handlePromoteClick = (candidate) => {
    if (candidate.target_phase === 'live') {
      setSelectedCandidate(candidate);
      setShowConfirmModal(true);
    } else {
      handleConfirmPromotion(candidate);
    }
  };

  const handleConfirmPromotion = async (candidate) => {
    setPromotingStrategy(candidate.strategy_name);
    setShowConfirmModal(false);
    try {
      await onPromote(candidate.strategy_name, candidate.target_phase);
    } finally {
      setPromotingStrategy(null);
      setSelectedCandidate(null);
    }
  };

  return (
    <>
      <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="strategy-pipeline-panel">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
          data-testid="strategy-pipeline-toggle"
        >
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #3b82f6, #10b981)' }}>
              <GitBranch className="w-4 h-4 text-white" />
            </div>
            <div className="text-left">
              <h3 className="text-sm font-semibold text-white">Strategy Pipeline</h3>
              <p className="text-xs text-zinc-400">Lifecycle & promotions</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Phase summary pills */}
            {phaseCounts.map(pc => pc.count > 0 && (
              <span key={pc.phase} className={`text-[10px] px-1.5 py-0.5 rounded ${phaseColors[pc.phase]}`}>
                {pc.count} {pc.phase}
              </span>
            ))}
            {readyCandidates.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 animate-pulse">{readyCandidates.length} ready</span>
            )}
            <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
          </div>
        </button>

        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="border-t border-white/10"
            >
              {/* Tabs */}
              <div className="flex border-b border-white/10">
                <button
                  onClick={() => setActiveTab('lifecycle')}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${activeTab === 'lifecycle' ? 'text-blue-400 border-b-2 border-blue-400 bg-blue-500/5' : 'text-zinc-500 hover:text-zinc-300'}`}
                  data-testid="pipeline-tab-lifecycle"
                >
                  <GitBranch className="w-3 h-3" /> Lifecycle
                </button>
                <button
                  onClick={() => setActiveTab('promotions')}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${activeTab === 'promotions' ? 'text-green-400 border-b-2 border-green-400 bg-green-500/5' : 'text-zinc-500 hover:text-zinc-300'}`}
                  data-testid="pipeline-tab-promotions"
                >
                  <Rocket className="w-3 h-3" /> Promotions
                  {readyCandidates.length > 0 && <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />}
                </button>
              </div>

              {activeTab === 'lifecycle' ? (
                <div className="p-4">
                  {/* Phase Flow Visualization */}
                  <div className="flex items-center justify-between mb-4 p-3 rounded-lg bg-black/20 border border-white/5">
                    {phaseOrder.map((phase, idx) => {
                      const Icon = phaseIcons[phase] || FlaskConical;
                      const count = phases?.by_phase?.[phase]?.length || 0;
                      return (
                        <React.Fragment key={phase}>
                          <div className="flex flex-col items-center gap-1">
                            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${count > 0 ? phaseColors[phase]?.split(' ').slice(1, 3).join(' ') : 'bg-white/[0.02]'}`}>
                              <Icon className={`w-5 h-5 ${count > 0 ? phaseColors[phase]?.split(' ')[0] : 'text-zinc-600'}`} />
                            </div>
                            <span className="text-white font-bold text-sm">{count}</span>
                            <span className="text-[10px] text-zinc-500 capitalize">{phase}</span>
                          </div>
                          {idx < phaseOrder.length - 1 && (
                            <div className="flex-1 flex items-center justify-center">
                              <ChevronRight className="w-4 h-4 text-zinc-600" />
                            </div>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </div>

                  {/* All Strategies */}
                  <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">All Strategies</h4>
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {phases?.phases && Object.entries(phases.phases).map(([name, phase]) => {
                      const Icon = phaseIcons[phase] || FlaskConical;
                      return (
                        <div key={name} className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/5">
                          <div className="flex items-center gap-2">
                            <Icon className={`w-3 h-3 ${phaseColors[phase]?.split(' ')[0] || 'text-zinc-400'}`} />
                            <span className="text-xs text-zinc-300">{name}</span>
                          </div>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${phaseColors[phase]}`}>{phase}</span>
                        </div>
                      );
                    })}
                    {(!phases?.phases || Object.keys(phases.phases).length === 0) && (
                      <div className="text-xs text-zinc-500 text-center py-4">No strategies tracked yet. Run simulations to populate.</div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="p-4">
                  {/* Ready for Promotion */}
                  {readyCandidates.length > 0 && (
                    <div className="mb-4">
                      <h4 className="text-xs font-semibold text-green-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <CheckCircle2 className="w-3 h-3" /> Ready for Promotion ({readyCandidates.length})
                      </h4>
                      <div className="space-y-3">
                        {readyCandidates.map((candidate) => {
                          const isPromoting = promotingStrategy === candidate.strategy_name;
                          const perf = candidate.performance || {};
                          return (
                            <div key={candidate.strategy_name} className="p-3 rounded-lg border border-green-500/20 bg-green-500/5">
                              <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-semibold text-white">{candidate.strategy_name}</span>
                                  <div className="flex items-center gap-1 text-xs text-zinc-400">
                                    <span className={`px-1.5 py-0.5 rounded ${phaseColors[candidate.current_phase]}`}>{candidate.current_phase}</span>
                                    <ChevronRight className="w-3 h-3" />
                                    <span className={`px-1.5 py-0.5 rounded ${phaseColors[candidate.target_phase]}`}>{candidate.target_phase}</span>
                                  </div>
                                </div>
                                <button
                                  onClick={() => handlePromoteClick(candidate)}
                                  disabled={isPromoting}
                                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-colors text-xs font-medium disabled:opacity-50"
                                  data-testid={`promote-${candidate.strategy_name}`}
                                >
                                  {isPromoting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Rocket className="w-3 h-3" />}
                                  {isPromoting ? 'Promoting...' : `Promote to ${candidate.target_phase.toUpperCase()}`}
                                </button>
                              </div>
                              <div className="grid grid-cols-4 gap-2 text-xs">
                                <div className="p-2 rounded bg-white/[0.03]"><div className="text-zinc-500">Trades</div><div className="text-white font-mono">{perf.total_trades || 0}</div></div>
                                <div className="p-2 rounded bg-white/[0.03]"><div className="text-zinc-500">Win Rate</div><div className={`font-mono ${(perf.win_rate || 0) >= 0.5 ? 'text-green-400' : 'text-yellow-400'}`}>{((perf.win_rate || 0) * 100).toFixed(0)}%</div></div>
                                <div className="p-2 rounded bg-white/[0.03]"><div className="text-zinc-500">Avg R</div><div className={`font-mono ${(perf.avg_r_multiple || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>{(perf.avg_r_multiple || 0).toFixed(2)}R</div></div>
                                <div className="p-2 rounded bg-white/[0.03]"><div className="text-zinc-500">Days</div><div className="text-white font-mono">{perf.days_in_phase || 0}</div></div>
                              </div>
                              {candidate.target_phase === 'live' && (
                                <div className="mt-2 p-2 rounded bg-yellow-500/10 border border-yellow-500/20 text-xs text-yellow-400 flex items-start gap-2">
                                  <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                                  <span>This will enable REAL money trading for this strategy</span>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Not Yet Ready */}
                  {pendingCandidates.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <Clock className="w-3 h-3" /> Not Yet Ready ({pendingCandidates.length})
                      </h4>
                      <div className="space-y-2">
                        {pendingCandidates.slice(0, 5).map((candidate) => {
                          const perf = candidate.performance || {};
                          return (
                            <div key={candidate.strategy_name} className="p-3 rounded-lg border border-white/5 bg-white/[0.02]">
                              <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm text-zinc-300">{candidate.strategy_name}</span>
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${phaseColors[candidate.current_phase]}`}>{candidate.current_phase}</span>
                                </div>
                                <span className="text-xs text-zinc-500">&rarr; {candidate.target_phase}</span>
                              </div>
                              <div className="flex items-center gap-4 text-xs text-zinc-500">
                                <span>{perf.total_trades || 0} trades</span>
                                <span>{((perf.win_rate || 0) * 100).toFixed(0)}% WR</span>
                                <span>{(perf.avg_r_multiple || 0).toFixed(2)}R</span>
                              </div>
                              {candidate.issues && candidate.issues.length > 0 && (
                                <div className="mt-2 text-xs text-red-400/80">
                                  <span className="text-zinc-500">Missing: </span>
                                  {candidate.issues.slice(0, 2).join(' \u2022 ')}
                                  {candidate.issues.length > 2 && ` +${candidate.issues.length - 2} more`}
                                </div>
                              )}
                            </div>
                          );
                        })}
                        {pendingCandidates.length > 5 && (
                          <div className="text-xs text-zinc-500 text-center py-2">+{pendingCandidates.length - 5} more strategies in progress</div>
                        )}
                      </div>
                    </div>
                  )}

                  {(!candidates || candidates.length === 0) && (
                    <div className="text-center py-6">
                      <FlaskConical className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                      <p className="text-sm text-zinc-400">No promotion candidates</p>
                      <p className="text-xs text-zinc-500 mt-1">Run simulations and paper trades to see candidates here</p>
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Confirmation Modal for LIVE promotions */}
      <AnimatePresence>
        {showConfirmModal && selectedCandidate && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0, 0, 0, 0.8)' }}
            onClick={() => setShowConfirmModal(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-md rounded-xl border border-white/10 p-6"
              style={{ background: 'rgba(21, 28, 36, 0.98)' }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-yellow-500/20 flex items-center justify-center">
                  <AlertTriangle className="w-5 h-5 text-yellow-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">Confirm LIVE Promotion</h3>
                  <p className="text-sm text-zinc-400">This action enables real money trading</p>
                </div>
              </div>
              <div className="p-4 rounded-lg bg-yellow-500/10 border border-yellow-500/20 mb-4">
                <p className="text-sm text-yellow-400 mb-2">
                  You are about to promote <strong>{selectedCandidate.strategy_name}</strong> to LIVE status.
                </p>
                <ul className="text-xs text-zinc-400 space-y-1">
                  <li>&bull; Real trades will be executed when this strategy triggers</li>
                  <li>&bull; Actual money will be at risk</li>
                  <li>&bull; Make sure you've reviewed the performance metrics</li>
                </ul>
              </div>
              <div className="grid grid-cols-3 gap-2 mb-4">
                <div className="p-2 rounded bg-white/[0.03] text-center"><div className="text-lg font-bold text-white">{selectedCandidate.performance?.total_trades || 0}</div><div className="text-[10px] text-zinc-500">Paper Trades</div></div>
                <div className="p-2 rounded bg-white/[0.03] text-center"><div className={`text-lg font-bold ${(selectedCandidate.performance?.win_rate || 0) >= 0.52 ? 'text-green-400' : 'text-yellow-400'}`}>{((selectedCandidate.performance?.win_rate || 0) * 100).toFixed(0)}%</div><div className="text-[10px] text-zinc-500">Win Rate</div></div>
                <div className="p-2 rounded bg-white/[0.03] text-center"><div className={`text-lg font-bold ${(selectedCandidate.performance?.avg_r_multiple || 0) >= 0.4 ? 'text-green-400' : 'text-yellow-400'}`}>{(selectedCandidate.performance?.avg_r_multiple || 0).toFixed(2)}R</div><div className="text-[10px] text-zinc-500">Avg R</div></div>
              </div>
              <div className="flex gap-3">
                <button onClick={() => setShowConfirmModal(false)} className="flex-1 px-4 py-2 rounded-lg border border-white/10 text-zinc-400 hover:bg-white/5 transition-colors text-sm">Cancel</button>
                <button onClick={() => handleConfirmPromotion(selectedCandidate)} className="flex-1 px-4 py-2 rounded-lg bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-colors text-sm font-medium flex items-center justify-center gap-2">
                  <Rocket className="w-4 h-4" /> Confirm & Go LIVE
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
});

export default StrategyPipelinePanel;
