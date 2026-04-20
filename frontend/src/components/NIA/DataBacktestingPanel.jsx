import React, { useState, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Database, ChevronDown, Search, FlaskConical, ShieldCheck } from 'lucide-react';
import DataCollectionPanel from './DataCollectionPanel';
import MarketScannerPanel from '../MarketScannerPanel';
import SimulationQuickPanel from './SimulationQuickPanel';
import ValidationResultsPanel from './ValidationResultsPanel';
import ValidationSummaryCard from './ValidationSummaryCard';

const DataBacktestingPanel = memo(({ simulationJobs, backtestResults, backtestJobs, validationResults, loading, onRefresh }) => {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState('data');

  const runningJobs = (simulationJobs || []).filter(j => j.status === 'running');
  const completedJobs = (simulationJobs || []).filter(j => j.status === 'completed');
  const btResults = backtestResults || [];
  const valResults = validationResults || { total: 0, promoted: 0, rejected: 0, records: [] };

  const tabs = [
    { id: 'data', label: 'Data Collection', icon: Database, color: 'emerald' },
    { id: 'scanner', label: 'Market Scanner', icon: Search, color: 'cyan' },
    { id: 'backtest', label: 'Backtesting', icon: FlaskConical, color: 'violet' },
    { id: 'validation', label: 'Validation', icon: ShieldCheck, color: 'amber' },
  ];

  const summaryText = () => {
    const parts = [];
    if (runningJobs.length > 0) parts.push(`${runningJobs.length} running`);
    if (completedJobs.length > 0) parts.push(`${completedJobs.length} sims`);
    if (btResults.length > 0) parts.push(`${btResults.length} backtests`);
    if (valResults.total > 0) parts.push(`${valResults.promoted} validated`);
    return parts.length > 0 ? parts.join(' | ') : 'No activity yet';
  };

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="data-backtesting-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="data-backtesting-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #10b981, #8b5cf6)' }}>
            <Database className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Data, Backtesting & Validation</h3>
            <p className="text-xs text-zinc-400">{summaryText()}</p>
          </div>
        </div>
        <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
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
                  data-testid={`data-tab-${tab.id}`}
                >
                  <tab.icon className="w-3 h-3" /> {tab.label}
                  {tab.id === 'validation' && valResults.total > 0 && (
                    <span className="ml-1 px-1.5 py-0.5 rounded-full text-[9px] bg-amber-500/20 text-amber-400">{valResults.total}</span>
                  )}
                  {tab.id === 'backtest' && btResults.length > 0 && (
                    <span className="ml-1 px-1.5 py-0.5 rounded-full text-[9px] bg-violet-500/20 text-violet-400">{btResults.length}</span>
                  )}
                </button>
              ))}
            </div>

            <div className="p-4">
              {activeTab === 'data' && <DataCollectionPanel onRefresh={onRefresh} />}
              {activeTab === 'scanner' && <MarketScannerPanel />}
              {activeTab === 'backtest' && (
                <SimulationQuickPanel
                  jobs={simulationJobs}
                  backtestResults={btResults}
                  backtestJobs={backtestJobs}
                  loading={loading}
                  onRefresh={onRefresh}
                />
              )}
              {activeTab === 'validation' && (
                <div className="space-y-4" data-testid="validation-tab-content">
                  <ValidationSummaryCard />
                  <ValidationResultsPanel
                    validationResults={valResults}
                    onRefresh={onRefresh}
                  />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default DataBacktestingPanel;
