/**
 * SentCom.jsx - Sentient Command
 * 
 * Production component for the unified AI command center.
 * Wired to real /api/sentcom/* endpoints.
 * Uses "we" voice throughout for team partnership feeling.
 * 
 * Updated with glassy mockup styling and unified Trading Bot header controls.
 * 
 * Performance Optimization:
 * - Uses DataCacheContext for persistent data across tab switches
 * - Stale-while-revalidate pattern for instant display
 */
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import ReactDOM from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Send, Brain, Clock, Zap, Target, AlertCircle, ArrowRight, 
  CheckCircle, Loader, X, TrendingUp, Activity, ChevronUp, 
  ChevronDown, DollarSign, Gauge, Wifi, Eye, Crosshair,
  MessageSquare, RefreshCw, Bell, Circle, Flame, Radio,
  BarChart3, Newspaper, Sunrise, BookOpen, Sparkles, ChevronRight,
  Play, Pause, Settings, Bot, Sliders, WifiOff, Star, Search
} from 'lucide-react';
import { toast } from 'sonner';
import { safePolling } from '../utils/safePolling';
import EnhancedTickerModal from './EnhancedTickerModal';
import ClickableTicker from './shared/ClickableTicker';
import { useDataCache } from '../contexts';
import { DynamicRiskBadge, DynamicRiskPanel } from './DynamicRiskPanel';
import ServerHealthBadge from './ServerHealthBadge';
import TradeExecutionHealthCard from './TradeExecutionHealthCard';
import BotHealthBanner from './BotHealthBanner';
import StreamOfConsciousness from './StreamOfConsciousness';
import ConversationPanel from './ConversationPanel';
import ChatBubbleOverlay from './ChatBubbleOverlay';
import StatusDot from './StatusDot';
import api, { safeGet, safePost } from '../utils/api';
import { useWsData } from '../contexts/WebSocketDataContext';

// Extracted primitives + utils (Stage 1 SentCom refactor, 2026-04-23)
import { formatRelativeTime, formatFullTime } from './sentcom/utils/time';
import { TypingIndicator } from './sentcom/primitives/TypingIndicator';
import { HoverTimestamp } from './sentcom/primitives/HoverTimestamp';
import { StreamMessage } from './sentcom/primitives/StreamMessage';
import { Sparkline, generateSparklineData } from './sentcom/primitives/Sparkline';
import { GlassCard } from './sentcom/primitives/GlassCard';
import { PulsingDot } from './sentcom/primitives/PulsingDot';

// Extracted hooks (Stage 1 SentCom refactor — Batch 2, 2026-04-23)
import { useAIInsights } from './sentcom/hooks/useAIInsights';
import { useMarketSession } from './sentcom/hooks/useMarketSession';
import { useSentComStatus } from './sentcom/hooks/useSentComStatus';
import { useSentComStream } from './sentcom/hooks/useSentComStream';
import { useSentComPositions } from './sentcom/hooks/useSentComPositions';
import { useSentComSetups } from './sentcom/hooks/useSentComSetups';
import { useSentComContext } from './sentcom/hooks/useSentComContext';
import { useSentComAlerts } from './sentcom/hooks/useSentComAlerts';
import { useChatHistory } from './sentcom/hooks/useChatHistory';
import { useTradingBotControl } from './sentcom/hooks/useTradingBotControl';
import { useIBConnectionStatus } from './sentcom/hooks/useIBConnectionStatus';
import { useAIModules } from './sentcom/hooks/useAIModules';

// Extracted panels (Stage 1 SentCom refactor — Batch 3, 2026-04-23)
import { CheckMyTradeForm } from './sentcom/panels/CheckMyTradeForm';
import { QuickActionsInline } from './sentcom/panels/QuickActionsInline';
import { StopFixPanel } from './sentcom/panels/StopFixPanel';
import { RiskControlsPanel } from './sentcom/panels/RiskControlsPanel';
import { AIModulesPanel } from './sentcom/panels/AIModulesPanel';
import { AIInsightsDashboard } from './sentcom/panels/AIInsightsDashboard';
import { OrderPipeline } from './sentcom/panels/OrderPipeline';
import { StatusHeader } from './sentcom/panels/StatusHeader';
import { PositionsPanel } from './sentcom/panels/PositionsPanel';
import { StreamPanel } from './sentcom/panels/StreamPanel';
import { ContextPanel } from './sentcom/panels/ContextPanel';
import { MarketIntelPanel } from './sentcom/panels/MarketIntelPanel';
import { AlertsPanel } from './sentcom/panels/AlertsPanel';
import { SetupsPanel } from './sentcom/panels/SetupsPanel';
import { ChatInput } from './sentcom/panels/ChatInput';

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const SentCom = ({ compact = false, embedded = false }) => {
  const { status, loading: statusLoading } = useSentComStatus();
  const { messages, loading: streamLoading, refresh: refreshStream } = useSentComStream();
  const { positions, totalPnl, loading: positionsLoading } = useSentComPositions();
  const { setups, loading: setupsLoading } = useSentComSetups();
  const { context, loading: contextLoading } = useSentComContext();
  const { alerts, loading: alertsLoading } = useSentComAlerts();
  const { botStatus, actionLoading, toggleBot, changeMode, updateRiskParams } = useTradingBotControl();
  const { ibConnected } = useIBConnectionStatus();
  const { session: marketSession } = useMarketSession();
  const { chatHistory, loading: historyLoading } = useChatHistory();
  const { 
    status: aiModulesStatus, 
    actionLoading: aiActionLoading, 
    toggleModule: toggleAIModule, 
    setGlobalShadowMode 
  } = useAIModules();
  
  const [selectedPosition, setSelectedPosition] = useState(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [localMessages, setLocalMessages] = useState([]);
  const [quickActionLoading, setQuickActionLoading] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState('mode'); // 'mode', 'risk', or 'ai'
  const [showAIInsights, setShowAIInsights] = useState(false);
  const [showRiskPanel, setShowRiskPanel] = useState(false);
  const [showTradeForm, setShowTradeForm] = useState(false);
  const conversationRef = useRef(null);
  
  // Initialize local messages with chat history when it loads
  useEffect(() => {
    if (chatHistory.length > 0 && localMessages.length === 0) {
      setLocalMessages(chatHistory);
    }
  }, [chatHistory, localMessages.length]);

  // Auto-scroll handled by ConversationPanel component now
  useEffect(() => {
    if (conversationRef.current) {
      conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
    }
  }, [localMessages]);

  const handleChat = async (message) => {
    if (!message.trim() || chatLoading) return;
    
    setChatLoading(true);
    const userTimestamp = new Date().toISOString();
    
    // Add user message to local messages immediately
    const userMsg = {
      id: `user_${Date.now()}`,
      type: 'chat',
      content: message,
      timestamp: userTimestamp,
      action_type: 'user_message',
      metadata: { role: 'user' }
    };
    setLocalMessages(prev => [...prev, userMsg]);
    
    try {
      const { data: chatData } = await api.post('/api/sentcom/chat', { message });
      
      // Add assistant response AFTER user message (slightly later timestamp)
      const assistantMsg = {
        id: `assistant_${Date.now()}`,
        type: 'chat',
        content: chatData.response || "We're processing your request...",
        timestamp: new Date().toISOString(),
        action_type: 'chat_response',
        metadata: { role: 'assistant', source: chatData.source }
      };
      setLocalMessages(prev => [...prev, assistantMsg]);
      
      return chatData;
    } catch (err) {
      console.error('Chat error:', err);
      // Add error message
      const errorMsg = {
        id: `error_${Date.now()}`,
        type: 'system',
        content: "We're having trouble processing that right now. We'll keep trying.",
        timestamp: new Date().toISOString(),
        action_type: 'error',
        metadata: { role: 'assistant' }
      };
      setLocalMessages(prev => [...prev, errorMsg]);
    } finally {
      setChatLoading(false);
    }
  };

  // Handle quick action clicks
  const handleQuickAction = async (action) => {
    setQuickActionLoading(action.id);
    
    // Add user message showing which action was triggered
    const userMsg = {
      id: `user_${Date.now()}`,
      type: 'chat',
      content: action.prompt ? action.prompt : `Requesting ${action.label}...`,
      timestamp: new Date().toISOString(),
      action_type: 'user_message',
      metadata: { role: 'user', quickAction: action.id }
    };
    setLocalMessages(prev => [...prev, userMsg]);
    
    try {
      let response;
      
      if (action.endpoint) {
        // Call specific coaching endpoint
        const data = await safeGet(action.endpoint);
        response = data.coaching || data.response || "We'll have that ready for you soon.";
      } else if (action.prompt) {
        // Send as chat message
        const { data } = await api.post('/api/sentcom/chat', { message: action.prompt });
        response = data.response || "We're working on that analysis.";
      }
      
      // Add assistant response
      const assistantMsg = {
        id: `assistant_${Date.now()}`,
        type: 'chat',
        content: response,
        timestamp: new Date().toISOString(),
        action_type: 'chat_response',
        metadata: { role: 'assistant', source: action.id }
      };
      setLocalMessages(prev => [...prev, assistantMsg]);
      
    } catch (err) {
      console.error('Quick action error:', err);
      const errorMsg = {
        id: `error_${Date.now()}`,
        type: 'system',
        content: `We couldn't complete that action right now. We'll try again shortly.`,
        timestamp: new Date().toISOString(),
        action_type: 'error',
        metadata: { role: 'assistant' }
      };
      setLocalMessages(prev => [...prev, errorMsg]);
    } finally {
      setQuickActionLoading(null);
    }
  };

  // Handle Check My Trade form submission
  const handleCheckTrade = async (data) => {
    setQuickActionLoading('checkTrade');
    
    const userMsg = {
      id: `user_${Date.now()}`,
      type: 'chat',
      content: `Check Our Trade: ${data.action} ${data.symbol} @ $${data.entry_price} (stop: $${data.stop_loss})`,
      timestamp: new Date().toISOString(),
      action_type: 'user_message',
      metadata: { role: 'user', tradeCheck: data }
    };
    setLocalMessages(prev => [...prev, userMsg]);
    
    try {
      // Call both endpoints in parallel
      const [rulesRes, sizingRes] = await Promise.all([
        safePost('/api/assistant/coach/check-rules', data),
        safePost('/api/assistant/coach/position-size', data)
      ]);
      
      // Combine the responses
      let combinedResponse = '';
      
      if (rulesRes?.analysis) {
        combinedResponse += '## Rule Check\n\n' + rulesRes.analysis;
      }
      
      if (sizingRes?.analysis) {
        combinedResponse += '\n\n---\n\n## Position Sizing\n\n' + sizingRes.analysis;
      }
      
      if (!combinedResponse) {
        combinedResponse = "We're analyzing this trade setup. Make sure our systems are fully connected for complete analysis.";
      }
      
      const assistantMsg = {
        id: `assistant_${Date.now()}`,
        type: 'chat',
        content: combinedResponse,
        timestamp: new Date().toISOString(),
        action_type: 'chat_response',
        metadata: { role: 'assistant', source: 'trade_check' }
      };
      setLocalMessages(prev => [...prev, assistantMsg]);
      
    } catch (err) {
      console.error('Trade check error:', err);
      const errorMsg = {
        id: `error_${Date.now()}`,
        type: 'system',
        content: "We couldn't analyze that trade right now. Let's try again.",
        timestamp: new Date().toISOString(),
        action_type: 'error',
        metadata: { role: 'assistant' }
      };
      setLocalMessages(prev => [...prev, errorMsg]);
    } finally {
      setQuickActionLoading(null);
      setShowTradeForm(false);
    }
  };

  // Separate chat messages from stream - these should NOT cause conversation re-renders
  // S.O.C. gets stream data, Conversation gets ONLY local user chat
  const chatOnlyMessages = React.useMemo(() => {
    // Only use localMessages for the conversation panel
    // These only change when the user sends a message or receives a response
    return localMessages.filter(m => 
      m.type === 'chat' || 
      m.action_type === 'chat_response' || 
      m.action_type === 'user_message'
    ).sort((a, b) => 
      new Date(a.timestamp) - new Date(b.timestamp)
    ).slice(-30);
  }, [localMessages]);
  
  // allMessages is only used for StopFixPanel - not for Conversation
  const allMessages = React.useMemo(() => {
    const combined = [...localMessages, ...messages];
    const seen = new Set();
    const unique = combined.filter(msg => {
      if (seen.has(msg.id)) return false;
      seen.add(msg.id);
      return true;
    });
    return unique.sort((a, b) => 
      new Date(a.timestamp) - new Date(b.timestamp)
    ).slice(-30);
  }, [localMessages, messages]);

  // =========================================================================
  // EMBEDDED MODE - For Command Center (full-featured but fits in dashboard)
  // With glassy mockup styling and unified Trading Bot controls
  // =========================================================================
  if (embedded) {
    const isRunning = botStatus?.running;
    const mode = botStatus?.mode || 'confirmation';
    const regime = context?.regime || status?.regime || 'UNKNOWN';
    const connected = status?.connected || false;
    
    return (
      <div className="relative overflow-auto rounded-2xl bg-gradient-to-br from-white/[0.08] to-white/[0.02] border border-white/10 backdrop-blur-xl" style={{ maxHeight: 'calc(100vh - 120px)' }} data-testid="sentcom-embedded">
        {/* Bot Health Banner — renders only when execution-health is CRITICAL */}
        <BotHealthBanner />

        {/* Ambient Background Effects */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-32 -right-32 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl" />
          <div className="absolute -bottom-32 -left-32 w-64 h-64 bg-violet-500/10 rounded-full blur-3xl" />
        </div>
        
        {/* Unified Header - Bot Controls + Status + Order Pipeline */}
        <div className="relative flex items-center justify-between px-3 py-2 border-b border-white/10 bg-black/40 backdrop-blur-xl">
          <div className="flex items-center gap-3">
            {/* Logo & Status */}
            <div className="flex items-center gap-2">
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 to-violet-500 blur-lg opacity-40" />
                <div className="relative w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center border border-white/20 shadow-lg shadow-cyan-500/20">
                  <Brain className="w-4 h-4 text-cyan-400" />
                </div>
              </div>
              <div>
                <h2 className="text-base font-bold text-white tracking-tight">SENTCOM</h2>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <div className="flex items-center gap-1">
                    <StatusDot service="quotesStream" size="sm" />
                  </div>
                  <span className="text-zinc-600">•</span>
                  {/* Market Session Badge */}
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold ${
                    marketSession.is_open 
                      ? marketSession.name === 'MARKET OPEN' 
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : 'bg-amber-500/20 text-amber-400'
                      : 'bg-zinc-500/20 text-zinc-400'
                  }`}>
                    {marketSession.name || 'LOADING'}
                  </span>
                  {regime !== 'UNKNOWN' && (
                    <>
                      <span className="text-zinc-600">•</span>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold ${
                        regime === 'RISK_ON' ? 'bg-emerald-500/20 text-emerald-400' :
                        regime === 'RISK_OFF' ? 'bg-rose-500/20 text-rose-400' :
                        'bg-zinc-500/20 text-zinc-400'
                      }`}>
                        {regime}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>
            
            {/* Bot Status Badge */}
            <div className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border ${
              isRunning 
                ? 'bg-emerald-500/10 border-emerald-500/30' 
                : 'bg-zinc-500/10 border-zinc-500/30'
            }`}>
              <Bot className={`w-3.5 h-3.5 ${isRunning ? 'text-emerald-400' : 'text-zinc-500'}`} />
              <span className={`text-[10px] font-bold ${isRunning ? 'text-emerald-400' : 'text-zinc-500'}`}>
                {isRunning ? 'ACTIVE' : 'STOPPED'}
              </span>
            </div>
            
            {/* Mode Indicator */}
            <div className={`flex items-center gap-1 px-2 py-1 rounded-lg border ${
              mode === 'autonomous' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' :
              mode === 'confirmation' ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400' :
              'bg-amber-500/10 border-amber-500/30 text-amber-400'
            }`}>
              {mode === 'autonomous' ? <Zap className="w-3 h-3" /> :
               mode === 'confirmation' ? <Eye className="w-3 h-3" /> :
               <Pause className="w-3 h-3" />}
              <span className="text-[9px] font-bold uppercase">{mode}</span>
            </div>
            
            {/* Dynamic Risk Badge */}
            <DynamicRiskBadge onClick={() => setShowRiskPanel(!showRiskPanel)} />
            
            {/* Server Health Badge */}
            <ServerHealthBadge />
          </div>
          
          <div className="flex items-center gap-2">
            {/* Order Pipeline - Compact */}
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-xl bg-black/40 border border-white/5">
              <div className="flex items-center gap-1.5">
                <div className="w-5 h-5 rounded bg-amber-500/20 flex items-center justify-center">
                  <Clock className="w-2.5 h-2.5 text-amber-400" />
                </div>
                <p className="text-sm font-bold text-amber-400">{status?.order_pipeline?.pending || 0}</p>
              </div>
              
              <ArrowRight className="w-2.5 h-2.5 text-zinc-600" />
              
              <div className="flex items-center gap-1.5">
                <div className={`w-5 h-5 rounded bg-cyan-500/20 flex items-center justify-center ${(status?.order_pipeline?.executing || 0) > 0 ? 'animate-pulse' : ''}`}>
                  <Zap className="w-2.5 h-2.5 text-cyan-400" />
                </div>
                <p className="text-sm font-bold text-cyan-400">{status?.order_pipeline?.executing || 0}</p>
              </div>
              
              <ArrowRight className="w-2.5 h-2.5 text-zinc-600" />
              
              <div className="flex items-center gap-1.5">
                <div className="w-5 h-5 rounded bg-emerald-500/20 flex items-center justify-center">
                  <CheckCircle className="w-2.5 h-2.5 text-emerald-400" />
                </div>
                <p className="text-sm font-bold text-emerald-400">{status?.order_pipeline?.filled || 0}</p>
              </div>
            </div>
            
            {/* Bot Controls */}
            <button
              onClick={() => setShowSettings(!showSettings)}
              className={`p-2 rounded-xl transition-all border ${
                showSettings 
                  ? 'bg-cyan-500/20 border-cyan-500/30 text-cyan-400' 
                  : 'bg-white/5 border-white/5 text-zinc-400 hover:text-white hover:bg-white/10'
              }`}
              data-testid="sentcom-settings-btn"
            >
              <Settings className="w-4 h-4" />
            </button>
            
            <button
              onClick={toggleBot}
              disabled={actionLoading === 'toggle'}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-xl font-medium text-xs transition-all shadow-lg ${
                isRunning 
                  ? 'bg-gradient-to-r from-rose-500/20 to-rose-600/10 border border-rose-500/30 text-rose-400 hover:from-rose-500/30 shadow-rose-500/10' 
                  : 'bg-gradient-to-r from-emerald-500/20 to-emerald-600/10 border border-emerald-500/30 text-emerald-400 hover:from-emerald-500/30 shadow-emerald-500/10'
              }`}
              data-testid="sentcom-toggle-bot"
            >
              {actionLoading === 'toggle' ? (
                <Loader className="w-3.5 h-3.5 animate-spin" />
              ) : isRunning ? (
                <Pause className="w-3.5 h-3.5" />
              ) : (
                <Play className="w-3.5 h-3.5" />
              )}
              {isRunning ? 'Stop' : 'Start'}
            </button>
          </div>
        </div>
        
        {/* Settings Panel (Mode Selector + Risk Controls) */}
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden border-b border-white/5"
            >
              <div className="relative p-4 bg-black/40">
                {/* Tab Navigation */}
                <div className="flex gap-2 mb-4">
                  <button
                    onClick={() => setSettingsTab('mode')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      settingsTab === 'mode' 
                        ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                        : 'bg-zinc-800/50 text-zinc-400 border border-white/5 hover:border-white/10'
                    }`}
                  >
                    Trading Mode
                  </button>
                  <button
                    onClick={() => setSettingsTab('risk')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      settingsTab === 'risk' 
                        ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                        : 'bg-zinc-800/50 text-zinc-400 border border-white/5 hover:border-white/10'
                    }`}
                  >
                    Risk Controls
                  </button>
                  <button
                    onClick={() => setSettingsTab('ai')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      settingsTab === 'ai' 
                        ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30' 
                        : 'bg-zinc-800/50 text-zinc-400 border border-white/5 hover:border-white/10'
                    }`}
                    data-testid="settings-tab-ai"
                  >
                    AI Modules
                    {aiModulesStatus?.active_modules > 0 && (
                      <span className="ml-1.5 px-1.5 py-0.5 text-[9px] bg-violet-500/30 text-violet-300 rounded-full">
                        {aiModulesStatus.active_modules}
                      </span>
                    )}
                  </button>
                  <button
                    onClick={() => { setShowAIInsights(true); }}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all bg-gradient-to-r from-cyan-500/20 to-violet-500/20 text-cyan-400 border border-cyan-500/30 hover:border-cyan-500/50 flex items-center gap-1.5"
                    data-testid="open-ai-insights"
                  >
                    <BarChart3 className="w-3 h-3" />
                    AI Insights
                  </button>
                </div>

                {/* Tab Content */}
                {settingsTab === 'mode' ? (
                  <>
                    <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Trading Mode</h4>
                    <div className="grid grid-cols-3 gap-3">
                      {/* Autonomous Mode */}
                      <button
                        onClick={() => changeMode('autonomous')}
                        className={`p-3 rounded-xl border text-center transition-all ${
                          mode === 'autonomous' 
                            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' 
                            : 'bg-black/30 border-white/5 text-zinc-400 hover:border-white/10 hover:bg-black/40'
                        }`}
                        data-testid="sentcom-mode-autonomous"
                      >
                        <Zap className={`w-5 h-5 mx-auto mb-2 ${mode === 'autonomous' ? 'text-emerald-400' : 'text-zinc-500'}`} />
                        <div className="text-sm font-medium">Autonomous</div>
                        <div className="text-[10px] text-zinc-500 mt-0.5">Auto-execute trades</div>
                      </button>
                      
                      {/* Confirmation Mode */}
                      <button
                        onClick={() => changeMode('confirmation')}
                        className={`p-3 rounded-xl border text-center transition-all ${
                          mode === 'confirmation' 
                            ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400' 
                            : 'bg-black/30 border-white/5 text-zinc-400 hover:border-white/10 hover:bg-black/40'
                        }`}
                        data-testid="sentcom-mode-confirmation"
                      >
                        <Eye className={`w-5 h-5 mx-auto mb-2 ${mode === 'confirmation' ? 'text-cyan-400' : 'text-zinc-500'}`} />
                        <div className="text-sm font-medium">Confirmation</div>
                        <div className="text-[10px] text-zinc-500 mt-0.5">Require approval</div>
                      </button>
                      
                      {/* Paused Mode */}
                      <button
                        onClick={() => changeMode('paused')}
                        className={`p-3 rounded-xl border text-center transition-all ${
                          mode === 'paused' 
                            ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' 
                            : 'bg-black/30 border-white/5 text-zinc-400 hover:border-white/10 hover:bg-black/40'
                        }`}
                        data-testid="sentcom-mode-paused"
                      >
                        <Pause className={`w-5 h-5 mx-auto mb-2 ${mode === 'paused' ? 'text-amber-400' : 'text-zinc-500'}`} />
                        <div className="text-sm font-medium">Paused</div>
                        <div className="text-[10px] text-zinc-500 mt-0.5">No scanning</div>
                      </button>
                    </div>
                  </>
                ) : settingsTab === 'risk' ? (
                  <RiskControlsPanel 
                    botStatus={botStatus} 
                    onUpdateRisk={updateRiskParams}
                    loading={actionLoading === 'risk'}
                  />
                ) : (
                  <AIModulesPanel
                    aiStatus={aiModulesStatus}
                    onToggleModule={toggleAIModule}
                    onSetShadowMode={setGlobalShadowMode}
                    actionLoading={aiActionLoading}
                  />
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Dynamic Risk Panel - Slide-out */}
        <AnimatePresence>
          {showRiskPanel && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="border-b border-white/10 bg-black/40 backdrop-blur-xl overflow-hidden"
            >
              <div className="p-4 max-w-2xl mx-auto">
                <DynamicRiskPanel expanded={true} onToggleExpand={() => setShowRiskPanel(false)} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Main Content */}
        <div className="relative p-3 space-y-3">
          {/* Full Width S.O.C. with floating Chat Bubble Overlay */}
          <div className="relative rounded-2xl border border-white/10 overflow-hidden" style={{ height: '700px' }} data-testid="neural-split-container">
            {/* SOC takes 100% */}
            <div className="h-full overflow-hidden">
              <StreamOfConsciousness />
            </div>
            
            {/* Floating Chat Bubble Overlay */}
            <ChatBubbleOverlay
              messages={chatOnlyMessages}
              onSendMessage={handleChat}
              onQuickAction={handleQuickAction}
              onCheckTrade={handleCheckTrade}
              loading={chatLoading}
              quickActionLoading={quickActionLoading}
            />
          </div>
          
          {/* Stop Fix Panel - Shows when risky stops detected */}
          <StopFixPanel 
            thoughts={allMessages.filter(m => m.type === 'thought' || m.action_type === 'stop_warning')}
            onRefresh={refreshStream}
          />
        </div>

        {/* Position Detail Modal - Enhanced */}
        <AnimatePresence>
        {/* Position Detail Modal - Using EnhancedTickerModal for full chart view */}
        {selectedPosition && (
          <EnhancedTickerModal
            ticker={{ 
              symbol: selectedPosition.symbol,
              name: selectedPosition.symbol
            }}
            onClose={() => setSelectedPosition(null)}
            botPosition={selectedPosition}
            initialTab="overview"
          />
        )}
        </AnimatePresence>

        {/* AI Insights Dashboard Modal - Rendered inside embedded mode */}
        {showAIInsights && (
          <AIInsightsDashboard 
            key="ai-insights-dashboard-embedded"
            onClose={() => setShowAIInsights(false)} 
          />
        )}
      </div>
    );
  }

  // =========================================================================
  // COMPACT MODE - Small box (kept for reference but not used currently)
  // =========================================================================
  if (compact) {
    return (
      <div className="bg-zinc-900/50 backdrop-blur-xl rounded-2xl border border-white/10 overflow-hidden" data-testid="sentcom-compact">
        {/* Compact Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/30 to-violet-500/30 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Brain className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight">SENTCOM</h2>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  {status?.connected ? (
                    <PulsingDot color="emerald" />
                  ) : (
                    <Circle className="w-2 h-2 text-zinc-500" />
                  )}
                  <span className={`text-[10px] font-medium ${status?.connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
                    {status?.connected ? 'CONNECTED' : 'OFFLINE'}
                  </span>
                </div>
                {context?.regime && context.regime !== 'UNKNOWN' && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                    context.regime === 'RISK_ON' ? 'bg-emerald-500/20 text-emerald-400' :
                    context.regime === 'RISK_OFF' ? 'bg-rose-500/20 text-rose-400' :
                    'bg-zinc-500/20 text-zinc-400'
                  }`}>
                    {context.regime}
                  </span>
                )}
              </div>
            </div>
          </div>
          
          {/* Compact Order Pipeline */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-black/30">
            <div className="flex items-center gap-1">
              <Clock className="w-3 h-3 text-amber-400" />
              <span className="text-sm font-bold text-amber-400">{status?.order_pipeline?.pending || 0}</span>
            </div>
            <ArrowRight className="w-3 h-3 text-zinc-600" />
            <div className="flex items-center gap-1">
              <Zap className="w-3 h-3 text-cyan-400" />
              <span className="text-sm font-bold text-cyan-400">{status?.order_pipeline?.executing || 0}</span>
            </div>
            <ArrowRight className="w-3 h-3 text-zinc-600" />
            <div className="flex items-center gap-1">
              <CheckCircle className="w-3 h-3 text-emerald-400" />
              <span className="text-sm font-bold text-emerald-400">{status?.order_pipeline?.filled || 0}</span>
            </div>
          </div>
        </div>

        {/* Thought Label */}
        <div className="px-4 pt-3 pb-1">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">What we're thinking right now</p>
        </div>
        
        {/* Live Stream - compact height */}
        <div className="h-[280px] overflow-hidden">
          <StreamPanel messages={messages} loading={streamLoading} />
        </div>
        
        {/* Chat Input */}
        <ChatInput onSend={handleChat} disabled={!status?.connected} />
      </div>
    );
  }

  // Full page version
  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <div className="max-w-7xl mx-auto p-6">
        {/* Header */}
        <div className="mb-6">
          <GlassCard gradient glow className="p-0">
            <StatusHeader status={status} context={context} />
          </GlassCard>
        </div>

        {/* Main Grid */}
        <div className="grid grid-cols-12 gap-6">
          {/* Left Column - Positions only */}
          <div className="col-span-3 space-y-6">
            <PositionsPanel 
              positions={positions} 
              totalPnl={totalPnl}
              loading={positionsLoading}
              onSelectPosition={setSelectedPosition}
            />
          </div>

          {/* Center - Live Stream */}
          <div className="col-span-5">
            <div className="h-[600px] flex flex-col">
              <StreamPanel messages={messages} loading={streamLoading} />
              <ChatInput onSend={handleChat} disabled={!status?.connected} />
            </div>
          </div>

          {/* Right Column - Market Intel (Regime + Setups + Alerts) */}
          <div className="col-span-4">
            <MarketIntelPanel 
              context={context}
              setups={setups}
              alerts={alerts}
              contextLoading={contextLoading}
              setupsLoading={setupsLoading}
              alertsLoading={alertsLoading}
            />
          </div>
        </div>
      </div>

      {/* Position Detail Modal */}
      <AnimatePresence>
        {selectedPosition && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-8"
            onClick={() => setSelectedPosition(null)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="w-full max-w-2xl"
              onClick={e => e.stopPropagation()}
            >
              <GlassCard glow className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="text-2xl font-bold text-white">Our {selectedPosition.symbol} Position</h2>
                    <p className="text-sm text-zinc-400">Entry: ${selectedPosition.entry_price?.toFixed(2)}</p>
                  </div>
                  <button
                    onClick={() => setSelectedPosition(null)}
                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                <div className="grid grid-cols-3 gap-4 mb-6">
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">P&L</p>
                    <p className={`text-xl font-bold ${selectedPosition.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {selectedPosition.pnl >= 0 ? '+' : ''}{selectedPosition.pnl?.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">Stop</p>
                    <p className="text-xl font-bold text-rose-400">
                      ${selectedPosition.stop_price?.toFixed(2) || '--'}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">Target</p>
                    <p className="text-xl font-bold text-emerald-400">
                      ${selectedPosition.target_prices?.[0]?.toFixed(2) || '--'}
                    </p>
                  </div>
                </div>

                <p className="text-sm text-zinc-400">
                  Shares: {selectedPosition.shares} • 
                  Entry: ${selectedPosition.entry_price?.toFixed(2)} • 
                  Current: ${selectedPosition.current_price?.toFixed(2)}
                </p>
              </GlassCard>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* AI Insights Dashboard Modal */}
      {showAIInsights && (
        <AIInsightsDashboard 
          key="ai-insights-dashboard"
          onClose={() => setShowAIInsights(false)} 
        />
      )}
    </div>
  );
};

export default SentCom;
