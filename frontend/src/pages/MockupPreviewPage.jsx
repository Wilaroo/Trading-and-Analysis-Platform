import React, { useState } from 'react';
import { OptionABHybridMockup, OptionDTradingDashboardMockup } from '../mockups/TradingMockups';
import LearningIntelligenceMockups from '../components/mockups/LearningIntelligenceMockups';

const MockupPreviewPage = () => {
  const [activeView, setActiveView] = useState('learning');
  
  return (
    <div className="min-h-screen bg-zinc-950">
      {/* Selector */}
      <div className="fixed top-4 left-1/2 transform -translate-x-1/2 z-50 bg-zinc-900 border border-zinc-700 rounded-lg p-1 flex gap-1">
        <button
          onClick={() => setActiveView('learning')}
          className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
            activeView === 'learning' ? 'bg-purple-500 text-white' : 'text-zinc-400 hover:text-white'
          }`}
        >
          Learning Intelligence
        </button>
        <button
          onClick={() => setActiveView('hybrid')}
          className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
            activeView === 'hybrid' ? 'bg-cyan-500 text-white' : 'text-zinc-400 hover:text-white'
          }`}
        >
          Trading Hybrid
        </button>
        <button
          onClick={() => setActiveView('dashboard')}
          className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
            activeView === 'dashboard' ? 'bg-cyan-500 text-white' : 'text-zinc-400 hover:text-white'
          }`}
        >
          Trading Dashboard
        </button>
      </div>
      
      {/* Mockup Content */}
      <div className="pt-16">
        {activeView === 'learning' && <LearningIntelligenceMockups />}
        {activeView === 'hybrid' && <OptionABHybridMockup />}
        {activeView === 'dashboard' && <OptionDTradingDashboardMockup />}
      </div>
      
      {/* Description */}
      {activeView !== 'learning' && (
      <div className="fixed bottom-4 left-4 right-4 bg-zinc-900/95 border border-zinc-700 rounded-lg p-4 max-w-2xl mx-auto">
        {activeView === 'hybrid' && (
          <div>
            <h3 className="text-white font-semibold mb-2">Option A+B: Hybrid Approach</h3>
            <ul className="text-sm text-zinc-400 space-y-1">
              <li>• <strong className="text-cyan-400">Left Panel:</strong> "Active Trading" combines Positions, Guidance, and Insights in tabs</li>
              <li>• <strong className="text-cyan-400">Center:</strong> AI Chat with compact Order Queue status bar in header</li>
              <li>• Each position shows inline micro-guidance when relevant</li>
              <li>• Clean integration without adding new panels</li>
            </ul>
          </div>
        )}
        {activeView === 'dashboard' && (
          <div>
            <h3 className="text-white font-semibold mb-2">Option D: Dedicated Trading Dashboard</h3>
            <ul className="text-sm text-zinc-400 space-y-1">
              <li>• <strong className="text-cyan-400">New "Trading" Tab:</strong> Full-screen focus when actively trading</li>
              <li>• <strong className="text-cyan-400">Left:</strong> Large position cards with P&L, stops, targets, action buttons</li>
              <li>• <strong className="text-cyan-400">Center:</strong> Visual order pipeline + In-trade guidance alerts</li>
              <li>• <strong className="text-cyan-400">Right:</strong> Performance stats + Risk status dashboard</li>
            </ul>
          </div>
        )}
      </div>
      )}
    </div>
  );
};

export default MockupPreviewPage;
