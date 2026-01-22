import React, { useState, useEffect, useCallback } from 'react';
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
  FileText,
  Zap
} from 'lucide-react';
import api from '../utils/api';

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

// Performance Stat Card
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
const TradeRow = ({ trade, onClose, onEdit, onDelete }) => {
  const isOpen = trade.status === 'open';
  const isProfitable = trade.pnl > 0;
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`bg-white/5 rounded-lg p-4 border ${
        isOpen ? 'border-primary/30' : isProfitable ? 'border-green-500/20' : 'border-red-500/20'
      }`}
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
          
          <div>
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
            </div>
            
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
              {trade.holding_days !== null && ` • ${trade.holding_days} day${trade.holding_days !== 1 ? 's' : ''}`}
            </p>
            
            {trade.notes && (
              <p className="text-xs text-zinc-400 mt-2 italic">"{trade.notes}"</p>
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
            {isOpen && (
              <>
                <button
                  onClick={() => onClose(trade)}
                  className="p-2 text-green-400 hover:bg-green-500/20 rounded-lg transition-colors"
                  title="Close Trade"
                >
                  <CheckCircle className="w-4 h-4" />
                </button>
                <button
                  onClick={() => onEdit(trade)}
                  className="p-2 text-zinc-400 hover:bg-white/10 rounded-lg transition-colors"
                  title="Edit"
                >
                  <Edit3 className="w-4 h-4" />
                </button>
              </>
            )}
            {isOpen && (
              <button
                onClick={() => onDelete(trade.id)}
                className="p-2 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors"
                title="Delete"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
};

// Performance Matrix Component
const PerformanceMatrix = ({ matrix }) => {
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
        {matrix.top_combinations.slice(0, 5).map((combo, idx) => (
          <div key={idx} className="flex items-center justify-between bg-white/5 rounded-lg p-3">
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
        ))}
      </div>
      
      {matrix.worst_combinations && matrix.worst_combinations.length > 0 && (
        <>
          <h3 className="font-semibold flex items-center gap-2 mt-6">
            <AlertTriangle className="w-5 h-5 text-red-400" />
            Avoid These Combinations
          </h3>
          <div className="space-y-2">
            {matrix.worst_combinations.slice(0, 3).map((combo, idx) => (
              <div key={idx} className="flex items-center justify-between bg-red-500/5 border border-red-500/20 rounded-lg p-3">
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

// ===================== TRADE JOURNAL PAGE =====================
const TradeJournalPage = () => {
  const [trades, setTrades] = useState([]);
  const [performance, setPerformance] = useState(null);
  const [matrix, setMatrix] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showNewTrade, setShowNewTrade] = useState(false);
  const [showCloseTrade, setShowCloseTrade] = useState(null);
  const [filter, setFilter] = useState('all');
  const [templates, setTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  
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

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [tradesRes, perfRes, matrixRes, templatesRes] = await Promise.all([
        api.get('/api/trades', { params: { status: filter !== 'all' ? filter : undefined } }),
        api.get('/api/trades/performance'),
        api.get('/api/trades/performance/matrix'),
        api.get('/api/trades/templates/list')
      ]);
      
      setTrades(tradesRes.data.trades || []);
      setPerformance(perfRes.data);
      setMatrix(matrixRes.data);
      setTemplates(templatesRes.data.templates || []);
    } catch (err) {
      console.error('Failed to load trade data:', err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

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

  return (
    <div className="space-y-6 animate-fade-in" data-testid="trade-journal-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-primary" />
            Trade Journal
          </h1>
          <p className="text-zinc-500 text-sm">Track trades and analyze strategy performance by market context</p>
        </div>
        <div className="flex gap-2">
          <button onClick={loadData} className="btn-secondary flex items-center gap-2">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={() => setShowNewTrade(true)}
            className="btn-primary flex items-center gap-2"
            data-testid="new-trade-btn"
          >
            <Plus className="w-4 h-4" />
            Log Trade
          </button>
        </div>
      </div>

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
        <PerformanceMatrix matrix={matrix} />
      </Card>

      {/* Filter Tabs */}
      <div className="flex gap-2">
        {['all', 'open', 'closed'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
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
              />
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <BookOpen className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">No trades yet</p>
            <p className="text-zinc-600 text-sm mt-1">Click "Log Trade" to record your first trade</p>
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
              className="bg-paper border border-white/10 rounded-xl max-w-lg w-full p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-bold">Log New Trade</h2>
                <button onClick={() => setShowNewTrade(false)} className="text-zinc-500 hover:text-white">
                  <X className="w-6 h-6" />
                </button>
              </div>
              
              <form onSubmit={handleCreateTrade} className="space-y-4">
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
                      onChange={(e) => setNewTrade({...newTrade, entry_price: e.target.value})}
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
    </div>
  );
};

export default TradeJournalPage;
