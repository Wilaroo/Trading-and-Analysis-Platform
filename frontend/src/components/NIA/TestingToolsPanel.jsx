import React, { useState, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Shuffle, ChevronDown } from 'lucide-react';
import MarketScannerPanel from '../MarketScannerPanel';
import AdvancedBacktestPanel from '../AdvancedBacktestPanel';

const TestingToolsPanel = memo(() => {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState('scanner');

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="testing-tools-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="testing-tools-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-emerald-500/20">
            <Search className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Testing & Scanning</h3>
            <p className="text-xs text-zinc-400">Market scanner, walk-forward & Monte Carlo</p>
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
            {/* Tabs */}
            <div className="flex border-b border-white/10">
              <button
                onClick={() => setActiveTab('scanner')}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${
                  activeTab === 'scanner'
                    ? 'text-emerald-400 border-b-2 border-emerald-400 bg-emerald-500/5'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
                data-testid="testing-tab-scanner"
              >
                <Search className="w-3 h-3" /> Market Scanner
              </button>
              <button
                onClick={() => setActiveTab('advanced')}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${
                  activeTab === 'advanced'
                    ? 'text-amber-400 border-b-2 border-amber-400 bg-amber-500/5'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
                data-testid="testing-tab-advanced"
              >
                <Shuffle className="w-3 h-3" /> Advanced Testing
              </button>
            </div>

            <div className="p-4">
              {activeTab === 'scanner' ? <MarketScannerPanel /> : <AdvancedBacktestPanel />}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default TestingToolsPanel;
