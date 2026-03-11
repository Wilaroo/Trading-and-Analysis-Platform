import React, { useState } from 'react';
import LearningIntelligenceHub from '../LearningIntelligenceHub';
import BacktestPanel from '../BacktestPanel';
import ShadowModePanel from '../ShadowModePanel';
import { Card } from '../shared/UIComponents';
import { Brain, TestTubes, Layers } from 'lucide-react';

/**
 * Analytics Tab - Learning Intelligence Hub
 * 
 * Restructured to show:
 * - Intelligence Hub (default): Unified view of all learning insights
 * - Backtest: Deep-dive into strategy backtesting
 * - Shadow Mode: Paper trading filter validation
 * 
 * The Intelligence Hub consolidates what was previously scattered across
 * multiple tabs, providing a single source of truth for trader performance.
 */
const AnalyticsTab = () => {
  const [activeSubTab, setActiveSubTab] = useState('hub');
  
  const subTabs = [
    { id: 'hub', label: 'Intelligence Hub', icon: Brain, description: 'Unified learning insights' },
    { id: 'backtest', label: 'Backtest', icon: TestTubes, description: 'Strategy backtesting' },
    { id: 'shadow', label: 'Shadow Mode', icon: Layers, description: 'Paper trading filters' }
  ];
  
  return (
    <div className="space-y-4 mt-2" data-testid="analytics-tab-content">
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
      {activeSubTab === 'hub' && (
        <LearningIntelligenceHub />
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
