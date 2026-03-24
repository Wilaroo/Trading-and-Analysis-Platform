/**
 * BriefMeModal - AI-generated personalized market briefing
 * 
 * Features:
 * - Quick summary view (default, 2-3 sentences)
 * - Expandable detailed view with sections
 * - Real-time data from multiple services
 * - Personalized based on user's trading history
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import api, { safeGet, safePost } from '../utils/api';
import { 
  X, Sparkles, TrendingUp, TrendingDown, Bot, Brain, 
  Target, AlertTriangle, ChevronDown, ChevronUp, 
  RefreshCw, Clock, Zap, BarChart3
} from 'lucide-react';

const BriefMeModal = ({ isOpen, onClose }) => {
  const [detailLevel, setDetailLevel] = useState('quick'); // 'quick' or 'detailed'
  const [briefData, setBriefData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  
  // Fetch briefing with extended timeout for enhanced data fetching
  const fetchBrief = useCallback(async (level = detailLevel) => {
    setIsLoading(true);
    setError(null);
    
    // Create abort controller with 60 second timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60000);
    
    try {
      const { data } = await api.post('/api/agents/brief-me', 
        { detail_level: level },
        { signal: controller.signal, timeout: 60000 }
      );
      
      clearTimeout(timeoutId);
      
      if (data.success) {
        setBriefData(data);
      } else {
        setError(data.error || 'Unknown error');
      }
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        setError('Request timed out. The briefing is taking longer than expected.');
      } else {
        console.error('Brief Me error:', err);
        setError(err.message);
      }
    } finally {
      setIsLoading(false);
    }
  }, [detailLevel]);
  
  // Fetch on open
  useEffect(() => {
    if (isOpen) {
      fetchBrief('quick');
    }
  }, [isOpen]);
  
  // Toggle detail level
  const toggleDetail = () => {
    const newLevel = detailLevel === 'quick' ? 'detailed' : 'quick';
    setDetailLevel(newLevel);
    fetchBrief(newLevel);
  };
  
  if (!isOpen) return null;
  
  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          onClick={(e) => e.stopPropagation()}
          className={`bg-zinc-900 border border-white/10 rounded-2xl shadow-2xl overflow-hidden
            ${detailLevel === 'detailed' ? 'w-full max-w-3xl max-h-[85vh]' : 'w-full max-w-xl'}
          `}
        >
          {/* Header */}
          <div className="p-4 border-b border-white/10 bg-gradient-to-r from-pink-500/10 to-purple-500/10">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-pink-500 to-purple-500 flex items-center justify-center">
                  <Sparkles className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h2 className="text-lg font-bold">Market Briefing</h2>
                  <p className="text-xs text-zinc-400">
                    {briefData?.generated_at 
                      ? `Generated ${new Date(briefData.generated_at).toLocaleTimeString()}`
                      : 'Generating...'}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => fetchBrief(detailLevel)}
                  disabled={isLoading}
                  className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                >
                  <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                </button>
                <button
                  onClick={onClose}
                  className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
          </div>
          
          {/* Content */}
          <div className={`p-6 overflow-y-auto ${detailLevel === 'detailed' ? 'max-h-[60vh]' : ''}`}>
            {isLoading ? (
              <LoadingState />
            ) : error ? (
              <ErrorState error={error} onRetry={() => fetchBrief(detailLevel)} />
            ) : briefData ? (
              detailLevel === 'quick' ? (
                <QuickSummary data={briefData} />
              ) : (
                <DetailedSummary data={briefData} />
              )
            ) : null}
          </div>
          
          {/* Footer */}
          <div className="p-4 border-t border-white/10 flex justify-between items-center">
            <button
              onClick={toggleDetail}
              className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors"
            >
              {detailLevel === 'quick' ? (
                <>
                  <ChevronDown className="w-4 h-4" />
                  Show Full Report
                </>
              ) : (
                <>
                  <ChevronUp className="w-4 h-4" />
                  Show Quick Summary
                </>
              )}
            </button>
            
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 transition-colors text-sm font-medium"
            >
              Got It
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

// Quick Summary Component
const QuickSummary = ({ data }) => {
  const summary = typeof data.summary === 'string' 
    ? data.summary 
    : data.summary?.full_summary || '';
  
  const marketData = data.data?.market_summary || {};
  const botData = data.data?.your_bot || {};
  const opportunities = data.data?.opportunities || [];
  const newsData = data.data?.news || {};
  const sectorsData = data.data?.sectors || {};
  const catalysts = data.data?.catalysts || [];
  
  return (
    <div className="space-y-4">
      {/* Main Summary Text */}
      <div className="text-lg leading-relaxed">
        {summary}
      </div>
      
      {/* Quick Stats Row */}
      <div className="flex flex-wrap gap-3 pt-4">
        {/* Regime Badge */}
        <div className={`px-3 py-2 rounded-lg border ${
          marketData.regime === 'RISK_ON' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' :
          marketData.regime === 'RISK_OFF' ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' :
          marketData.regime === 'CONFIRMED_DOWN' ? 'bg-red-500/10 border-red-500/30 text-red-400' :
          'bg-zinc-500/10 border-zinc-500/30 text-zinc-400'
        }`}>
          <div className="text-xs opacity-70">Regime</div>
          <div className="font-bold">{marketData.regime || 'HOLD'}</div>
        </div>
        
        {/* News Sentiment Badge */}
        {newsData.sentiment && (
          <div className={`px-3 py-2 rounded-lg border ${
            newsData.sentiment === 'bullish' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' :
            newsData.sentiment === 'bearish' ? 'bg-red-500/10 border-red-500/30 text-red-400' :
            'bg-zinc-500/10 border-zinc-500/30 text-zinc-400'
          }`}>
            <div className="text-xs opacity-70">News Tone</div>
            <div className="font-bold capitalize">{newsData.sentiment}</div>
          </div>
        )}
        
        {/* Leading Sector Badge */}
        {sectorsData.leaders?.[0] && (
          <div className={`px-3 py-2 rounded-lg border ${
            sectorsData.leaders[0].change_pct > 0 
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-red-500/10 border-red-500/30 text-red-400'
          }`}>
            <div className="text-xs opacity-70">Top Sector</div>
            <div className="font-bold">
              {sectorsData.leaders[0].name} {sectorsData.leaders[0].change_pct > 0 ? '+' : ''}{sectorsData.leaders[0].change_pct?.toFixed(1)}%
            </div>
          </div>
        )}
        
        {/* Bot State */}
        <div className={`px-3 py-2 rounded-lg border ${
          botData.running 
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
            : 'bg-zinc-500/10 border-zinc-500/30 text-zinc-400'
        }`}>
          <div className="text-xs opacity-70">Bot</div>
          <div className="font-bold">{botData.running ? 'Hunting' : 'Paused'}</div>
        </div>
        
        {/* Today's P&L */}
        <div className={`px-3 py-2 rounded-lg border ${
          (botData.today_pnl || 0) >= 0
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
            : 'bg-red-500/10 border-red-500/30 text-red-400'
        }`}>
          <div className="text-xs opacity-70">Today's P&L</div>
          <div className="font-bold font-mono">
            {(botData.today_pnl || 0) >= 0 ? '+' : ''}${(botData.today_pnl || 0).toFixed(0)}
          </div>
        </div>
        
        {/* Top Opportunity */}
        {opportunities[0] && (
          <div className="px-3 py-2 rounded-lg border bg-cyan-500/10 border-cyan-500/30 text-cyan-400">
            <div className="text-xs opacity-70">Top Setup</div>
            <div className="font-bold">{opportunities[0].symbol} - {opportunities[0].setup}</div>
          </div>
        )}
        
        {/* Catalyst Alert */}
        {catalysts[0]?.ticker && (
          <div className="px-3 py-2 rounded-lg border bg-orange-500/10 border-orange-500/30 text-orange-400">
            <div className="text-xs opacity-70">Catalyst</div>
            <div className="font-bold">{catalysts[0].ticker} ({catalysts[0].type})</div>
          </div>
        )}
      </div>
      
      {/* Key Themes Row */}
      {newsData.themes?.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-2">
          <span className="text-xs text-zinc-500">Themes:</span>
          {newsData.themes.slice(0, 3).map((theme, idx) => (
            <span key={idx} className="text-xs px-2 py-1 rounded-full bg-zinc-800 text-zinc-400">
              {theme}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

// Detailed Summary Component
const DetailedSummary = ({ data }) => {
  const sections = typeof data.summary === 'object' && !data.summary.full_summary
    ? data.summary
    : null;
  const fullSummary = data.summary?.full_summary || '';
  const briefData = data.data || {};
  
  // If LLM generated a full summary, show it
  if (fullSummary) {
    return (
      <div className="prose prose-invert max-w-none">
        <div 
          className="whitespace-pre-wrap text-sm leading-relaxed"
          dangerouslySetInnerHTML={{ 
            __html: fullSummary
              .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
              .replace(/\n/g, '<br />') 
          }}
        />
      </div>
    );
  }
  
  // Otherwise show structured sections
  return (
    <div className="space-y-6">
      {/* Market Overview */}
      {sections?.market_overview && (
        <Section 
          icon={<BarChart3 className="w-4 h-4" />}
          title="Market Overview"
          color="purple"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.market_overview
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            }}
          />
        </Section>
      )}
      
      {/* NEW: News & Catalysts */}
      {sections?.news && (
        <Section 
          icon={<AlertTriangle className="w-4 h-4" />}
          title="News & Catalysts"
          color="cyan"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.news
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/📰/g, '<span class="text-cyan-400">📰</span>')
                .replace(/🟢/g, '<span class="text-emerald-400">🟢</span>')
                .replace(/🔴/g, '<span class="text-red-400">🔴</span>')
                .replace(/🟡/g, '<span class="text-amber-400">🟡</span>')
            }}
          />
        </Section>
      )}
      
      {/* NEW: Catalysts */}
      {sections?.catalysts && (
        <Section 
          icon={<Zap className="w-4 h-4" />}
          title="Today's Catalysts"
          color="amber"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.catalysts
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/🔥/g, '<span class="text-orange-400">🔥</span>')
                .replace(/⚡/g, '<span class="text-amber-400">⚡</span>')
                .replace(/📌/g, '<span class="text-zinc-400">📌</span>')
                .replace(/🎯/g, '<span class="text-cyan-400">🎯</span>')
            }}
          />
        </Section>
      )}
      
      {/* NEW: Sector Rotation */}
      {sections?.sectors && (
        <Section 
          icon={<TrendingUp className="w-4 h-4" />}
          title="Sector Rotation"
          color="emerald"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.sectors
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/🚀/g, '<span class="text-emerald-400">🚀</span>')
                .replace(/🛡️/g, '<span class="text-blue-400">🛡️</span>')
                .replace(/🔄/g, '<span class="text-purple-400">🔄</span>')
                .replace(/📉/g, '<span class="text-red-400">📉</span>')
                .replace(/📈/g, '<span class="text-emerald-400">📈</span>')
                .replace(/🔀/g, '<span class="text-zinc-400">🔀</span>')
                .replace(/🟢/g, '<span class="text-emerald-400">🟢</span>')
                .replace(/🔴/g, '<span class="text-red-400">🔴</span>')
            }}
          />
        </Section>
      )}
      
      {/* NEW: Earnings Watch */}
      {sections?.earnings && (
        <Section 
          icon={<Clock className="w-4 h-4" />}
          title="Earnings Watch"
          color="amber"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.earnings
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/⚠️/g, '<span class="text-amber-400">⚠️</span>')
                .replace(/📅/g, '<span class="text-cyan-400">📅</span>')
                .replace(/💡/g, '<span class="text-amber-400">💡</span>')
            }}
          />
        </Section>
      )}
      
      {/* Gappers */}
      {sections?.gappers && (
        <Section 
          icon={<TrendingUp className="w-4 h-4" />}
          title="Pre-Market Gappers"
          color="emerald"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.gappers
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/🟢/g, '<span class="text-emerald-400">🟢</span>')
                .replace(/🔴/g, '<span class="text-red-400">🔴</span>')
            }}
          />
        </Section>
      )}
      
      {/* Bot Status */}
      {sections?.bot_status && (
        <Section 
          icon={<Bot className="w-4 h-4" />}
          title="Your Bot Status"
          color="cyan"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.bot_status
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            }}
          />
        </Section>
      )}
      
      {/* Personalized Insights */}
      {sections?.personalized_insights && (
        <Section 
          icon={<Brain className="w-4 h-4" />}
          title="Personalized Insights"
          color="pink"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.personalized_insights
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            }}
          />
        </Section>
      )}
      
      {/* Opportunities / Stocks to Watch */}
      {sections?.opportunities && (
        <Section 
          icon={<Target className="w-4 h-4" />}
          title="Stocks to Watch"
          color="emerald"
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.opportunities
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/📊/g, '<span class="text-cyan-400">📊</span>')
            }}
          />
        </Section>
      )}
      
      {/* Recommendation */}
      {sections?.recommendation && (
        <Section 
          icon={<Zap className="w-4 h-4" />}
          title="Recommendation"
          color="amber"
          highlight
        >
          <div 
            className="text-sm text-zinc-300 whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ 
              __html: sections.recommendation
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/💡/g, '<span class="text-amber-400">💡</span>')
            }}
          />
        </Section>
      )}
    </div>
  );
};

// Section Component
const Section = ({ icon, title, color, highlight, children }) => {
  const colorClasses = {
    purple: 'border-purple-500/30 bg-purple-500/5',
    cyan: 'border-cyan-500/30 bg-cyan-500/5',
    pink: 'border-pink-500/30 bg-pink-500/5',
    emerald: 'border-emerald-500/30 bg-emerald-500/5',
    amber: 'border-amber-500/30 bg-amber-500/5',
  };
  
  const iconColorClasses = {
    purple: 'text-purple-400',
    cyan: 'text-cyan-400',
    pink: 'text-pink-400',
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
  };
  
  return (
    <div className={`rounded-xl border p-4 ${colorClasses[color]} ${highlight ? 'ring-1 ring-amber-500/50' : ''}`}>
      <div className="flex items-center gap-2 mb-3">
        <span className={iconColorClasses[color]}>{icon}</span>
        <h3 className="font-bold text-sm">{title}</h3>
      </div>
      {children}
    </div>
  );
};

// Loading State
const LoadingState = () => (
  <div className="flex flex-col items-center justify-center py-12 gap-4">
    <div className="relative">
      <div className="w-16 h-16 rounded-full border-2 border-purple-500/20 animate-pulse" />
      <Sparkles className="w-8 h-8 text-purple-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 animate-pulse" />
    </div>
    <div className="text-center">
      <p className="text-zinc-400">Analyzing market conditions...</p>
      <p className="text-xs text-zinc-500">Gathering data from multiple sources</p>
    </div>
  </div>
);

// Error State
const ErrorState = ({ error, onRetry }) => (
  <div className="flex flex-col items-center justify-center py-12 gap-4">
    <AlertTriangle className="w-12 h-12 text-amber-400" />
    <div className="text-center">
      <p className="text-amber-400 font-medium">Unable to generate briefing</p>
      <p className="text-xs text-zinc-500 mt-1">{error}</p>
    </div>
    <button
      onClick={onRetry}
      className="px-4 py-2 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 text-sm font-medium transition-colors"
    >
      Try Again
    </button>
  </div>
);

export default BriefMeModal;
