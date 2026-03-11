/**
 * Learning Intelligence Mockups
 * =============================
 * Three design options for consolidating Learning Dashboard, Learning Loop & Analytics
 * 
 * This is a MOCKUP PAGE - not for production use.
 * Access at: /mockups/learning-intelligence
 */

import React, { useState } from 'react';
import { 
  Brain, TrendingUp, TrendingDown, Target, AlertTriangle, CheckCircle2,
  BarChart3, Activity, Zap, Clock, Calendar, ChevronRight, ChevronDown,
  Lightbulb, Shield, TestTubes, Layers, GraduationCap, LineChart,
  ArrowUpRight, ArrowDownRight, Minus, Eye, Settings, RefreshCw
} from 'lucide-react';

// ============================================================================
// OPTION A: Enhanced Analytics Tab with Summary Sub-tab
// ============================================================================

const OptionA_EnhancedAnalytics = () => {
  const [activeSubTab, setActiveSubTab] = useState('summary');
  
  const subTabs = [
    { id: 'summary', label: 'Summary', icon: Brain },
    { id: 'learning', label: 'Learning', icon: GraduationCap },
    { id: 'backtest', label: 'Backtest', icon: TestTubes },
    { id: 'shadow', label: 'Shadow Mode', icon: Layers }
  ];
  
  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      <div className="max-w-6xl mx-auto">
        <h2 className="text-2xl font-bold text-white mb-2">Option A: Enhanced Analytics Tab</h2>
        <p className="text-slate-400 mb-6">Add a "Summary" sub-tab to existing Analytics structure</p>
        
        {/* Sub-Tab Navigation */}
        <div className="flex items-center gap-2 bg-slate-800/50 p-1.5 rounded-lg border border-slate-700/50 mb-6">
          {subTabs.map(tab => {
            const Icon = tab.icon;
            const isActive = activeSubTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveSubTab(tab.id)}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  isActive
                    ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
                }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
        
        {/* Summary Content (NEW) */}
        {activeSubTab === 'summary' && (
          <div className="space-y-4">
            {/* Top Row - Key Metrics */}
            <div className="grid grid-cols-4 gap-4">
              <MetricCard 
                title="Win Rate" 
                value="62%" 
                change="+3.2%" 
                trend="up"
                subtitle="Last 30 days"
              />
              <MetricCard 
                title="Avg R-Multiple" 
                value="1.8R" 
                change="+0.2" 
                trend="up"
                subtitle="Risk/Reward"
              />
              <MetricCard 
                title="Profit Factor" 
                value="2.1" 
                change="-0.1" 
                trend="down"
                subtitle="Gross P / Gross L"
              />
              <MetricCard 
                title="Edge Score" 
                value="78" 
                change="Healthy" 
                trend="neutral"
                subtitle="Overall health"
              />
            </div>
            
            {/* Middle Row - Edge Health & Recommendations */}
            <div className="grid grid-cols-2 gap-4">
              <EdgeHealthCard />
              <RecommendationsCard />
            </div>
            
            {/* Bottom - Performance Chart Placeholder */}
            <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
              <h3 className="text-sm font-medium text-slate-300 mb-3">30-Day Performance</h3>
              <div className="h-32 bg-slate-900/50 rounded-lg flex items-center justify-center">
                <div className="flex items-end gap-1 h-20">
                  {[40, 55, 45, 60, 50, 70, 65, 80, 75, 85, 70, 90, 85, 95, 88].map((h, i) => (
                    <div 
                      key={i} 
                      className={`w-4 rounded-t ${h > 60 ? 'bg-emerald-500/60' : 'bg-red-500/60'}`}
                      style={{ height: `${h}%` }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
        
        {activeSubTab !== 'summary' && (
          <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-8 text-center">
            <p className="text-slate-400">Existing {activeSubTab} content would go here</p>
          </div>
        )}
      </div>
    </div>
  );
};

// ============================================================================
// OPTION B: Full Intelligence Hub Redesign
// ============================================================================

const OptionB_IntelligenceHub = () => {
  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      <div className="max-w-6xl mx-auto">
        <h2 className="text-2xl font-bold text-white mb-2">Option B: Learning Intelligence Hub</h2>
        <p className="text-slate-400 mb-6">Complete redesign - unified dashboard replacing Analytics tab</p>
        
        {/* Header with Trader Profile */}
        <div className="bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-xl border border-purple-500/20 p-5 mb-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 rounded-full bg-purple-500/20 flex items-center justify-center">
                <Brain className="w-8 h-8 text-purple-400" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-white">Trader Profile</h3>
                <p className="text-slate-400 text-sm">Based on 847 trades over 6 months</p>
              </div>
            </div>
            <div className="flex gap-6">
              <ProfileStat label="Best Time" value="10-11 AM" />
              <ProfileStat label="Best Setup" value="ORB" />
              <ProfileStat label="Best Regime" value="Trending" />
              <ProfileStat label="Avg Hold" value="23 min" />
            </div>
          </div>
        </div>
        
        {/* Main Grid */}
        <div className="grid grid-cols-3 gap-4 mb-4">
          {/* Left Column - Metrics */}
          <div className="space-y-4">
            <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
              <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Performance Metrics
              </h3>
              <div className="space-y-3">
                <MetricRow label="Win Rate" value="62%" badge="+3.2%" positive />
                <MetricRow label="Profit Factor" value="2.1" badge="Good" neutral />
                <MetricRow label="Avg Winner" value="$284" badge="+$12" positive />
                <MetricRow label="Avg Loser" value="$142" badge="-$8" negative />
                <MetricRow label="Expectancy" value="$89/trade" badge="+$5" positive />
              </div>
            </div>
            
            <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
              <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
                <Calendar className="w-4 h-4" />
                This Week
              </h3>
              <div className="grid grid-cols-5 gap-1">
                {['M', 'T', 'W', 'T', 'F'].map((day, i) => (
                  <div key={day} className="text-center">
                    <div className="text-xs text-slate-500 mb-1">{day}</div>
                    <div className={`w-8 h-8 mx-auto rounded-lg flex items-center justify-center text-xs font-medium ${
                      i < 3 ? (i === 1 ? 'bg-red-500/20 text-red-400' : 'bg-emerald-500/20 text-emerald-400') : 'bg-slate-700/50 text-slate-500'
                    }`}>
                      {i < 3 ? (i === 1 ? '-$120' : '+$180') : '--'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          
          {/* Center Column - Edge Health */}
          <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
            <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <Shield className="w-4 h-4" />
              Edge Health Monitor
            </h3>
            <div className="space-y-3">
              <EdgeRow setup="ORB Breakout" status="healthy" winRate="68%" trades={124} />
              <EdgeRow setup="VWAP Bounce" status="warning" winRate="52%" trades={89} decay />
              <EdgeRow setup="Gap & Go" status="critical" winRate="41%" trades={45} decay />
              <EdgeRow setup="First Pullback" status="healthy" winRate="64%" trades={156} />
              <EdgeRow setup="HOD Break" status="healthy" winRate="59%" trades={78} />
              <EdgeRow setup="Mean Reversion" status="warning" winRate="48%" trades={34} />
            </div>
            <button className="w-full mt-3 py-2 text-xs text-purple-400 hover:text-purple-300 border border-purple-500/30 rounded-lg hover:bg-purple-500/10">
              View All Setups →
            </button>
          </div>
          
          {/* Right Column - AI Recommendations */}
          <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
            <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <Lightbulb className="w-4 h-4 text-yellow-400" />
              AI Recommendations
            </h3>
            <div className="space-y-3">
              <RecommendationItem 
                type="optimize"
                text="Your ORB setups work best in TRENDING markets (72% vs 54%)"
                action="Filter by regime"
              />
              <RecommendationItem 
                type="warning"
                text="Gap & Go edge has degraded 15% over 2 weeks. Consider pausing."
                action="Pause setup"
              />
              <RecommendationItem 
                type="opportunity"
                text="Strong performance 10-11 AM. Consider focusing trades here."
                action="Set reminder"
              />
              <RecommendationItem 
                type="calibrate"
                text="TQS threshold could drop to 68 based on recent accuracy."
                action="Apply change"
              />
            </div>
          </div>
        </div>
        
        {/* Bottom Row - Collapsible Sections */}
        <div className="grid grid-cols-2 gap-4">
          <CollapsibleSection title="Backtest Results" icon={TestTubes}>
            <p className="text-slate-400 text-sm">Last backtest: +12.3% over 3 months</p>
          </CollapsibleSection>
          <CollapsibleSection title="Shadow Mode" icon={Layers}>
            <p className="text-slate-400 text-sm">3 filters active, 2 pending validation</p>
          </CollapsibleSection>
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// OPTION C: Compact Widget + Detailed Tab
// ============================================================================

const OptionC_WidgetApproach = () => {
  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      <div className="max-w-6xl mx-auto">
        <h2 className="text-2xl font-bold text-white mb-2">Option C: Widget + Detailed Tab</h2>
        <p className="text-slate-400 mb-6">Compact widget on main screen, click to expand to full Analytics</p>
        
        <div className="grid grid-cols-2 gap-8">
          {/* Left: Simulated Main Trading View */}
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-3">Main Trading View (AI Coach Tab)</h3>
            <div className="bg-slate-800/30 rounded-xl border border-slate-700/50 p-4 space-y-4">
              {/* Simulated Header */}
              <div className="h-12 bg-slate-700/30 rounded-lg flex items-center px-4">
                <span className="text-slate-400 text-sm">Header Bar</span>
              </div>
              
              {/* Learning Insights Widget - THE NEW WIDGET */}
              <div className="bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-xl border border-purple-500/30 p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Brain className="w-4 h-4 text-purple-400" />
                    <span className="text-sm font-medium text-white">Learning Insights</span>
                  </div>
                  <button className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1">
                    View Details <ChevronRight className="w-3 h-3" />
                  </button>
                </div>
                
                <div className="grid grid-cols-4 gap-3">
                  <MiniStat label="Win Rate" value="62%" trend="up" />
                  <MiniStat label="Today P&L" value="+$340" trend="up" />
                  <MiniStat label="Avg R" value="1.8" trend="neutral" />
                  <MiniStat label="Edge" value="78" trend="neutral" />
                </div>
                
                {/* Alert Row */}
                <div className="mt-3 flex items-center gap-2 text-xs">
                  <AlertTriangle className="w-3 h-3 text-yellow-400" />
                  <span className="text-yellow-400">Gap & Go edge degrading</span>
                  <span className="text-slate-500">•</span>
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  <span className="text-emerald-400">ORB performing well</span>
                </div>
              </div>
              
              {/* Simulated Chat Area */}
              <div className="h-48 bg-slate-700/20 rounded-lg flex items-center justify-center">
                <span className="text-slate-500 text-sm">AI Chat Area</span>
              </div>
              
              {/* Simulated Alerts */}
              <div className="h-24 bg-slate-700/20 rounded-lg flex items-center justify-center">
                <span className="text-slate-500 text-sm">Scanner Alerts</span>
              </div>
            </div>
          </div>
          
          {/* Right: Expanded Analytics Tab */}
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-3">Expanded Analytics Tab (Click to open)</h3>
            <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4 space-y-4">
              {/* Tab Header */}
              <div className="flex items-center gap-2 bg-slate-700/30 p-1 rounded-lg">
                <button className="flex-1 py-2 text-xs text-purple-400 bg-purple-500/20 rounded">Overview</button>
                <button className="flex-1 py-2 text-xs text-slate-400 hover:text-slate-300">Performance</button>
                <button className="flex-1 py-2 text-xs text-slate-400 hover:text-slate-300">Validation</button>
                <button className="flex-1 py-2 text-xs text-slate-400 hover:text-slate-300">History</button>
              </div>
              
              {/* Overview Content */}
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-900/50 rounded-lg p-3">
                  <div className="text-xs text-slate-500 mb-1">Today</div>
                  <div className="text-lg font-bold text-emerald-400">+$340</div>
                  <div className="text-xs text-slate-400">5W / 2L</div>
                </div>
                <div className="bg-slate-900/50 rounded-lg p-3">
                  <div className="text-xs text-slate-500 mb-1">This Week</div>
                  <div className="text-lg font-bold text-emerald-400">+$1,240</div>
                  <div className="text-xs text-slate-400">18W / 9L</div>
                </div>
              </div>
              
              {/* Edge Alerts */}
              <div className="bg-slate-900/50 rounded-lg p-3">
                <div className="text-xs font-medium text-slate-300 mb-2">Edge Alerts</div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-yellow-400">⚠️ Gap & Go: -15% edge decay</span>
                    <button className="text-slate-400 hover:text-white">Pause</button>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-emerald-400">✓ ORB: +8% improvement</span>
                    <button className="text-slate-400 hover:text-white">Details</button>
                  </div>
                </div>
              </div>
              
              {/* Recommendations */}
              <div className="bg-slate-900/50 rounded-lg p-3">
                <div className="text-xs font-medium text-slate-300 mb-2">Top Recommendation</div>
                <div className="flex items-start gap-2">
                  <Lightbulb className="w-4 h-4 text-yellow-400 mt-0.5" />
                  <div>
                    <p className="text-xs text-slate-300">Focus on ORB setups in trending markets</p>
                    <p className="text-xs text-slate-500 mt-1">72% win rate vs 54% in ranging</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// Shared Components
// ============================================================================

const MetricCard = ({ title, value, change, trend, subtitle }) => (
  <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
    <div className="text-xs text-slate-500 mb-1">{title}</div>
    <div className="flex items-baseline gap-2">
      <span className="text-2xl font-bold text-white">{value}</span>
      <span className={`text-xs ${
        trend === 'up' ? 'text-emerald-400' : 
        trend === 'down' ? 'text-red-400' : 'text-slate-400'
      }`}>
        {change}
      </span>
    </div>
    <div className="text-xs text-slate-500 mt-1">{subtitle}</div>
  </div>
);

const EdgeHealthCard = () => (
  <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
    <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
      <Shield className="w-4 h-4" />
      Edge Health
    </h3>
    <div className="space-y-2">
      <EdgeRow setup="ORB Breakout" status="healthy" winRate="68%" trades={124} />
      <EdgeRow setup="VWAP Bounce" status="warning" winRate="52%" trades={89} decay />
      <EdgeRow setup="Gap & Go" status="critical" winRate="41%" trades={45} decay />
    </div>
  </div>
);

const RecommendationsCard = () => (
  <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
    <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
      <Lightbulb className="w-4 h-4 text-yellow-400" />
      AI Recommendations
    </h3>
    <div className="space-y-2">
      <RecommendationItem 
        type="optimize"
        text="ORB works best in TRENDING markets"
        action="Apply filter"
        compact
      />
      <RecommendationItem 
        type="warning"
        text="Gap & Go edge degraded 15%"
        action="Pause"
        compact
      />
    </div>
  </div>
);

const EdgeRow = ({ setup, status, winRate, trades, decay }) => (
  <div className="flex items-center justify-between py-1">
    <div className="flex items-center gap-2">
      <div className={`w-2 h-2 rounded-full ${
        status === 'healthy' ? 'bg-emerald-400' :
        status === 'warning' ? 'bg-yellow-400' : 'bg-red-400'
      }`} />
      <span className="text-sm text-slate-300">{setup}</span>
      {decay && <TrendingDown className="w-3 h-3 text-red-400" />}
    </div>
    <div className="flex items-center gap-3 text-xs">
      <span className="text-slate-400">{trades} trades</span>
      <span className={`font-medium ${
        parseInt(winRate) >= 60 ? 'text-emerald-400' :
        parseInt(winRate) >= 50 ? 'text-yellow-400' : 'text-red-400'
      }`}>{winRate}</span>
    </div>
  </div>
);

const RecommendationItem = ({ type, text, action, compact }) => {
  const icons = {
    optimize: <Zap className="w-4 h-4 text-blue-400" />,
    warning: <AlertTriangle className="w-4 h-4 text-yellow-400" />,
    opportunity: <Target className="w-4 h-4 text-emerald-400" />,
    calibrate: <Settings className="w-4 h-4 text-purple-400" />
  };
  
  return (
    <div className={`flex items-start gap-2 ${compact ? 'py-1' : 'p-2 bg-slate-900/30 rounded-lg'}`}>
      {icons[type]}
      <div className="flex-1">
        <p className={`text-slate-300 ${compact ? 'text-xs' : 'text-sm'}`}>{text}</p>
        {!compact && (
          <button className="text-xs text-purple-400 hover:text-purple-300 mt-1">
            {action} →
          </button>
        )}
      </div>
      {compact && (
        <button className="text-xs text-purple-400 hover:text-purple-300">
          {action}
        </button>
      )}
    </div>
  );
};

const ProfileStat = ({ label, value }) => (
  <div className="text-center">
    <div className="text-xs text-slate-500">{label}</div>
    <div className="text-sm font-medium text-white">{value}</div>
  </div>
);

const MetricRow = ({ label, value, badge, positive, negative, neutral }) => (
  <div className="flex items-center justify-between">
    <span className="text-sm text-slate-400">{label}</span>
    <div className="flex items-center gap-2">
      <span className="text-sm font-medium text-white">{value}</span>
      <span className={`text-xs px-1.5 py-0.5 rounded ${
        positive ? 'bg-emerald-500/20 text-emerald-400' :
        negative ? 'bg-red-500/20 text-red-400' : 'bg-slate-600/50 text-slate-400'
      }`}>{badge}</span>
    </div>
  </div>
);

const MiniStat = ({ label, value, trend }) => (
  <div className="text-center">
    <div className="text-xs text-slate-500">{label}</div>
    <div className={`text-sm font-bold ${
      trend === 'up' ? 'text-emerald-400' :
      trend === 'down' ? 'text-red-400' : 'text-white'
    }`}>{value}</div>
  </div>
);

const CollapsibleSection = ({ title, icon: Icon, children }) => {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50">
      <button 
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 text-left"
      >
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-slate-400" />
          <span className="text-sm font-medium text-slate-300">{title}</span>
        </div>
        {expanded ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
      </button>
      {expanded && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
};

// ============================================================================
// Main Mockups Page
// ============================================================================

const LearningIntelligenceMockups = () => {
  const [activeOption, setActiveOption] = useState('A');
  
  return (
    <div className="min-h-screen bg-slate-950">
      {/* Option Selector */}
      <div className="sticky top-0 z-50 bg-slate-950/95 backdrop-blur border-b border-slate-800 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-4">
          <span className="text-slate-400 text-sm">Select Option:</span>
          {['A', 'B', 'C'].map(opt => (
            <button
              key={opt}
              onClick={() => setActiveOption(opt)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                activeOption === opt
                  ? 'bg-purple-500 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-white'
              }`}
            >
              Option {opt}
            </button>
          ))}
        </div>
      </div>
      
      {/* Content */}
      {activeOption === 'A' && <OptionA_EnhancedAnalytics />}
      {activeOption === 'B' && <OptionB_IntelligenceHub />}
      {activeOption === 'C' && <OptionC_WidgetApproach />}
    </div>
  );
};

export default LearningIntelligenceMockups;
