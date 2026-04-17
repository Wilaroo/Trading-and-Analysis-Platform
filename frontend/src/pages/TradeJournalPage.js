import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  BookOpen,
  Plus,
  X,
  TrendingUp,
  TrendingDown,
  Activity,
  Target,
  DollarSign,
  Percent,
  Calendar,
  BarChart3,
  CheckCircle,
  XCircle,
  Edit3,
  Trash2,
  RefreshCw,
  Award,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  FileText,
  Zap,
  Map,
  Briefcase,
  Filter,
  Camera,
  Image,
  Clock,
  MessageSquare
} from 'lucide-react';
import api, { safeGet } from '../utils/api';
import { useAppState } from '../contexts/AppStateContext';
import { PlaybookTab, DRCTab, GamePlanTab, WeeklyReportTab } from '../components/Journal';

// ─── Trade Snapshot Viewer ────────────────────────────────────────
const ANNOTATION_COLORS = {
  entry: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', dot: 'bg-emerald-400' },
  exit: { bg: 'bg-white/5', border: 'border-white/10', text: 'text-white', dot: 'bg-white' },
  scale_out: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', dot: 'bg-amber-400' },
  stop_adjust: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', dot: 'bg-orange-400' },
  gate_decision: { bg: 'bg-violet-500/10', border: 'border-violet-500/30', text: 'text-violet-400', dot: 'bg-violet-400' },
};

const TradeSnapshotViewer = ({ tradeId, source = 'bot' }) => {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [activeAnnotation, setActiveAnnotation] = useState(null);
  const [aiExplanation, setAiExplanation] = useState({});
  const [chatThread, setChatThread] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [hindsight, setHindsight] = useState({ data: null, narrative: '', loading: false, error: null });
  const chatInputRef = useRef(null);

  const fetchSnapshot = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await safeGet(`/api/trades/snapshots/${tradeId}?source=${source}`);
      if (data?.success && data.snapshot) {
        setSnapshot(data.snapshot);
      } else {
        setSnapshot(null);
      }
    } catch (err) {
      setError('Failed to load snapshot');
    } finally {
      setLoading(false);
    }
  }, [tradeId, source]);

  const generateSnapshot = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await api.post(`/api/trades/snapshots/${tradeId}/generate?source=${source}`);
      if (res.data?.success) {
        await fetchSnapshot();
      } else {
        setError(res.data?.error || 'Generation failed');
      }
    } catch (err) {
      setError('Failed to generate snapshot');
    } finally {
      setGenerating(false);
    }
  };

  const explainAnnotation = async (index, customQuestion) => {
    setAiExplanation(prev => ({ ...prev, [index]: { text: '', loading: true, error: null } }));
    try {
      const res = await api.post(`/api/trades/snapshots/${tradeId}/explain?source=${source}`, {
        annotation_index: index,
        question: customQuestion || null
      });
      if (res.data?.success) {
        setAiExplanation(prev => ({ ...prev, [index]: { text: res.data.explanation, loading: false, error: null } }));
      } else {
        setAiExplanation(prev => ({ ...prev, [index]: { text: '', loading: false, error: 'AI explanation unavailable' } }));
      }
    } catch (err) {
      setAiExplanation(prev => ({ ...prev, [index]: { text: '', loading: false, error: 'Failed to get explanation' } }));
    }
  };

  const openInChat = async (index) => {
    // Build context and send to SentCom chat inline
    try {
      const res = await api.post(`/api/trades/snapshots/${tradeId}/chat-context?source=${source}`, {
        annotation_index: index,
      });
      if (res.data?.success) {
        const contextMsg = res.data.chat_message;
        setChatThread([{ role: 'context', text: contextMsg }]);
        setTimeout(() => chatInputRef.current?.focus(), 150);
      }
    } catch (err) {
      console.error('Failed to build chat context:', err);
    }
  };

  const sendChatMessage = async (message) => {
    if (!message?.trim() || chatLoading) return;
    const userMsg = message.trim();
    setChatThread(prev => [...prev, { role: 'user', text: userMsg }]);
    setChatInput('');
    setChatLoading(true);

    try {
      const res = await api.post('/api/sentcom/chat', { message: userMsg });
      const reply = res.data?.response || 'Processing...';
      setChatThread(prev => [...prev, { role: 'assistant', text: reply }]);
    } catch (err) {
      setChatThread(prev => [...prev, { role: 'assistant', text: 'Unable to reach AI. Try again later.' }]);
    } finally {
      setChatLoading(false);
    }
  };

  const fetchHindsight = async () => {
    setHindsight({ data: null, narrative: '', loading: true, error: null });
    try {
      const res = await api.post(`/api/trades/snapshots/${tradeId}/hindsight?source=${source}`);
      if (res.data?.success) {
        setHindsight({
          data: res.data.hindsight.data,
          narrative: res.data.hindsight.narrative,
          loading: false,
          error: null
        });
      } else {
        setHindsight({ data: null, narrative: '', loading: false, error: 'Analysis unavailable' });
      }
    } catch (err) {
      setHindsight({ data: null, narrative: '', loading: false, error: 'Failed to generate analysis' });
    }
  };

  useEffect(() => {
    fetchSnapshot();
  }, [fetchSnapshot]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-zinc-500 text-sm">
        <RefreshCw className="w-4 h-4 animate-spin" />
        Loading snapshot...
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="flex items-center justify-between py-3 px-4 bg-white/5 rounded-lg border border-dashed border-white/10">
        <div className="flex items-center gap-2 text-zinc-500 text-sm">
          <Camera className="w-4 h-4" />
          <span>No chart snapshot yet</span>
        </div>
        <button
          onClick={generateSnapshot}
          disabled={generating}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
            generating
              ? 'bg-white/5 text-zinc-500 cursor-wait'
              : 'bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 border border-cyan-500/30'
          }`}
          data-testid={`generate-snapshot-${tradeId}`}
        >
          {generating ? (
            <>
              <RefreshCw className="w-3 h-3 animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Camera className="w-3 h-3" />
              Generate Snapshot
            </>
          )}
        </button>
      </div>
    );
  }

  const annotations = snapshot.annotations || [];

  return (
    <div className="space-y-3" data-testid={`snapshot-viewer-${tradeId}`}>
      {/* Chart Image */}
      {snapshot.chart_image && (
        <div className="relative rounded-lg overflow-hidden border border-white/10 bg-[#0a0a0a]">
          <img
            src={`data:image/png;base64,${snapshot.chart_image}`}
            alt={`${snapshot.symbol} trade chart`}
            className="w-full h-auto"
            data-testid={`snapshot-chart-${tradeId}`}
          />
          {/* Chart metadata overlay */}
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-3 py-2">
            <div className="flex items-center justify-between text-[10px] text-zinc-400">
              <span>{snapshot.timeframe} chart</span>
              <span>{snapshot.bars_count > 0 ? `${snapshot.bars_count} bars` : 'No data'}{snapshot.bars_source === 'synthetic' ? ' (simulated)' : snapshot.bars_source === 'historical' ? ' (live data)' : ''}</span>
              <span>Generated {new Date(snapshot.generated_at).toLocaleDateString()}</span>
            </div>
          </div>
        </div>
      )}

      {/* AI Decision Timeline */}
      {annotations.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-xs text-zinc-400 font-medium px-1">
            <MessageSquare className="w-3 h-3" />
            AI Decision Timeline
          </div>
          <div className="space-y-1">
            {annotations.map((ann, i) => {
              const style = ANNOTATION_COLORS[ann.type] || ANNOTATION_COLORS.entry;
              const isActive = activeAnnotation === i;
              const explanation = aiExplanation[i];

              return (
                <div
                  key={i}
                  className={`rounded-lg border transition-all ${style.bg} ${style.border} ${
                    isActive ? 'ring-1 ring-white/20' : ''
                  }`}
                  data-testid={`annotation-${ann.type}-${i}`}
                >
                  {/* Annotation header - clickable */}
                  <div
                    className="flex items-center gap-2 px-3 py-2 cursor-pointer"
                    onClick={() => setActiveAnnotation(isActive ? null : i)}
                  >
                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${style.dot}`} />
                    <span className={`text-xs font-bold ${style.text}`}>{ann.label}</span>
                    {ann.price > 0 && (
                      <span className="text-xs font-mono text-zinc-400">${ann.price?.toFixed(2)}</span>
                    )}
                    {ann.time && (
                      <span className="text-[10px] text-zinc-500 ml-auto flex items-center gap-1">
                        <Clock className="w-2.5 h-2.5" />
                        {new Date(ann.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    )}
                    <ChevronDown className={`w-3 h-3 text-zinc-500 transition-transform ${isActive ? 'rotate-180' : ''}`} />
                  </div>

                  {/* Expanded content */}
                  <AnimatePresence>
                    {isActive && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden"
                      >
                        <div className="px-3 pb-3 pt-0.5 border-t border-white/5 space-y-2">
                          {/* Recorded reasons */}
                          {ann.reasons?.length > 0 && (
                            <div className="space-y-0.5">
                              {ann.reasons.map((reason, ri) => (
                                <p key={ri} className="text-[11px] text-zinc-400 leading-relaxed pl-4">
                                  {reason}
                                </p>
                              ))}
                            </div>
                          )}

                          {/* AI Explanation section */}
                          {explanation?.text && (
                            <div className="mt-2 p-2.5 rounded-lg bg-cyan-500/5 border border-cyan-500/20">
                              <div className="flex items-center gap-1.5 mb-1.5">
                                <Zap className="w-3 h-3 text-cyan-400" />
                                <span className="text-[10px] font-semibold text-cyan-400">AI Analysis</span>
                              </div>
                              <p className="text-[11px] text-zinc-300 leading-relaxed whitespace-pre-wrap">
                                {explanation.text}
                              </p>
                            </div>
                          )}

                          {explanation?.error && (
                            <p className="text-[10px] text-red-400 pl-4">{explanation.error}</p>
                          )}

                          {/* Action buttons */}
                          <div className="flex items-center gap-2 pt-1">
                            <button
                              onClick={(e) => { e.stopPropagation(); explainAnnotation(i); }}
                              disabled={explanation?.loading}
                              className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-medium transition-all ${
                                explanation?.loading
                                  ? 'bg-cyan-500/10 text-cyan-500/50 cursor-wait'
                                  : 'bg-cyan-500/15 text-cyan-400 hover:bg-cyan-500/25 border border-cyan-500/20'
                              }`}
                              data-testid={`ask-ai-${ann.type}-${i}`}
                            >
                              {explanation?.loading ? (
                                <>
                                  <RefreshCw className="w-2.5 h-2.5 animate-spin" />
                                  Analyzing...
                                </>
                              ) : explanation?.text ? (
                                <>
                                  <Zap className="w-2.5 h-2.5" />
                                  Re-analyze
                                </>
                              ) : (
                                <>
                                  <Zap className="w-2.5 h-2.5" />
                                  Ask AI
                                </>
                              )}
                            </button>

                            <button
                              onClick={(e) => { e.stopPropagation(); openInChat(i); }}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-medium bg-violet-500/15 text-violet-400 hover:bg-violet-500/25 border border-violet-500/20 transition-all"
                              data-testid={`chat-about-${ann.type}-${i}`}
                            >
                              <MessageSquare className="w-2.5 h-2.5" />
                              Ask More in Chat
                            </button>
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Inline Chat Thread — contextual conversation about this trade */}
      {chatThread.length > 0 && (
        <div className="space-y-2 rounded-lg border border-violet-500/20 bg-violet-500/5 p-3" data-testid={`snapshot-chat-${tradeId}`}>
          <div className="flex items-center gap-1.5 text-[10px] font-semibold text-violet-400">
            <MessageSquare className="w-3 h-3" />
            Trade Discussion
          </div>

          {/* Messages */}
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {chatThread.map((msg, mi) => (
              <div key={mi} className={`flex gap-2 ${msg.role === 'user' ? 'justify-end' : ''}`}>
                {msg.role !== 'user' && (
                  <div className={`w-5 h-5 rounded flex items-center justify-center flex-shrink-0 ${
                    msg.role === 'context' ? 'bg-violet-500/20' : 'bg-cyan-500/20'
                  }`}>
                    {msg.role === 'context' ? <Target className="w-2.5 h-2.5 text-violet-400" /> : <Zap className="w-2.5 h-2.5 text-cyan-400" />}
                  </div>
                )}
                <div className={`rounded-lg px-2.5 py-1.5 text-[11px] leading-relaxed max-w-[85%] ${
                  msg.role === 'user'
                    ? 'bg-cyan-500/20 text-cyan-200'
                    : msg.role === 'context'
                    ? 'bg-violet-500/10 text-zinc-400 italic'
                    : 'bg-white/5 text-zinc-300'
                }`}>
                  {msg.role === 'context' ? (
                    <span className="text-[10px]">{msg.text}</span>
                  ) : (
                    <span className="whitespace-pre-wrap">{msg.text}</span>
                  )}
                </div>
              </div>
            ))}
            {chatLoading && (
              <div className="flex gap-2">
                <div className="w-5 h-5 rounded bg-cyan-500/20 flex items-center justify-center">
                  <RefreshCw className="w-2.5 h-2.5 text-cyan-400 animate-spin" />
                </div>
                <div className="bg-white/5 rounded-lg px-2.5 py-1.5 text-[11px] text-zinc-500">
                  Thinking...
                </div>
              </div>
            )}
          </div>

          {/* Chat input */}
          <div className="flex gap-2 mt-1">
            <input
              ref={chatInputRef}
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') sendChatMessage(chatInput); }}
              placeholder="Ask a follow-up about this trade..."
              className="flex-1 bg-white/5 border border-white/10 rounded-lg px-2.5 py-1.5 text-[11px] text-white placeholder-zinc-500 focus:outline-none focus:border-violet-500/40"
              disabled={chatLoading}
              data-testid={`snapshot-chat-input-${tradeId}`}
            />
            <button
              onClick={() => sendChatMessage(chatInput)}
              disabled={chatLoading || !chatInput.trim()}
              className="px-2 py-1 bg-violet-500/20 text-violet-400 rounded-lg hover:bg-violet-500/30 transition-colors disabled:opacity-40"
              data-testid={`snapshot-chat-send-${tradeId}`}
            >
              <ChevronUp className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* What I'd Do Differently — Hindsight Analysis */}
      <div className="space-y-2" data-testid={`hindsight-section-${tradeId}`}>
        {!hindsight.data && !hindsight.loading && (
          <button
            onClick={fetchHindsight}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border border-dashed border-amber-500/30 bg-amber-500/5 text-amber-400 text-xs font-medium hover:bg-amber-500/10 transition-all"
            data-testid={`hindsight-btn-${tradeId}`}
          >
            <Activity className="w-3.5 h-3.5" />
            What I'd Do Differently
          </button>
        )}

        {hindsight.loading && (
          <div className="flex items-center gap-2 py-3 px-4 rounded-lg bg-amber-500/5 border border-amber-500/20 text-amber-400 text-xs">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            Analyzing trade against current model knowledge...
          </div>
        )}

        {hindsight.data && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-lg border border-amber-500/20 bg-amber-500/5 overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center gap-2 px-3 py-2 border-b border-amber-500/10 bg-amber-500/10">
              <Activity className="w-3.5 h-3.5 text-amber-400" />
              <span className="text-xs font-bold text-amber-400">Hindsight Analysis</span>
              <span className="text-[10px] text-amber-500/60 ml-auto">vs current model</span>
            </div>

            <div className="p-3 space-y-3">
              {/* Data cards */}
              <div className="grid grid-cols-3 gap-2">
                {/* Similar trades stat */}
                <div className="rounded-md bg-white/5 px-2.5 py-2 text-center">
                  <div className="text-[10px] text-zinc-500">Similar Trades</div>
                  <div className="text-sm font-bold text-white">{hindsight.data.similar_trades?.count || 0}</div>
                  <div className={`text-[10px] font-medium ${
                    (hindsight.data.similar_trades?.win_rate || 0) >= 55 ? 'text-emerald-400' : 
                    (hindsight.data.similar_trades?.win_rate || 0) >= 45 ? 'text-amber-400' : 'text-red-400'
                  }`}>
                    {hindsight.data.similar_trades?.win_rate || 0}% WR
                  </div>
                </div>

                {/* Gate stance */}
                <div className="rounded-md bg-white/5 px-2.5 py-2 text-center">
                  <div className="text-[10px] text-zinc-500">Gate Today</div>
                  <div className={`text-sm font-bold ${
                    hindsight.data.current_gate_stance?.would_take_today === 'GO' ? 'text-emerald-400' :
                    hindsight.data.current_gate_stance?.would_take_today === 'REDUCE' ? 'text-amber-400' : 'text-red-400'
                  }`}>
                    {hindsight.data.current_gate_stance?.would_take_today || '?'}
                  </div>
                  <div className="text-[10px] text-zinc-500">
                    {hindsight.data.current_gate_stance?.avg_confidence || 0}% conf
                  </div>
                </div>

                {/* Learning loop */}
                <div className="rounded-md bg-white/5 px-2.5 py-2 text-center">
                  <div className="text-[10px] text-zinc-500">Outcomes Tracked</div>
                  <div className="text-sm font-bold text-white">{hindsight.data.learning_loop?.total_outcomes_tracked || 0}</div>
                  <div className="text-[10px] text-zinc-500">
                    {hindsight.data.learning_loop?.win_rate_from_outcomes || 0}% WR
                  </div>
                </div>
              </div>

              {/* Improvements list */}
              {hindsight.data.improvements?.length > 0 && (
                <div className="space-y-1">
                  <div className="text-[10px] font-semibold text-amber-400">Key Takeaways:</div>
                  {hindsight.data.improvements.map((imp, ii) => (
                    <div key={ii} className="flex items-start gap-1.5 text-[11px] text-zinc-300 leading-relaxed">
                      <AlertTriangle className="w-3 h-3 text-amber-400 mt-0.5 flex-shrink-0" />
                      <span>{imp}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* AI Narrative */}
              {hindsight.narrative && (
                <div className="pt-2 border-t border-amber-500/10">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <Zap className="w-3 h-3 text-amber-400" />
                    <span className="text-[10px] font-semibold text-amber-400">AI Self-Review</span>
                  </div>
                  <p className="text-[11px] text-zinc-300 leading-relaxed whitespace-pre-wrap">
                    {hindsight.narrative}
                  </p>
                </div>
              )}

              {/* Refresh button */}
              <div className="flex justify-end pt-1">
                <button
                  onClick={fetchHindsight}
                  disabled={hindsight.loading}
                  className="flex items-center gap-1 text-[10px] text-amber-500/60 hover:text-amber-400 transition-colors"
                >
                  <RefreshCw className={`w-2.5 h-2.5 ${hindsight.loading ? 'animate-spin' : ''}`} />
                  Re-analyze
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {hindsight.error && (
          <p className="text-[10px] text-red-400 px-1">{hindsight.error}</p>
        )}
      </div>

      {/* Regenerate button */}
      <div className="flex justify-end">
        <button
          onClick={generateSnapshot}
          disabled={generating}
          className="flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
          data-testid={`regenerate-snapshot-${tradeId}`}
        >
          <RefreshCw className={`w-2.5 h-2.5 ${generating ? 'animate-spin' : ''}`} />
          {generating ? 'Regenerating...' : 'Regenerate'}
        </button>
      </div>

      {error && (
        <p className="text-xs text-red-400 px-1">{error}</p>
      )}
    </div>
  );
};

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

// Context Badge
const ContextBadge = ({ context, size = 'sm' }) => {
  const styles = {
    TRENDING: 'bg-green-500/20 text-green-400 border-green-500/30',
    CONSOLIDATION: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    MEAN_REVERSION: 'bg-purple-500/20 text-purple-400 border-purple-500/30'
  };
  
  const icons = {
    TRENDING: <TrendingUp className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
    CONSOLIDATION: <Activity className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
    MEAN_REVERSION: <Target className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />
  };
  
  if (!context) return null;
  
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium ${styles[context] || 'bg-zinc-500/20 text-zinc-400'}`}>
      {icons[context]}
      {context?.replace('_', ' ')}
    </span>
  );
};

// AI Context Badge Component
const AIContextBadge = ({ aiContext }) => {
  if (!aiContext) return null;
  
  const gate = aiContext.confidence_gate;
  const prediction = aiContext.model_prediction;
  const tqsScore = aiContext.tqs_score;
  
  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-2">
      {gate && (
        <span
          data-testid="ai-gate-badge"
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${
            gate.decision === 'GO' ? 'bg-green-500/20 text-green-400 border-green-500/30' :
            gate.decision === 'REDUCE' ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
            'bg-red-500/20 text-red-400 border-red-500/30'
          }`}
          title={gate.reasoning?.join(' | ') || ''}
        >
          <Zap className="w-3 h-3" />
          Gate: {gate.decision} ({gate.confidence_score}%)
        </span>
      )}
      {prediction && (
        <span
          data-testid="ai-prediction-badge"
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${
            prediction.direction === 'up' ? 'bg-green-500/20 text-green-400 border-green-500/30' :
            prediction.direction === 'down' ? 'bg-red-500/20 text-red-400 border-red-500/30' :
            'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'
          }`}
        >
          <BarChart3 className="w-3 h-3" />
          Model: {prediction.direction?.toUpperCase()} ({(prediction.confidence * 100).toFixed(0)}%)
        </span>
      )}
      {tqsScore != null && (
        <span
          data-testid="ai-tqs-badge"
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${
            tqsScore >= 70 ? 'bg-green-500/20 text-green-400 border-green-500/30' :
            tqsScore >= 50 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
            'bg-red-500/20 text-red-400 border-red-500/30'
          }`}
        >
          <Award className="w-3 h-3" />
          TQS: {tqsScore} ({aiContext.tqs_grade || ''})
        </span>
      )}
      {gate?.trading_mode && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-white/5 text-zinc-400 border border-white/10">
          Mode: {gate.trading_mode}
        </span>
      )}
    </div>
  );
};
const StatCard = ({ label, value, icon: Icon, color = 'primary', subtext }) => (
  <Card className={`bg-gradient-to-br from-${color}/10 to-${color}/5`}>
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-zinc-500 uppercase">{label}</p>
        <p className={`text-2xl font-bold mt-1 ${
          color === 'green' ? 'text-green-400' :
          color === 'red' ? 'text-red-400' :
          color === 'yellow' ? 'text-yellow-400' :
          'text-primary'
        }`}>{value}</p>
        {subtext && <p className="text-xs text-zinc-500 mt-1">{subtext}</p>}
      </div>
      {Icon && <Icon className={`w-8 h-8 opacity-50 ${
        color === 'green' ? 'text-green-400' :
        color === 'red' ? 'text-red-400' :
        color === 'yellow' ? 'text-yellow-400' :
        'text-primary'
      }`} />}
    </div>
  </Card>
);

// Trade Row Component
const TradeRow = ({ trade, onClose, onEdit, onDelete, onUpdateNotes, onEnrichAI }) => {
  const isOpen = trade.status === 'open';
  const isProfitable = trade.pnl > 0;
  const [showNotesInput, setShowNotesInput] = useState(false);
  const [localNotes, setLocalNotes] = useState(trade.notes || '');
  const [enriching, setEnriching] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);
  
  const handleSaveNotes = () => {
    onUpdateNotes(trade.id, localNotes);
    setShowNotesInput(false);
  };

  const handleEnrich = async () => {
    setEnriching(true);
    try {
      await onEnrichAI(trade.id);
    } finally {
      setEnriching(false);
    }
  };
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`bg-white/5 rounded-lg p-4 border ${
        isOpen ? 'border-primary/30' : isProfitable ? 'border-green-500/20' : 'border-red-500/20'
      }`}
      data-testid={`trade-row-${trade.id}`}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${
            isOpen ? 'bg-primary/20' : isProfitable ? 'bg-green-500/20' : 'bg-red-500/20'
          }`}>
            {isOpen ? (
              <Activity className="w-6 h-6 text-primary" />
            ) : isProfitable ? (
              <CheckCircle className="w-6 h-6 text-green-400" />
            ) : (
              <XCircle className="w-6 h-6 text-red-400" />
            )}
          </div>
          
          <div className="flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-lg">{trade.symbol}</span>
              <span className={`text-xs px-2 py-0.5 rounded ${
                trade.direction === 'long' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
              }`}>
                {trade.direction?.toUpperCase()}
              </span>
              <span className="badge badge-info text-xs">{trade.strategy_id}</span>
              <ContextBadge context={trade.market_context} />
              <span className={`text-xs px-2 py-0.5 rounded ${
                isOpen ? 'bg-primary/20 text-primary' : 'bg-zinc-500/20 text-zinc-400'
              }`}>
                {trade.status?.toUpperCase()}
              </span>
              {trade.source && trade.source !== 'manual' && (
                <span className={`text-xs px-2 py-0.5 rounded ${
                  trade.source === 'bot' ? 'bg-purple-500/20 text-purple-400' : 'bg-blue-500/20 text-blue-400'
                }`}>
                  {trade.source.toUpperCase()}
                </span>
              )}
            </div>
            
            {/* AI Context Badges */}
            <AIContextBadge aiContext={trade.ai_context} />
            
            <div className="flex items-center gap-4 mt-2 text-sm">
              <span className="text-zinc-400">
                Entry: <span className="text-white font-mono">${trade.entry_price?.toFixed(2)}</span>
              </span>
              <span className="text-zinc-400">
                Shares: <span className="text-white font-mono">{trade.shares}</span>
              </span>
              {trade.exit_price && (
                <span className="text-zinc-400">
                  Exit: <span className="text-white font-mono">${trade.exit_price?.toFixed(2)}</span>
                </span>
              )}
              {trade.stop_loss && (
                <span className="text-zinc-400">
                  SL: <span className="text-red-400 font-mono">${trade.stop_loss?.toFixed(2)}</span>
                </span>
              )}
              {trade.take_profit && (
                <span className="text-zinc-400">
                  TP: <span className="text-green-400 font-mono">${trade.take_profit?.toFixed(2)}</span>
                </span>
              )}
            </div>
            
            <p className="text-xs text-zinc-500 mt-2">
              {new Date(trade.entry_date).toLocaleDateString()} 
              {trade.holding_days != null && trade.holding_days !== undefined && ` • ${trade.holding_days} day${trade.holding_days !== 1 ? 's' : ''}`}
              {trade.close_reason && (
                <span className="ml-2 text-zinc-400">
                  • Closed: <span className="text-white">{trade.close_reason.replace(/_/g, ' ')}</span>
                </span>
              )}
            </p>
            
            {/* Bot trade extra details */}
            {trade.source === 'bot' && (trade.quality_grade || trade.trade_style) && (
              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                {trade.quality_grade && (
                  <span className="text-xs px-2 py-0.5 rounded bg-white/5 text-zinc-400 border border-white/10">
                    Grade: {trade.quality_grade}
                  </span>
                )}
                {trade.trade_style && (
                  <span className="text-xs px-2 py-0.5 rounded bg-white/5 text-zinc-400 border border-white/10">
                    {trade.trade_style.replace(/_/g, ' ')}
                  </span>
                )}
                {trade.mfe_pct > 0 && (
                  <span className="text-xs text-green-400">
                    MFE: +{trade.mfe_pct?.toFixed(2)}%
                  </span>
                )}
                {trade.mae_pct < 0 && (
                  <span className="text-xs text-red-400">
                    MAE: {trade.mae_pct?.toFixed(2)}%
                  </span>
                )}
              </div>
            )}
            
            {/* Notes Section */}
            {showNotesInput ? (
              <div className="mt-3 space-y-2">
                <textarea
                  value={localNotes}
                  onChange={(e) => setLocalNotes(e.target.value)}
                  placeholder="Add trade notes..."
                  rows={2}
                  className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2 text-sm resize-none focus:border-primary/50 focus:outline-none"
                  autoFocus
                />
                <div className="flex gap-2">
                  <button
                    onClick={handleSaveNotes}
                    className="text-xs bg-primary/20 text-primary px-3 py-1 rounded hover:bg-primary/30 transition-colors"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => { setShowNotesInput(false); setLocalNotes(trade.notes || ''); }}
                    className="text-xs bg-white/5 text-zinc-400 px-3 py-1 rounded hover:bg-white/10 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : trade.notes ? (
              <div 
                className="mt-2 p-2 bg-white/5 rounded-lg cursor-pointer hover:bg-white/10 transition-colors group"
                onClick={() => setShowNotesInput(true)}
              >
                <p className="text-xs text-zinc-400 italic flex items-start gap-2">
                  <FileText className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <span className="flex-1">{trade.notes}</span>
                  <Edit3 className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                </p>
              </div>
            ) : (
              <button
                onClick={() => setShowNotesInput(true)}
                className="mt-2 text-xs text-zinc-500 hover:text-primary flex items-center gap-1 transition-colors"
              >
                <Plus className="w-3 h-3" />
                Add notes
              </button>
            )}
          </div>
        </div>
        
        <div className="flex flex-col items-end gap-2">
          {!isOpen && (
            <div className="text-right">
              <p className={`text-xl font-bold ${isProfitable ? 'text-green-400' : 'text-red-400'}`}>
                {isProfitable ? '+' : ''}{trade.pnl_percent?.toFixed(2)}%
              </p>
              <p className={`text-sm ${isProfitable ? 'text-green-400' : 'text-red-400'}`}>
                {isProfitable ? '+' : ''}${trade.pnl?.toFixed(2)}
              </p>
            </div>
          )}
          
          <div className="flex items-center gap-2">
            {/* Chart Snapshot toggle - available for all closed trades */}
            {!isOpen && (
              <button
                onClick={() => setShowSnapshot(!showSnapshot)}
                className={`p-2 rounded-lg transition-colors ${
                  showSnapshot ? 'text-cyan-400 bg-cyan-500/20' : 'text-zinc-400 hover:bg-white/10'
                }`}
                title={showSnapshot ? 'Hide Chart Snapshot' : 'View Chart Snapshot'}
                data-testid={`toggle-snapshot-${trade.id}`}
              >
                <Camera className="w-4 h-4" />
              </button>
            )}
            {isOpen && trade.source !== 'bot' && (
              <>
                <button
                  onClick={() => onClose(trade)}
                  className="p-2 text-green-400 hover:bg-green-500/20 rounded-lg transition-colors"
                  title="Close Trade"
                  data-testid={`close-trade-${trade.id}`}
                >
                  <CheckCircle className="w-4 h-4" />
                </button>
                {!trade.ai_context && (
                  <button
                    onClick={handleEnrich}
                    className={`p-2 text-amber-400 hover:bg-amber-500/20 rounded-lg transition-colors ${enriching ? 'animate-pulse' : ''}`}
                    title="Enrich with AI Context"
                    disabled={enriching}
                    data-testid={`enrich-ai-${trade.id}`}
                  >
                    <Zap className="w-4 h-4" />
                  </button>
                )}
                <button
                  onClick={() => setShowNotesInput(true)}
                  className="p-2 text-zinc-400 hover:bg-white/10 rounded-lg transition-colors"
                  title="Add/Edit Notes"
                >
                  <FileText className="w-4 h-4" />
                </button>
              </>
            )}
            {isOpen && trade.source !== 'bot' && (
              <button
                onClick={() => onDelete(trade.id)}
                className="p-2 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors"
                title="Delete"
                data-testid={`delete-trade-${trade.id}`}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
            {!isOpen && trade.source !== 'bot' && (
              <button
                onClick={() => setShowNotesInput(true)}
                className="p-2 text-zinc-400 hover:bg-white/10 rounded-lg transition-colors"
                title="Add/Edit Notes"
              >
                <FileText className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
      
      {/* Chart Snapshot Viewer - Expandable */}
      <AnimatePresence>
        {showSnapshot && !isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: 'easeInOut' }}
            className="overflow-hidden border-t border-white/5"
          >
            <div className="p-4 bg-[#0a0a0a]/50">
              <TradeSnapshotViewer
                tradeId={trade.id}
                source={trade.source || 'manual'}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

// Performance Matrix Component
const PerformanceMatrix = ({ matrix, aiInsights }) => {
  if (!matrix || !matrix.top_combinations || matrix.top_combinations.length === 0) {
    return (
      <div className="text-center py-8 text-zinc-500">
        <BarChart3 className="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p>No performance data yet</p>
        <p className="text-sm">Log and close some trades to see insights</p>
      </div>
    );
  }
  
  return (
    <div className="space-y-4">
      <h3 className="font-semibold flex items-center gap-2">
        <Award className="w-5 h-5 text-yellow-400" />
        Best Strategy-Context Combinations
      </h3>
      <div className="space-y-2">
        {matrix.top_combinations.slice(0, 5).map((combo, idx) => {
          const stratInsight = aiInsights?.[combo.strategy];
          const edgeTrend = stratInsight?.edge_trend;
          return (
            <div key={idx} className="bg-white/5 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                    idx === 0 ? 'bg-yellow-500 text-black' :
                    idx === 1 ? 'bg-zinc-400 text-black' :
                    idx === 2 ? 'bg-amber-700 text-white' :
                    'bg-zinc-700 text-white'
                  }`}>
                    {idx + 1}
                  </span>
                  <div>
                    <span className="font-medium">{combo.strategy}</span>
                    <span className="text-zinc-500 mx-2">in</span>
                    <ContextBadge context={combo.context} />
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <p className="text-sm text-green-400">{combo.win_rate}% win</p>
                    <p className="text-xs text-zinc-500">{combo.trades} trades</p>
                  </div>
                  <div className={`text-right ${combo.avg_pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {combo.avg_pnl_percent >= 0 ? '+' : ''}{combo.avg_pnl_percent?.toFixed(1)}%
                  </div>
                </div>
              </div>
              {/* AI Metrics Row */}
              {(combo.ai_win_rate || combo.gate_go > 0 || edgeTrend) && (
                <div className="flex items-center gap-3 mt-2 pt-2 border-t border-white/5 flex-wrap">
                  {combo.ai_win_rate > 0 && (
                    <span className="text-[10px] flex items-center gap-1 text-violet-400">
                      <Zap className="w-3 h-3" />
                      AI WR: {combo.ai_win_rate}%
                    </span>
                  )}
                  {(combo.gate_go > 0 || combo.gate_reduce > 0) && (
                    <span className="text-[10px] text-zinc-400">
                      Gate: <span className="text-green-400">{combo.gate_go || 0} GO</span>
                      {combo.gate_reduce > 0 && <span className="text-amber-400 ml-1">{combo.gate_reduce} RED</span>}
                    </span>
                  )}
                  {edgeTrend?.trend && (
                    <span className={`text-[10px] flex items-center gap-1 ${
                      edgeTrend.trend === 'improving' ? 'text-green-400' :
                      edgeTrend.trend === 'declining' ? 'text-red-400' :
                      'text-zinc-500'
                    }`}>
                      {edgeTrend.trend === 'improving' ? <TrendingUp className="w-3 h-3" /> :
                       edgeTrend.trend === 'declining' ? <TrendingDown className="w-3 h-3" /> :
                       <Activity className="w-3 h-3" />}
                      Edge: {edgeTrend.trend} ({edgeTrend.delta > 0 ? '+' : ''}{edgeTrend.delta}%)
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      
      {matrix.worst_combinations && matrix.worst_combinations.length > 0 && (
        <>
          <h3 className="font-semibold flex items-center gap-2 mt-6">
            <AlertTriangle className="w-5 h-5 text-red-400" />
            Avoid These Combinations
          </h3>
          <div className="space-y-2">
            {matrix.worst_combinations.slice(0, 3).map((combo, idx) => {
              const stratInsight = aiInsights?.[combo.strategy];
              const edgeTrend = stratInsight?.edge_trend;
              return (
                <div key={idx} className="bg-red-500/5 border border-red-500/20 rounded-lg p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="font-medium">{combo.strategy}</span>
                      <span className="text-zinc-500">in</span>
                      <ContextBadge context={combo.context} />
                    </div>
                    <div className="flex items-center gap-4">
                      <p className="text-sm text-red-400">{combo.win_rate}% win</p>
                      <p className={`${combo.avg_pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {combo.avg_pnl_percent >= 0 ? '+' : ''}{combo.avg_pnl_percent?.toFixed(1)}%
                      </p>
                    </div>
                  </div>
                  {edgeTrend?.trend && (
                    <div className="mt-2 pt-2 border-t border-red-500/10">
                      <span className={`text-[10px] flex items-center gap-1 ${
                        edgeTrend.trend === 'declining' ? 'text-red-400' : 'text-zinc-500'
                      }`}>
                        {edgeTrend.trend === 'declining' ? <TrendingDown className="w-3 h-3" /> : <Activity className="w-3 h-3" />}
                        Edge: {edgeTrend.trend} ({edgeTrend.delta > 0 ? '+' : ''}{edgeTrend.delta}%)
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Per-Strategy AI Insights */}
      {aiInsights && Object.keys(aiInsights).length > 0 && (
        <>
          <h3 className="font-semibold flex items-center gap-2 mt-6">
            <Zap className="w-5 h-5 text-violet-400" />
            AI Performance by Strategy
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(aiInsights).filter(([_, v]) => v.total_trades >= 2).sort((a, b) => b[1].total_trades - a[1].total_trades).map(([strategy, data]) => (
              <div key={strategy} className="bg-white/5 rounded-lg p-3 border border-white/5" data-testid={`ai-strategy-${strategy}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-sm">{strategy}</span>
                  <span className={`text-sm font-bold ${data.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                    {data.win_rate}%
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 mb-2 text-center">
                  <div>
                    <p className="text-[9px] text-zinc-600 uppercase">Trades</p>
                    <p className="text-xs font-bold text-white">{data.total_trades}</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-zinc-600 uppercase">W/L</p>
                    <p className="text-xs"><span className="text-green-400">{data.wins}</span>/<span className="text-red-400">{data.losses}</span></p>
                  </div>
                  <div>
                    <p className="text-[9px] text-zinc-600 uppercase">Avg P&L</p>
                    <p className={`text-xs font-bold ${data.avg_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      ${data.avg_pnl?.toFixed(0)}
                    </p>
                  </div>
                </div>
                {/* Gate distribution bar */}
                {data.gate_stats?.total > 0 && (
                  <div className="mb-2">
                    <p className="text-[9px] text-zinc-600 uppercase mb-1">Gate Decisions</p>
                    <div className="flex h-2 rounded-full overflow-hidden bg-zinc-800">
                      {data.gate_stats.GO > 0 && (
                        <div className="bg-green-500 h-full" style={{ width: `${(data.gate_stats.GO / data.gate_stats.total * 100)}%` }} title={`GO: ${data.gate_stats.GO}`} />
                      )}
                      {data.gate_stats.REDUCE > 0 && (
                        <div className="bg-amber-500 h-full" style={{ width: `${(data.gate_stats.REDUCE / data.gate_stats.total * 100)}%` }} title={`REDUCE: ${data.gate_stats.REDUCE}`} />
                      )}
                      {data.gate_stats.SKIP > 0 && (
                        <div className="bg-red-500 h-full" style={{ width: `${(data.gate_stats.SKIP / data.gate_stats.total * 100)}%` }} title={`SKIP: ${data.gate_stats.SKIP}`} />
                      )}
                    </div>
                    <div className="flex justify-between mt-0.5">
                      <span className="text-[8px] text-green-400">{data.gate_stats.GO || 0} GO</span>
                      <span className="text-[8px] text-amber-400">{data.gate_stats.REDUCE || 0} RED</span>
                      <span className="text-[8px] text-red-400">{data.gate_stats.SKIP || 0} SKIP</span>
                    </div>
                  </div>
                )}
                {/* Edge trend */}
                {data.edge_trend?.trend && (
                  <div className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-md ${
                    data.edge_trend.trend === 'improving' ? 'bg-green-500/10 text-green-400' :
                    data.edge_trend.trend === 'declining' ? 'bg-red-500/10 text-red-400' :
                    'bg-zinc-500/10 text-zinc-400'
                  }`}>
                    {data.edge_trend.trend === 'improving' ? <TrendingUp className="w-3 h-3" /> :
                     data.edge_trend.trend === 'declining' ? <TrendingDown className="w-3 h-3" /> :
                     <Activity className="w-3 h-3" />}
                    Edge {data.edge_trend.trend}: {data.edge_trend.recent_win_rate}% recent vs {data.edge_trend.older_win_rate}% older
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

// Template Selection Component
const TemplateSelector = ({ templates, onSelect, selectedTemplate }) => {
  const [showTemplates, setShowTemplates] = useState(false);
  
  const basicTemplates = templates.filter(t => t.template_type === 'basic');
  const strategyTemplates = templates.filter(t => t.template_type === 'strategy');
  
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setShowTemplates(!showTemplates)}
        className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2 text-left flex items-center justify-between"
      >
        <span className={selectedTemplate ? 'text-white' : 'text-zinc-500'}>
          {selectedTemplate?.name || 'Select Template (Optional)'}
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${showTemplates ? 'rotate-180' : ''}`} />
      </button>
      
      {showTemplates && (
        <div className="absolute z-10 w-full mt-1 bg-paper border border-white/10 rounded-lg shadow-lg max-h-64 overflow-y-auto">
          <button
            type="button"
            onClick={() => { onSelect(null); setShowTemplates(false); }}
            className="w-full px-3 py-2 text-left text-zinc-400 hover:bg-white/5"
          >
            No template (manual entry)
          </button>
          
          {basicTemplates.length > 0 && (
            <>
              <div className="px-3 py-1 text-xs text-zinc-500 uppercase bg-white/5">Basic Templates</div>
              {basicTemplates.map((t, idx) => (
                <button
                  key={`basic-${idx}`}
                  type="button"
                  onClick={() => { onSelect(t); setShowTemplates(false); }}
                  className="w-full px-3 py-2 text-left hover:bg-white/5 flex items-center justify-between"
                >
                  <span>{t.name}</span>
                  <span className={`text-xs ${t.direction === 'long' ? 'text-green-400' : 'text-red-400'}`}>
                    {t.direction?.toUpperCase()}
                  </span>
                </button>
              ))}
            </>
          )}
          
          {strategyTemplates.length > 0 && (
            <>
              <div className="px-3 py-1 text-xs text-zinc-500 uppercase bg-white/5">Strategy Templates</div>
              {strategyTemplates.map((t, idx) => (
                <button
                  key={`strat-${idx}`}
                  type="button"
                  onClick={() => { onSelect(t); setShowTemplates(false); }}
                  className="w-full px-3 py-2 text-left hover:bg-white/5"
                >
                  <div className="flex items-center justify-between">
                    <span>{t.name}</span>
                    <ContextBadge context={t.market_context} />
                  </div>
                  <p className="text-xs text-zinc-500 mt-0.5">{t.strategy_id} • {t.direction}</p>
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
};

// ===================== IB ACCOUNT HISTORY TAB =====================
// ===================== TRADE JOURNAL PAGE =====================
const TradeJournalPage = () => {
  const { getData, setData: setAppData } = useAppState();
  const [activeTab, setActiveTab] = useState('trades'); // trades, playbook, drc, gameplan
  
  // Initialize from cached state for instant display on tab switch
  const [allTrades, setAllTrades] = useState(() => getData('journalTrades') || []);
  const [performance, setPerformance] = useState(() => getData('journalPerformance'));
  const [matrix, setMatrix] = useState(() => getData('journalMatrix'));
  const [loading, setLoading] = useState(() => !getData('journalTrades'));
  const [showNewTrade, setShowNewTrade] = useState(false);
  const [showCloseTrade, setShowCloseTrade] = useState(null);
  const [filter, setFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all'); // all, manual, bot
  const [templates, setTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  
  // Client-side filtered view (no API call needed)
  const trades = React.useMemo(() => {
    let filtered = allTrades;
    if (filter !== 'all') {
      filtered = filtered.filter(t => {
        if (filter === 'open') return t.status === 'open' || t.status === 'pending' || t.status === 'filled';
        if (filter === 'closed') return t.status === 'closed';
        return true;
      });
    }
    if (sourceFilter !== 'all') {
      filtered = filtered.filter(t => t.source === sourceFilter);
    }
    return filtered;
  }, [allTrades, filter, sourceFilter]);
  
  // New trade form state
  const [newTrade, setNewTrade] = useState({
    symbol: '',
    strategy_id: '',
    strategy_name: '',
    entry_price: '',
    shares: '',
    direction: 'long',
    market_context: '',
    stop_loss: '',
    take_profit: '',
    notes: ''
  });
  
  const [closePrice, setClosePrice] = useState('');
  const [closeNotes, setCloseNotes] = useState('');
  const [aiStats, setAiStats] = useState(null);
  const [aiInsights, setAiInsights] = useState(null);
  const [ibAccount, setIbAccount] = useState(null);
  const [ibPositions, setIbPositions] = useState([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // Always fetch ALL trades — filtering happens client-side
      const [tradesRes, templatesRes] = await Promise.all([
        api.get('/api/trades/unified', { params: { limit: 200 }, timeout: 20000 }),
        api.get('/api/trades/templates/list', { timeout: 10000 }),
      ]);
      
      const tradesData = tradesRes.data.trades || [];
      setAllTrades(tradesData);
      setTemplates(templatesRes.data.templates || []);
      setAppData('journalTrades', tradesData);
      setLoading(false);  // Unblock UI early — trades are visible

      // Secondary data in background (non-blocking)
      Promise.all([
        api.get('/api/trades/performance', { timeout: 15000 }).catch(() => ({ data: {} })),
        api.get('/api/trades/performance/matrix', { timeout: 15000 }).catch(() => ({ data: {} })),
        api.get('/api/trades/ai/learning-stats', { timeout: 10000 }).catch(() => ({ data: { stats: {} } })),
        api.get('/api/trades/ai/strategy-insights', { timeout: 10000 }).catch(() => ({ data: { insights: {} } })),
      ]).then(([perfRes, matrixRes, aiStatsRes, aiInsightsRes]) => {
        const perfData = perfRes.data;
        const matrixData = matrixRes.data;
        setPerformance(perfData);
        setMatrix(matrixData);
        setAiStats(aiStatsRes.data?.stats || null);
        setAiInsights(aiInsightsRes.data?.insights || null);
        setAppData('journalPerformance', perfData);
        setAppData('journalMatrix', matrixData);
      });

      // IB account data (non-blocking)
      Promise.all([
        api.get('/api/ib/account/summary').catch(() => ({ data: null })),
        api.get('/api/portfolio').catch(() => ({ data: { positions: [] } }))
      ]).then(([acctRes, portRes]) => {
        if (acctRes.data && acctRes.data.net_liquidation > 0) setIbAccount(acctRes.data);
        setIbPositions(portRes.data?.positions || []);
      });
    } catch (err) {
      console.error('Failed to load trade data:', err);
      setLoading(false);
    }
  }, [setAppData]);  // No filter deps — always loads all trades

  useEffect(() => { loadData(); }, [loadData]);

  // Handle template selection
  const handleTemplateSelect = (template) => {
    setSelectedTemplate(template);
    if (template) {
      setNewTrade(prev => ({
        ...prev,
        strategy_id: template.strategy_id || prev.strategy_id,
        strategy_name: template.strategy_name || prev.strategy_name,
        market_context: template.market_context || prev.market_context,
        direction: template.direction || prev.direction,
        shares: template.default_shares?.toString() || prev.shares,
        notes: template.notes || prev.notes
      }));
    }
  };

  // Calculate SL/TP from template when entry price changes
  const handleEntryPriceChange = (value) => {
    const entry = parseFloat(value);
    setNewTrade(prev => {
      const updated = { ...prev, entry_price: value };
      
      if (entry && selectedTemplate && !prev.stop_loss && !prev.take_profit) {
        const riskPct = (selectedTemplate.risk_percent || 1) / 100;
        const rewardRatio = selectedTemplate.reward_ratio || 2;
        
        if (prev.direction === 'long') {
          updated.stop_loss = (entry * (1 - riskPct)).toFixed(2);
          updated.take_profit = (entry * (1 + riskPct * rewardRatio)).toFixed(2);
        } else {
          updated.stop_loss = (entry * (1 + riskPct)).toFixed(2);
          updated.take_profit = (entry * (1 - riskPct * rewardRatio)).toFixed(2);
        }
      }
      
      return updated;
    });
  };

  const handleCreateTrade = async (e) => {
    e.preventDefault();
    try {
      await api.post('/api/trades', {
        ...newTrade,
        entry_price: parseFloat(newTrade.entry_price),
        shares: parseFloat(newTrade.shares),
        stop_loss: newTrade.stop_loss ? parseFloat(newTrade.stop_loss) : null,
        take_profit: newTrade.take_profit ? parseFloat(newTrade.take_profit) : null
      });
      setShowNewTrade(false);
      setSelectedTemplate(null);
      setNewTrade({
        symbol: '', strategy_id: '', strategy_name: '', entry_price: '', shares: '',
        direction: 'long', market_context: '', stop_loss: '', take_profit: '', notes: ''
      });
      loadData();
    } catch (err) {
      console.error('Failed to create trade:', err);
    }
  };

  const handleCloseTrade = async () => {
    if (!showCloseTrade || !closePrice) return;
    try {
      await api.post(`/api/trades/${showCloseTrade.id}/close`, {
        exit_price: parseFloat(closePrice),
        notes: closeNotes
      });
      setShowCloseTrade(null);
      setClosePrice('');
      setCloseNotes('');
      loadData();
    } catch (err) {
      console.error('Failed to close trade:', err);
    }
  };

  const handleDeleteTrade = async (tradeId) => {
    if (!window.confirm('Delete this trade?')) return;
    try {
      await api.delete(`/api/trades/${tradeId}`);
      loadData();
    } catch (err) {
      console.error('Failed to delete trade:', err);
    }
  };

  const handleUpdateNotes = async (tradeId, notes) => {
    try {
      await api.patch(`/api/trades/${tradeId}`, { notes });
      loadData();
    } catch (err) {
      console.error('Failed to update trade notes:', err);
    }
  };

  const handleEnrichAI = async (tradeId) => {
    try {
      await api.post(`/api/trades/${tradeId}/enrich-ai`);
      loadData();
    } catch (err) {
      console.error('Failed to enrich trade with AI:', err);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="trade-journal-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-primary" />
            Trading Journal
          </h1>
          <p className="text-zinc-500 text-sm">Playbooks, Daily Report Cards, Game Plans & Trade Log</p>
        </div>
        <div className="flex gap-2">
          <button onClick={loadData} className="btn-secondary flex items-center gap-2">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          {activeTab === 'trades' && (
            <button
              onClick={() => setShowNewTrade(true)}
              className="btn-primary flex items-center gap-2"
              data-testid="new-trade-btn"
            >
              <Plus className="w-4 h-4" />
              Log Trade
            </button>
          )}
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 p-1 bg-white/5 rounded-lg border border-white/10 w-fit overflow-x-auto">
        {[
          { id: 'trades', label: 'Trade Log', icon: BarChart3 },
          { id: 'weekly', label: 'Weekly Report', icon: Calendar },
          { id: 'playbook', label: 'Playbooks', icon: BookOpen },
          { id: 'drc', label: 'Daily Report Card', icon: FileText },
          { id: 'gameplan', label: 'Game Plan', icon: Map }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === tab.id
                ? 'bg-primary text-black'
                : 'text-zinc-400 hover:text-white hover:bg-white/5'
            }`}
            data-testid={`journal-tab-${tab.id}`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'playbook' && <PlaybookTab />}
      {activeTab === 'drc' && <DRCTab />}
      {activeTab === 'gameplan' && <GamePlanTab />}
      {activeTab === 'weekly' && <WeeklyReportTab />}
      
      {/* Original Trade Log Content (only show when trades tab is active) */}
      {activeTab === 'trades' && (
        <>
          {/* IB Account Summary — merged from IB Account tab */}
          {ibAccount && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="ib-account-summary">
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Net Liquidation</p>
                <p className="text-xl font-bold text-primary">${ibAccount.net_liquidation?.toLocaleString()}</p>
                <p className="text-[10px] text-zinc-500">{ibAccount.account_id}</p>
              </div>
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Buying Power</p>
                <p className="text-xl font-bold text-blue-400">${ibAccount.buying_power?.toLocaleString()}</p>
              </div>
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Daily P&L</p>
                <p className={`text-xl font-bold ${(ibAccount.daily_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  ${ibAccount.daily_pnl?.toLocaleString() || '0.00'}
                </p>
                <p className={`text-[10px] ${(ibAccount.daily_pnl_percent || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {(ibAccount.daily_pnl_percent || 0) >= 0 ? '+' : ''}{ibAccount.daily_pnl_percent?.toFixed(2)}%
                </p>
              </div>
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Unrealized P&L</p>
                <p className={`text-xl font-bold ${(ibAccount.unrealized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  ${ibAccount.unrealized_pnl?.toLocaleString() || '0.00'}
                </p>
              </div>
            </div>
          )}

          {/* Current Positions — collapsed by default */}
          {ibPositions.length > 0 && (
            <details className="group" data-testid="ib-positions-section">
              <summary className="flex items-center gap-2 cursor-pointer text-sm font-medium text-zinc-400 hover:text-white transition-colors py-2">
                <Briefcase className="w-4 h-4" />
                <span>Open Positions ({ibPositions.length})</span>
                <ChevronDown className="w-3.5 h-3.5 ml-auto transition-transform group-open:rotate-180" />
              </summary>
              <div className="mt-2 overflow-x-auto rounded-lg border border-white/10 bg-white/5">
                <table className="w-full text-sm">
                  <thead className="text-[10px] text-zinc-500 uppercase border-b border-white/10">
                    <tr>
                      <th className="text-left px-3 py-2">Symbol</th>
                      <th className="text-right px-3 py-2">Shares</th>
                      <th className="text-right px-3 py-2">Avg Cost</th>
                      <th className="text-right px-3 py-2">Current</th>
                      <th className="text-right px-3 py-2">Value</th>
                      <th className="text-right px-3 py-2">P&L</th>
                      <th className="text-right px-3 py-2">P&L %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ibPositions.map((pos, idx) => {
                      const positionPnl = pos.unrealized_pnl || pos.gain_loss || 0;
                      const positionPnlPct = pos.gain_loss_percent || (pos.current_price && pos.avg_cost ? ((pos.current_price - pos.avg_cost) / pos.avg_cost * 100) : 0);
                      return (
                        <tr key={idx} className="border-b border-white/5 hover:bg-white/5">
                          <td className="px-3 py-2 font-mono font-bold text-white">{pos.symbol}</td>
                          <td className="text-right px-3 py-2 text-zinc-300">{pos.shares?.toLocaleString()}</td>
                          <td className="text-right px-3 py-2 font-mono text-zinc-400">${pos.avg_cost?.toFixed(2)}</td>
                          <td className="text-right px-3 py-2 font-mono text-zinc-300">${pos.current_price?.toFixed(2) || '-'}</td>
                          <td className="text-right px-3 py-2 font-mono text-zinc-400">${pos.market_value?.toLocaleString() || '-'}</td>
                          <td className={`text-right px-3 py-2 font-mono ${positionPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            ${positionPnl?.toLocaleString()}
                          </td>
                          <td className={`text-right px-3 py-2 ${positionPnlPct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {positionPnlPct >= 0 ? '+' : ''}{positionPnlPct?.toFixed(2)}%
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </details>
          )}

          {/* Performance Summary */}
          {performance && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <StatCard
                label="Total Trades"
                value={performance.total_trades}
                icon={BookOpen}
                color="primary"
              />
              <StatCard
                label="Win Rate"
                value={`${performance.win_rate}%`}
                icon={Percent}
                color={performance.win_rate >= 50 ? 'green' : 'red'}
                subtext={`${performance.winning_trades}W / ${performance.losing_trades}L`}
              />
              <StatCard
                label="Total P&L"
                value={`$${performance.total_pnl?.toFixed(0)}`}
                icon={DollarSign}
                color={performance.total_pnl >= 0 ? 'green' : 'red'}
              />
          <StatCard
            label="Avg P&L"
            value={`$${performance.avg_pnl?.toFixed(0)}`}
            icon={TrendingUp}
            color={performance.avg_pnl >= 0 ? 'green' : 'red'}
          />
          <StatCard
            label="Best Context"
            value={performance.best_context?.context?.replace('_', ' ') || 'N/A'}
            icon={Target}
            color="yellow"
            subtext={performance.best_context ? `${performance.best_context.win_rate}% win` : ''}
          />
        </div>
      )}

      {/* AI Learning Loop Integration Status */}
      {aiStats && aiStats.journal_outcomes > 0 && (
        <Card hover={false} className="border-amber-500/20">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold flex items-center gap-2 text-sm">
              <Zap className="w-4 h-4 text-amber-400" />
              AI Learning Loop — Journal Feed
            </h3>
            <span className="text-xs text-zinc-500">{aiStats.journal_outcomes} trades fed to AI</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {aiStats.outcomes && Object.entries(aiStats.outcomes).map(([outcome, data]) => (
              <div key={outcome} className="bg-white/5 rounded-lg p-3">
                <p className="text-xs text-zinc-500 uppercase">{outcome}</p>
                <p className={`text-lg font-bold ${outcome === 'won' ? 'text-green-400' : outcome === 'lost' ? 'text-red-400' : 'text-zinc-400'}`}>
                  {data.count}
                </p>
                <p className={`text-xs ${data.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${data.pnl?.toFixed(0)}
                </p>
              </div>
            ))}
            {aiStats.confidence_gate_accuracy && Object.entries(aiStats.confidence_gate_accuracy).map(([decision, data]) => (
              <div key={decision} className="bg-white/5 rounded-lg p-3">
                <p className="text-xs text-zinc-500 uppercase">Gate {decision}</p>
                <p className="text-lg font-bold text-primary">
                  {(data.win_rate * 100).toFixed(0)}%
                </p>
                <p className="text-xs text-zinc-500">
                  {data.total} decisions
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Context Breakdown */}
      {performance?.context_breakdown && Object.keys(performance.context_breakdown).length > 0 && (
        <Card hover={false}>
          <h3 className="font-semibold mb-4">Performance by Market Context</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Object.entries(performance.context_breakdown).map(([ctx, data]) => (
              <div key={ctx} className="bg-white/5 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <ContextBadge context={ctx} size="md" />
                  <span className={`text-lg font-bold ${data.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                    {data.win_rate}%
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-zinc-500">{data.total_trades} trades</span>
                  <span className={data.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                    {data.total_pnl >= 0 ? '+' : ''}${data.total_pnl?.toFixed(0)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Strategy-Context Matrix */}
      <Card hover={false}>
        <PerformanceMatrix matrix={matrix} aiInsights={aiInsights} />
      </Card>

      {/* Filter Tabs */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex gap-2">
          {['all', 'open', 'closed'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              data-testid={`filter-status-${f}`}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                filter === f
                  ? 'bg-primary/20 text-primary border border-primary/30'
                  : 'bg-white/5 text-zinc-400 hover:bg-white/10'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div className="h-6 w-px bg-white/10" />
        <div className="flex gap-1 bg-white/5 rounded-lg p-1">
          {[
            { id: 'all', label: 'All Sources' },
            { id: 'manual', label: 'Manual' },
            { id: 'bot', label: 'Bot' }
          ].map((sf) => (
            <button
              key={sf.id}
              onClick={() => setSourceFilter(sf.id)}
              data-testid={`filter-source-${sf.id}`}
              className={`px-3 py-1 text-xs rounded-md transition-all ${
                sourceFilter === sf.id
                  ? sf.id === 'bot' ? 'bg-purple-500/20 text-purple-400' : sf.id === 'manual' ? 'bg-blue-500/20 text-blue-400' : 'bg-primary text-black'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              {sf.label}
            </button>
          ))}
        </div>
      </div>

      {/* Trades List */}
      <Card hover={false}>
        <h2 className="font-semibold mb-4">
          {filter === 'all' ? 'All Trades' : filter === 'open' ? 'Open Positions' : 'Closed Trades'} 
          ({trades.length})
        </h2>
        
        {loading ? (
          <div className="space-y-4">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-24 bg-white/5 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : trades.length > 0 ? (
          <div className="space-y-4">
            {trades.map((trade) => (
              <TradeRow
                key={trade.id}
                trade={trade}
                onClose={setShowCloseTrade}
                onEdit={() => {}}
                onDelete={handleDeleteTrade}
                onUpdateNotes={handleUpdateNotes}
                onEnrichAI={handleEnrichAI}
              />
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <BookOpen className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">No trades yet</p>
            <p className="text-zinc-600 text-sm mt-1">Click &quot;Log Trade&quot; to record your first trade</p>
          </div>
        )}
      </Card>

      {/* New Trade Modal */}
      <AnimatePresence>
        {showNewTrade && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={() => setShowNewTrade(false)}
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-paper border border-white/10 rounded-xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-bold flex items-center gap-2">
                  <FileText className="w-5 h-5 text-primary" />
                  Log New Trade
                </h2>
                <button onClick={() => { setShowNewTrade(false); setSelectedTemplate(null); }} className="text-zinc-500 hover:text-white">
                  <X className="w-6 h-6" />
                </button>
              </div>
              
              <form onSubmit={handleCreateTrade} className="space-y-4">
                {/* Template Selector */}
                <div>
                  <label className="text-xs text-zinc-500 uppercase block mb-1">
                    <Zap className="w-3 h-3 inline mr-1" />
                    Quick Template
                  </label>
                  <TemplateSelector 
                    templates={templates}
                    selectedTemplate={selectedTemplate}
                    onSelect={handleTemplateSelect}
                  />
                  {selectedTemplate && (
                    <p className="text-xs text-green-400 mt-1">
                      Template applied: {selectedTemplate.risk_percent}% risk, {selectedTemplate.reward_ratio}:1 R:R
                    </p>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-zinc-500 uppercase block mb-1">Symbol *</label>
                    <input
                      type="text"
                      value={newTrade.symbol}
                      onChange={(e) => setNewTrade({...newTrade, symbol: e.target.value.toUpperCase()})}
                      className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                      placeholder="AAPL"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 uppercase block mb-1">Strategy *</label>
                    <input
                      type="text"
                      value={newTrade.strategy_id}
                      onChange={(e) => setNewTrade({...newTrade, strategy_id: e.target.value.toUpperCase()})}
                      className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                      placeholder="INT-01"
                      required
                    />
                  </div>
                </div>
                
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-zinc-500 uppercase block mb-1">Entry Price *</label>
                    <input
                      type="number"
                      step="0.01"
                      value={newTrade.entry_price}
                      onChange={(e) => handleEntryPriceChange(e.target.value)}
                      className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                      placeholder="150.00"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 uppercase block mb-1">Shares *</label>
                    <input
                      type="number"
                      value={newTrade.shares}
                      onChange={(e) => setNewTrade({...newTrade, shares: e.target.value})}
                      className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                      placeholder="100"
                      required
                    />
                  </div>
                </div>
                
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-zinc-500 uppercase block mb-1">Direction</label>
                    <select
                      value={newTrade.direction}
                      onChange={(e) => setNewTrade({...newTrade, direction: e.target.value})}
                      className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                    >
                      <option value="long">Long</option>
                      <option value="short">Short</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 uppercase block mb-1">Market Context</label>
                    <select
                      value={newTrade.market_context}
                      onChange={(e) => setNewTrade({...newTrade, market_context: e.target.value})}
                      className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                    >
                      <option value="">Unknown</option>
                      <option value="TRENDING">Trending</option>
                      <option value="CONSOLIDATION">Consolidation</option>
                      <option value="MEAN_REVERSION">Mean Reversion</option>
                    </select>
                  </div>
                </div>
                
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-zinc-500 uppercase block mb-1">Stop Loss</label>
                    <input
                      type="number"
                      step="0.01"
                      value={newTrade.stop_loss}
                      onChange={(e) => setNewTrade({...newTrade, stop_loss: e.target.value})}
                      className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                      placeholder="145.00"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 uppercase block mb-1">Take Profit</label>
                    <input
                      type="number"
                      step="0.01"
                      value={newTrade.take_profit}
                      onChange={(e) => setNewTrade({...newTrade, take_profit: e.target.value})}
                      className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                      placeholder="160.00"
                    />
                  </div>
                </div>
                
                <div>
                  <label className="text-xs text-zinc-500 uppercase block mb-1">Notes</label>
                  <textarea
                    value={newTrade.notes}
                    onChange={(e) => setNewTrade({...newTrade, notes: e.target.value})}
                    className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2 h-20"
                    placeholder="Trade setup notes..."
                  />
                </div>
                
                <button type="submit" className="btn-primary w-full">
                  Log Trade
                </button>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Close Trade Modal */}
        <AnimatePresence>
        {showCloseTrade && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={() => setShowCloseTrade(null)}
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-paper border border-white/10 rounded-xl max-w-md w-full p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <h2 className="text-xl font-bold mb-4">Close Trade: {showCloseTrade.symbol}</h2>
              
              <div className="bg-white/5 rounded-lg p-4 mb-4">
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Entry Price:</span>
                  <span className="font-mono">${showCloseTrade.entry_price?.toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-sm mt-1">
                  <span className="text-zinc-500">Shares:</span>
                  <span className="font-mono">{showCloseTrade.shares}</span>
                </div>
              </div>
              
              <div className="space-y-4">
                <div>
                  <label className="text-xs text-zinc-500 uppercase block mb-1">Exit Price *</label>
                  <input
                    type="number"
                    step="0.01"
                    value={closePrice}
                    onChange={(e) => setClosePrice(e.target.value)}
                    className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2"
                    placeholder="155.00"
                    required
                  />
                </div>
                
                {closePrice && (
                  <div className={`text-center p-3 rounded-lg ${
                    parseFloat(closePrice) > showCloseTrade.entry_price
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-red-500/20 text-red-400'
                  }`}>
                    <p className="text-2xl font-bold">
                      {((parseFloat(closePrice) - showCloseTrade.entry_price) / showCloseTrade.entry_price * 100).toFixed(2)}%
                    </p>
                    <p className="text-sm">
                      ${((parseFloat(closePrice) - showCloseTrade.entry_price) * showCloseTrade.shares).toFixed(2)}
                    </p>
                  </div>
                )}
                
                <div>
                  <label className="text-xs text-zinc-500 uppercase block mb-1">Notes</label>
                  <textarea
                    value={closeNotes}
                    onChange={(e) => setCloseNotes(e.target.value)}
                    className="w-full bg-subtle border border-white/10 rounded-lg px-3 py-2 h-20"
                    placeholder="Exit reason..."
                  />
                </div>
                
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowCloseTrade(null)}
                    className="btn-secondary flex-1"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleCloseTrade}
                    className="btn-primary flex-1"
                    disabled={!closePrice}
                  >
                    Close Trade
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
        </>
      )}
    </div>
  );
};

export default TradeJournalPage;
