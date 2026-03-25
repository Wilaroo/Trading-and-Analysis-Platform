import React, { useState, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { GitBranch, ChevronDown, BarChart3 } from 'lucide-react';
import StrategyPipelinePanel from './StrategyPipelinePanel';
import ReportCardPanel from './ReportCardPanel';

const StrategyPerformancePanel = memo(({ phases, candidates, reportCard, loading, onPromote, onDemote }) => {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState('pipeline');

  const readyCandidates = (candidates || []).filter(c => c.meets_requirements);
  const totalTrades = reportCard?.overall_stats?.total_trades || 0;

  const tabs = [
    { id: 'pipeline', label: 'Strategy Pipeline', icon: GitBranch, color: 'blue' },
    { id: 'report', label: 'Report Card', icon: BarChart3, color: 'amber' },
  ];

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="strategy-performance-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="strategy-performance-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #3b82f6, #f59e0b)' }}>
            <GitBranch className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Strategy & Performance</h3>
            <p className="text-xs text-zinc-400">Pipeline, promotions & report card</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {readyCandidates.length > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 animate-pulse">{readyCandidates.length} ready</span>
          )}
          {totalTrades > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">{totalTrades} trades</span>
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
            <div className="flex border-b border-white/10">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${
                    activeTab === tab.id
                      ? `text-${tab.color}-400 border-b-2 border-${tab.color}-400 bg-${tab.color}-500/5`
                      : 'text-zinc-500 hover:text-zinc-300'
                  }`}
                  data-testid={`strategy-tab-${tab.id}`}
                >
                  <tab.icon className="w-3 h-3" /> {tab.label}
                </button>
              ))}
            </div>

            <div className="p-4">
              {activeTab === 'pipeline' && (
                <StrategyPipelinePanel
                  phases={phases}
                  candidates={candidates}
                  loading={loading}
                  onPromote={onPromote}
                  onDemote={onDemote}
                />
              )}
              {activeTab === 'report' && (
                <ReportCardPanel reportCard={reportCard} loading={loading} />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default StrategyPerformancePanel;
