import React, { useState, useEffect, useCallback } from 'react';
import {
  Brain,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Calculator,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Sunrise,
  Target,
  Scale,
  BookOpen,
  Clock,
  Sparkles,
  X
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';

// Coaching action buttons
const CoachAction = ({ icon: Icon, label, onClick, loading, color = 'cyan' }) => {
  const colorClasses = {
    cyan: 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20',
    amber: 'bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20',
    emerald: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20',
    purple: 'bg-purple-500/10 border-purple-500/30 text-purple-400 hover:bg-purple-500/20',
    red: 'bg-red-500/10 border-red-500/30 text-red-400 hover:bg-red-500/20'
  };

  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-all disabled:opacity-50 ${colorClasses[color]}`}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Icon className="w-4 h-4" />}
      <span>{label}</span>
    </button>
  );
};

// Rule Check Form
const RuleCheckForm = ({ onCheck, loading }) => {
  const [symbol, setSymbol] = useState('');
  const [action, setAction] = useState('BUY');
  const [entryPrice, setEntryPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!symbol.trim()) {
      toast.error('Please enter a symbol');
      return;
    }
    onCheck({
      symbol: symbol.toUpperCase(),
      action,
      entry_price: entryPrice ? parseFloat(entryPrice) : null,
      stop_loss: stopLoss ? parseFloat(stopLoss) : null
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          placeholder="Symbol (e.g., AAPL)"
          className="px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          data-testid="coach-symbol-input"
        />
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
          data-testid="coach-action-select"
        >
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <input
          type="number"
          value={entryPrice}
          onChange={(e) => setEntryPrice(e.target.value)}
          placeholder="Entry Price"
          step="0.01"
          className="px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          data-testid="coach-entry-input"
        />
        <input
          type="number"
          value={stopLoss}
          onChange={(e) => setStopLoss(e.target.value)}
          placeholder="Stop Loss"
          step="0.01"
          className="px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          data-testid="coach-stop-input"
        />
      </div>
      <button
        type="submit"
        disabled={loading || !symbol.trim()}
        className="w-full py-2 bg-cyan-500 hover:bg-cyan-600 disabled:bg-zinc-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
        data-testid="coach-check-rules-btn"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
        Check Rules Before Trading
      </button>
    </form>
  );
};

// Position Sizing Form
const PositionSizingForm = ({ onCalculate, loading }) => {
  const [symbol, setSymbol] = useState('');
  const [entryPrice, setEntryPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [accountSize, setAccountSize] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!symbol.trim() || !entryPrice || !stopLoss) {
      toast.error('Please fill in symbol, entry price, and stop loss');
      return;
    }
    onCalculate({
      symbol: symbol.toUpperCase(),
      entry_price: parseFloat(entryPrice),
      stop_loss: parseFloat(stopLoss),
      account_size: accountSize ? parseFloat(accountSize) : null
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <input
        type="text"
        value={symbol}
        onChange={(e) => setSymbol(e.target.value.toUpperCase())}
        placeholder="Symbol"
        className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
      />
      <div className="grid grid-cols-2 gap-2">
        <input
          type="number"
          value={entryPrice}
          onChange={(e) => setEntryPrice(e.target.value)}
          placeholder="Entry Price"
          step="0.01"
          required
          className="px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
        />
        <input
          type="number"
          value={stopLoss}
          onChange={(e) => setStopLoss(e.target.value)}
          placeholder="Stop Loss"
          step="0.01"
          required
          className="px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
        />
      </div>
      <input
        type="number"
        value={accountSize}
        onChange={(e) => setAccountSize(e.target.value)}
        placeholder="Account Size (optional)"
        step="100"
        className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
      />
      <button
        type="submit"
        disabled={loading || !symbol.trim() || !entryPrice || !stopLoss}
        className="w-full py-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-zinc-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
        data-testid="coach-calculate-size-btn"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Calculator className="w-4 h-4" />}
        Calculate Position Size
      </button>
    </form>
  );
};

// Markdown components defined outside render to avoid recreating on each render
const markdownComponents = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="text-zinc-300">{children}</li>,
  strong: ({ children }) => <strong className="text-cyan-400 font-semibold">{children}</strong>,
  h1: ({ children }) => <h1 className="text-lg font-bold text-white mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-bold text-white mb-2">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-bold text-white mb-1">{children}</h3>,
};

// Coaching Response Display
const CoachingResponse = ({ title, response, onClose }) => {
  if (!response) return null;

  return (
    <div className="bg-zinc-900/80 border border-white/10 rounded-xl p-4 mt-4">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-amber-400" />
          <h4 className="font-semibold text-white">{title}</h4>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-zinc-500 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
      <div className="prose prose-invert prose-sm max-w-none text-zinc-300">
        <ReactMarkdown components={markdownComponents}>
          {response}
        </ReactMarkdown>
      </div>
    </div>
  );
};


// Main AI Coach Panel Component
const AICoachPanel = ({ isOpen, onClose }) => {
  const [activeTab, setActiveTab] = useState('quick');
  const [loading, setLoading] = useState({});
  const [coachingResponse, setCoachingResponse] = useState(null);
  const [responseTitle, setResponseTitle] = useState('');

  // Quick coaching actions
  const handleMorningBriefing = useCallback(async () => {
    setLoading(prev => ({ ...prev, morning: true }));
    try {
      const res = await api.get('/api/assistant/coach/morning-briefing');
      setResponseTitle('Morning Coaching');
      setCoachingResponse(res.data?.coaching || 'No response');
    } catch (err) {
      toast.error('Failed to get morning briefing');
    } finally {
      setLoading(prev => ({ ...prev, morning: false }));
    }
  }, []);

  const handleRuleReminder = useCallback(async () => {
    setLoading(prev => ({ ...prev, reminder: true }));
    try {
      const res = await api.get('/api/assistant/coach/rule-reminder');
      setResponseTitle('Rule Reminder');
      setCoachingResponse(res.data?.coaching || 'No response');
    } catch (err) {
      toast.error('Failed to get rule reminder');
    } finally {
      setLoading(prev => ({ ...prev, reminder: false }));
    }
  }, []);

  const handleDailySummary = useCallback(async () => {
    setLoading(prev => ({ ...prev, summary: true }));
    try {
      const res = await api.get('/api/assistant/coach/daily-summary');
      setResponseTitle('Daily Coaching Summary');
      setCoachingResponse(res.data?.coaching || 'No response');
    } catch (err) {
      toast.error('Failed to get daily summary');
    } finally {
      setLoading(prev => ({ ...prev, summary: false }));
    }
  }, []);

  // Rule check
  const handleRuleCheck = useCallback(async (data) => {
    setLoading(prev => ({ ...prev, rules: true }));
    try {
      const res = await api.post('/api/assistant/coach/check-rules', data);
      setResponseTitle(`Rule Check: ${data.symbol} ${data.action}`);
      setCoachingResponse(res.data?.analysis || 'No response');
    } catch (err) {
      toast.error('Failed to check rules');
    } finally {
      setLoading(prev => ({ ...prev, rules: false }));
    }
  }, []);

  // Position sizing
  const handlePositionSizing = useCallback(async (data) => {
    setLoading(prev => ({ ...prev, sizing: true }));
    try {
      const res = await api.post('/api/assistant/coach/position-size', data);
      setResponseTitle(`Position Size: ${data.symbol}`);
      setCoachingResponse(res.data?.analysis || 'No response');
    } catch (err) {
      toast.error('Failed to calculate position size');
    } finally {
      setLoading(prev => ({ ...prev, sizing: false }));
    }
  }, []);

  if (!isOpen) return null;

  const tabs = [
    { id: 'quick', label: 'Quick Actions', icon: Sparkles },
    { id: 'rules', label: 'Rule Check', icon: CheckCircle2 },
    { id: 'sizing', label: 'Position Size', icon: Calculator }
  ];

  return (
    <div className="fixed bottom-4 right-4 z-40 w-96 max-h-[600px] bg-[#0A0A0A] border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden"
         data-testid="ai-coach-panel">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/10 bg-gradient-to-r from-amber-500/5 to-purple-500/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-purple-500/20 flex items-center justify-center">
            <Brain className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h2 className="font-bold text-white flex items-center gap-2">
              AI Trading Coach
              <span className="text-xs px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded-full">BETA</span>
            </h2>
            <p className="text-xs text-zinc-500">Proactive guidance & rule enforcement</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 text-zinc-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/10">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm transition-colors ${
              activeTab === tab.id
                ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/5'
                : 'text-zinc-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            <span className="hidden sm:inline">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === 'quick' && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              <CoachAction
                icon={Sunrise}
                label="Morning Brief"
                onClick={handleMorningBriefing}
                loading={loading.morning}
                color="amber"
              />
              <CoachAction
                icon={BookOpen}
                label="Rule Reminder"
                onClick={handleRuleReminder}
                loading={loading.reminder}
                color="cyan"
              />
              <CoachAction
                icon={Clock}
                label="Daily Summary"
                onClick={handleDailySummary}
                loading={loading.summary}
                color="purple"
              />
              <CoachAction
                icon={Target}
                label="Check Setup"
                onClick={() => setActiveTab('rules')}
                loading={false}
                color="emerald"
              />
            </div>

            <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span className="text-sm font-medium text-amber-400">Coach Tips</span>
              </div>
              <ul className="text-xs text-zinc-400 space-y-1">
                <li>• Check rules BEFORE entering any trade</li>
                <li>• Get position size guidance based on your risk rules</li>
                <li>• Ask for a rule reminder when emotions run high</li>
              </ul>
            </div>
          </div>
        )}

        {activeTab === 'rules' && (
          <div>
            <p className="text-sm text-zinc-400 mb-4">
              Enter your trade idea and I'll check it against your trading rules before you execute.
            </p>
            <RuleCheckForm onCheck={handleRuleCheck} loading={loading.rules} />
          </div>
        )}

        {activeTab === 'sizing' && (
          <div>
            <p className="text-sm text-zinc-400 mb-4">
              Calculate the right position size based on your rules and the current market regime.
            </p>
            <PositionSizingForm onCalculate={handlePositionSizing} loading={loading.sizing} />
          </div>
        )}

        {/* Response Display */}
        {coachingResponse && (
          <CoachingResponse
            title={responseTitle}
            response={coachingResponse}
            onClose={() => setCoachingResponse(null)}
          />
        )}
      </div>
    </div>
  );
};

export default AICoachPanel;
