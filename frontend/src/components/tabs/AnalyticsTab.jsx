import React, { useState } from 'react';
import BacktestPanel from '../BacktestPanel';
import ShadowModePanel from '../ShadowModePanel';
import MarketScannerPanel from '../MarketScannerPanel';
import { Card } from '../shared/UIComponents';
import { Brain, TestTubes, Layers, Search, ArrowRight } from 'lucide-react';

/**
 * Analytics Tab - Market Analysis Tools
 * 
 * Restructured to show:
 * - Market Scanner: Full US market strategy scanning
 * - Backtest: Deep-dive into strategy backtesting
 * - Shadow Mode: Paper trading filter validation
 * 
 * Note: Intelligence Hub has been moved to NIA (Neural Intelligence Agency)
 */
const AnalyticsTab = () => {
  const [activeSubTab, setActiveSubTab] = useState('scanner');
  
  const subTabs = [
    { id: 'scanner', label: 'Market Scanner', icon: Search, description: 'Full market scanning' },
    { id: 'backtest', label: 'Backtest', icon: TestTubes, description: 'Strategy backtesting' },
    { id: 'shadow', label: 'Shadow Mode', icon: Layers, description: 'Paper trading filters' }
  ];
  
  return (
    <div className="space-y-4 mt-2" data-testid="analytics-tab-content">
      {/* NIA Redirect Banner */}
      <div className="p-3 rounded-lg bg-gradient-to-r from-cyan-500/10 to-violet-500/10 border border-cyan-500/20 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain className="w-5 h-5 text-cyan-400" />
          <div>
            <p className="text-sm text-white">Looking for Learning Intelligence?</p>
            <p className="text-xs text-zinc-400">AI insights and training are now in NIA</p>
          </div>
        </div>
        <a 
          href="#" 
          onClick={(e) => { e.preventDefault(); window.dispatchEvent(new CustomEvent('navigate', { detail: 'nia' })); }}
          className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
        >
          Go to NIA <ArrowRight className="w-3 h-3" />
        </a>
      </div>

      {/* Sub-Tab Navigation */}
      <div className="flex items-center gap-2 bg-white/5 p-1.5 rounded-lg border border-white/10" data-testid="analytics-subtabs">
        {subTabs.map(tab => {
          const Icon = tab.icon;
          const isActive = activeSubTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveSubTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                isActive
                  ? 'bg-purple-400/10 text-purple-400 border border-purple-400/30 shadow-[0_0_10px_rgba(168,85,247,0.15)]'
                  : 'text-zinc-500 hover:text-zinc-300 hover:bg-white/5 border border-transparent'
              }`}
              data-testid={`analytics-subtab-${tab.id}`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'drop-shadow-[0_0_4px_rgba(168,85,247,0.5)]' : ''}`} />
              {tab.label}
            </button>
          );
        })}
      </div>
      
      {/* Sub-Tab Content */}
      {activeSubTab === 'scanner' && (
        <MarketScannerPanel />
      )}
      
      {activeSubTab === 'backtest' && (
        <BacktestPanel />
      )}
      
      {activeSubTab === 'shadow' && (
        <ShadowModePanel />
      )}
    </div>
  );
};

export default AnalyticsTab;
