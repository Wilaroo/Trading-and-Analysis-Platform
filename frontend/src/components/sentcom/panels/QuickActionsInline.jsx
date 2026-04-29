import React from 'react';
import { BarChart3, BookOpen, Loader, Newspaper, Sunrise, Target, TrendingUp } from 'lucide-react';

// Inline Quick Actions - Always visible above chat input
export const QuickActionsInline = ({ onAction, onCheckTrade, loading, showTradeForm, setShowTradeForm }) => {
  const quickActions = [
    { id: 'performance', icon: BarChart3, label: 'Performance', color: 'emerald', 
      prompt: "Analyze our trading performance. What's our win rate, profit factor, and what are our strengths and weaknesses? Give us actionable recommendations." },
    { id: 'news', icon: Newspaper, label: 'News', color: 'cyan',
      prompt: "What's happening in the market today? Give us the key headlines and themes affecting our watchlist." },
    { id: 'morning', icon: Sunrise, label: 'Brief', color: 'amber',
      endpoint: '/api/assistant/coach/morning-briefing' },
    { id: 'rules', icon: BookOpen, label: 'Rules', color: 'violet',
      endpoint: '/api/assistant/coach/rule-reminder' },
    { id: 'summary', icon: TrendingUp, label: 'Summary', color: 'purple',
      endpoint: '/api/assistant/coach/daily-summary' },
  ];

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {quickActions.map((action) => {
        const Icon = action.icon;
        const isLoading = loading === action.id;
        return (
          <button
            key={action.id}
            onClick={() => onAction(action)}
            disabled={isLoading}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[13px] font-medium transition-all border
              ${isLoading ? 'opacity-50' : 'hover:scale-105'}
              ${action.color === 'emerald' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20' :
                action.color === 'cyan' ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20' :
                action.color === 'amber' ? 'bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20' :
                action.color === 'violet' ? 'bg-violet-500/10 border-violet-500/30 text-violet-400 hover:bg-violet-500/20' :
                'bg-purple-500/10 border-purple-500/30 text-purple-400 hover:bg-purple-500/20'
              }`}
            data-testid={`quick-action-${action.id}`}
          >
            {isLoading ? <Loader className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
            {action.label}
          </button>
        );
      })}
      <button
        onClick={() => setShowTradeForm(!showTradeForm)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[13px] font-medium transition-all border
          ${showTradeForm 
            ? 'bg-gradient-to-r from-cyan-500/20 to-emerald-500/20 border-cyan-500/50 text-cyan-400' 
            : 'bg-zinc-800/50 border-white/10 text-zinc-300 hover:border-cyan-500/30 hover:bg-zinc-800'
          }`}
        data-testid="check-trade-btn"
      >
        <Target className="w-3 h-3" />
        Check Trade
      </button>
    </div>
  );
};
