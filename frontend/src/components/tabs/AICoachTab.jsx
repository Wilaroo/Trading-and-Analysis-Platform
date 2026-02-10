import React from 'react';
import { ChevronDown, Newspaper } from 'lucide-react';
import AICommandPanel from '../AICommandPanel';
import { Card } from '../shared/UIComponents';

const AICoachTab = ({
  setSelectedTicker,
  watchlist,
  enhancedAlerts,
  alerts,
  opportunities,
  earnings,
  positions,
  marketContext,
  isConnected,
  runScanner,
  newsletter,
  expandedSections,
  toggleSection,
}) => {
  return (
    <div className="grid lg:grid-cols-12 gap-4 mt-2" data-testid="ai-coach-tab-content">
      {/* CENTER - AI Command Panel */}
      <div className="lg:col-span-9">
        <div className="h-[calc(100vh-220px)] min-h-[600px]">
          <AICommandPanel
            onTickerSelect={(ticker) => setSelectedTicker(ticker)}
            watchlist={watchlist}
            alerts={[...enhancedAlerts, ...alerts]}
            opportunities={opportunities}
            earnings={earnings}
            portfolio={positions}
            scanResults={opportunities}
            marketIndices={marketContext?.indices || []}
            isConnected={isConnected}
            onRefresh={() => runScanner()}
          />
        </div>
      </div>

      {/* Right - Market Intel */}
      <div className="lg:col-span-3 space-y-4">
        <Card>
          <div 
            onClick={() => toggleSection('news')}
            className="w-full flex items-center justify-between mb-3 cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <Newspaper className="w-5 h-5 text-purple-400" />
              <h3 className="text-sm font-semibold uppercase tracking-wider">Market Intel</h3>
            </div>
            <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.news ? 'rotate-180' : ''}`} />
          </div>
          
          {expandedSections.news && newsletter && (
            <div className="space-y-2 max-h-[200px] overflow-y-auto">
              {newsletter.top_stories?.slice(0, 3).map((story, idx) => (
                <div key={idx} className="p-2 bg-zinc-900/50 rounded">
                  <p className="text-xs text-zinc-300">{story.headline || story}</p>
                </div>
              ))}
              {!newsletter.top_stories?.length && (
                <p className="text-xs text-zinc-500 text-center py-2">No market intel available</p>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};

export default AICoachTab;
