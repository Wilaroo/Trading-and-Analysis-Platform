import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Map, Plus, X, Save, Edit3, Trash2, ChevronDown, ChevronRight,
  Target, TrendingUp, TrendingDown, AlertCircle, Check, Clock,
  Zap, Activity, BarChart3, Calendar, DollarSign, RefreshCw
} from 'lucide-react';
import api from '../../utils/api';

// SMB Game Plan Component
const GamePlanTab = () => {
  const [gamePlan, setGamePlan] = useState(null);
  const [recentPlans, setRecentPlans] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editedPlan, setEditedPlan] = useState(null);
  const [showAddStock, setShowAddStock] = useState(false);
  const [expandedSection, setExpandedSection] = useState('stocks_in_play');

  // New stock form
  const [newStock, setNewStock] = useState({
    symbol: '',
    catalyst: '',
    setup_type: '',
    direction: 'long',
    if_then_statements: [
      { condition: '', action: '', notes: '' },
      { condition: '', action: '', notes: '' },
      { condition: '', action: '', notes: '' }
    ],
    key_levels: { entry: '', target_1: '', stop: '' },
    priority: 'secondary',
    notes: ''
  });

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      // Load today's game plan first (critical)
      const todayRes = await api.get('/api/journal/gameplan/today', { timeout: 15000 });
      setGamePlan(todayRes.data.game_plan);
      setEditedPlan(todayRes.data.game_plan);
      setLoading(false);  // Unblock UI
      
      // Secondary data in background
      Promise.all([
        api.get('/api/journal/gameplan/recent?limit=7', { timeout: 10000 }).catch(() => ({ data: { game_plans: [] } })),
        api.get('/api/journal/gameplan/stats?days=30', { timeout: 10000 }).catch(() => ({ data: {} }))
      ]).then(([recentRes, statsRes]) => {
        setRecentPlans(recentRes.data.game_plans || []);
        setStats(statsRes.data);
      });
    } catch (err) {
      console.error('Failed to load Game Plan data:', err);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSave = async () => {
    try {
      const res = await api.put(`/api/journal/gameplan/date/${gamePlan.date}`, editedPlan);
      if (res.data.success) {
        setGamePlan(res.data.game_plan);
        setEditing(false);
      }
    } catch (err) {
      console.error('Failed to save Game Plan:', err);
    }
  };

  const handleAddStock = async () => {
    try {
      const res = await api.post(`/api/journal/gameplan/date/${gamePlan.date}/stocks`, newStock);
      if (res.data.success) {
        await loadData();
        setShowAddStock(false);
        setNewStock({
          symbol: '', catalyst: '', setup_type: '', direction: 'long',
          if_then_statements: [
            { condition: '', action: '', notes: '' },
            { condition: '', action: '', notes: '' },
            { condition: '', action: '', notes: '' }
          ],
          key_levels: { entry: '', target_1: '', stop: '' },
          priority: 'secondary', notes: ''
        });
      }
    } catch (err) {
      console.error('Failed to add stock:', err);
    }
  };

  const handleRemoveStock = async (symbol) => {
    try {
      await api.delete(`/api/journal/gameplan/date/${gamePlan.date}/stocks/${symbol}`);
      await loadData();
    } catch (err) {
      console.error('Failed to remove stock:', err);
    }
  };

  const updateIfThen = (index, field, value) => {
    const updated = [...newStock.if_then_statements];
    updated[index] = { ...updated[index], [field]: value };
    setNewStock({ ...newStock, if_then_statements: updated });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="gameplan-tab">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Map className="w-5 h-5 text-amber-400" />
            Daily Game Plan
          </h2>
          <p className="text-xs text-zinc-500">
            {gamePlan?.date ? new Date(gamePlan.date).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) : 'Today'}
            {gamePlan?.is_night_before && <span className="ml-2 text-emerald-400">✓ Prepared night before</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadData}
            className="px-3 py-1.5 rounded-lg bg-zinc-700 text-white text-sm hover:bg-zinc-600 flex items-center gap-1"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          {editing ? (
            <>
              <button
                onClick={() => { setEditing(false); setEditedPlan(gamePlan); }}
                className="px-3 py-1.5 rounded-lg bg-zinc-700 text-white text-sm hover:bg-zinc-600"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                className="px-3 py-1.5 rounded-lg bg-amber-500 text-black text-sm font-medium hover:bg-amber-400 flex items-center gap-1"
              >
                <Save className="w-4 h-4" />
                Save
              </button>
            </>
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="px-3 py-1.5 rounded-lg bg-amber-500/20 text-amber-400 text-sm font-medium hover:bg-amber-500/30 flex items-center gap-1"
            >
              <Edit3 className="w-4 h-4" />
              Edit
            </button>
          )}
        </div>
      </div>

      {/* Stats Row */}
      {stats && (
        <div className="grid grid-cols-4 gap-3">
          <div className="p-2.5 rounded-lg bg-white/5 border border-white/10">
            <p className="text-[10px] text-zinc-500">30-Day Plans</p>
            <p className="text-lg font-bold text-white">{stats.total_plans}</p>
          </div>
          <div className="p-2.5 rounded-lg bg-white/5 border border-white/10">
            <p className="text-[10px] text-zinc-500">Completion Rate</p>
            <p className="text-lg font-bold text-emerald-400">{stats.completion_rate}%</p>
          </div>
          <div className="p-2.5 rounded-lg bg-white/5 border border-white/10">
            <p className="text-[10px] text-zinc-500">Night Before Prep</p>
            <p className="text-lg font-bold text-cyan-400">{stats.night_before_rate}%</p>
          </div>
          <div className="p-2.5 rounded-lg bg-white/5 border border-white/10">
            <p className="text-[10px] text-zinc-500">Avg Stocks/Plan</p>
            <p className="text-lg font-bold text-white">{stats.avg_stocks_per_plan}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {/* Left Column - Main Game Plan */}
        <div className="col-span-2 space-y-3">
          {/* Big Picture Commentary */}
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <button
              onClick={() => setExpandedSection(expandedSection === 'big_picture' ? null : 'big_picture')}
              className="w-full flex items-center justify-between"
            >
              <div className="flex items-center gap-2">
                <ChevronRight className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSection === 'big_picture' ? 'rotate-90' : ''}`} />
                <span className="text-sm font-medium">Big Picture Commentary</span>
              </div>
              <Activity className="w-4 h-4 text-zinc-500" />
            </button>
            <AnimatePresence>
              {expandedSection === 'big_picture' && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-3 space-y-3 overflow-hidden"
                >
                  <div>
                    <label className="text-[10px] text-zinc-500 uppercase">Market Overview</label>
                    {editing ? (
                      <textarea
                        value={editedPlan?.big_picture?.market_overview || ''}
                        onChange={(e) => setEditedPlan({
                          ...editedPlan,
                          big_picture: { ...editedPlan.big_picture, market_overview: e.target.value }
                        })}
                        className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-xs text-white outline-none resize-none"
                        rows={2}
                        placeholder="Overall market conditions, regime, bias..."
                      />
                    ) : (
                      <p className="text-xs text-zinc-300 mt-1">{gamePlan?.big_picture?.market_overview || 'Not filled yet'}</p>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase">Market Regime</label>
                      {editing ? (
                        <select
                          value={editedPlan?.big_picture?.market_regime || ''}
                          onChange={(e) => setEditedPlan({
                            ...editedPlan,
                            big_picture: { ...editedPlan.big_picture, market_regime: e.target.value }
                          })}
                          className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-xs text-white outline-none"
                        >
                          <option value="">Select...</option>
                          <option value="Trending Up">Trending Up</option>
                          <option value="Trending Down">Trending Down</option>
                          <option value="Consolidating">Consolidating</option>
                          <option value="Choppy">Choppy</option>
                        </select>
                      ) : (
                        <p className="text-xs text-zinc-300 mt-1">{gamePlan?.big_picture?.market_regime || '-'}</p>
                      )}
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase">Bias</label>
                      {editing ? (
                        <select
                          value={editedPlan?.big_picture?.bias || ''}
                          onChange={(e) => setEditedPlan({
                            ...editedPlan,
                            big_picture: { ...editedPlan.big_picture, bias: e.target.value }
                          })}
                          className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-xs text-white outline-none"
                        >
                          <option value="">Neutral</option>
                          <option value="Bullish">Bullish</option>
                          <option value="Bearish">Bearish</option>
                          <option value="Neutral">Neutral</option>
                        </select>
                      ) : (
                        <p className="text-xs text-zinc-300 mt-1">{gamePlan?.big_picture?.bias || 'Neutral'}</p>
                      )}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] text-zinc-500 uppercase">Recent Observations (What's Working)</label>
                    {editing ? (
                      <textarea
                        value={editedPlan?.big_picture?.recent_observations || ''}
                        onChange={(e) => setEditedPlan({
                          ...editedPlan,
                          big_picture: { ...editedPlan.big_picture, recent_observations: e.target.value }
                        })}
                        className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-xs text-white outline-none resize-none"
                        rows={2}
                        placeholder="What setups have been working recently?"
                      />
                    ) : (
                      <p className="text-xs text-zinc-300 mt-1">{gamePlan?.big_picture?.recent_observations || 'Not filled yet'}</p>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Stocks In Play */}
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <button
              onClick={() => setExpandedSection(expandedSection === 'stocks_in_play' ? null : 'stocks_in_play')}
              className="w-full flex items-center justify-between"
            >
              <div className="flex items-center gap-2">
                <ChevronRight className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSection === 'stocks_in_play' ? 'rotate-90' : ''}`} />
                <span className="text-sm font-medium">Stocks In Play</span>
                <span className="text-xs text-zinc-500">({gamePlan?.stocks_in_play?.length || 0}/5 max)</span>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); setShowAddStock(true); }}
                className="px-2 py-1 rounded bg-amber-500/20 text-amber-400 text-xs hover:bg-amber-500/30 flex items-center gap-1"
              >
                <Plus className="w-3 h-3" />
                Add
              </button>
            </button>
            <AnimatePresence>
              {expandedSection === 'stocks_in_play' && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-3 space-y-2 overflow-hidden"
                >
                  {gamePlan?.stocks_in_play?.length === 0 ? (
                    <div className="text-center py-4 text-zinc-500 text-xs">
                      No stocks added yet. Add your key names for today.
                    </div>
                  ) : (
                    gamePlan?.stocks_in_play?.map((stock, idx) => (
                      <div key={`${stock.symbol}-${idx}`} className="p-3 rounded bg-black/30 border border-white/5">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-bold text-white">{stock.symbol}</span>
                            <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                              stock.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                            }`}>
                              {stock.direction?.toUpperCase()}
                            </span>
                            <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                              stock.priority === 'primary' ? 'bg-amber-500/20 text-amber-400' : 'bg-zinc-500/20 text-zinc-400'
                            }`}>
                              {stock.priority}
                            </span>
                          </div>
                          <button
                            onClick={() => handleRemoveStock(stock.symbol)}
                            className="text-zinc-500 hover:text-red-400"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                        
                        {stock.catalyst && (
                          <p className="text-xs text-zinc-400 mb-2">Catalyst: {stock.catalyst}</p>
                        )}
                        
                        {/* Key Levels */}
                        <div className="flex gap-3 text-xs mb-2">
                          {stock.key_levels?.entry && (
                            <span className="text-zinc-500">Entry: <span className="text-white">${stock.key_levels.entry}</span></span>
                          )}
                          {stock.key_levels?.target_1 && (
                            <span className="text-zinc-500">Target: <span className="text-emerald-400">${stock.key_levels.target_1}</span></span>
                          )}
                          {stock.key_levels?.stop && (
                            <span className="text-zinc-500">Stop: <span className="text-red-400">${stock.key_levels.stop}</span></span>
                          )}
                        </div>
                        
                        {/* IF/THEN Statements */}
                        {stock.if_then_statements?.some(s => s.condition) && (
                          <div className="space-y-1">
                            {stock.if_then_statements.filter(s => s.condition).map((stmt, i) => (
                              <div key={i} className="text-[10px] p-1.5 rounded bg-black/40">
                                <span className="text-cyan-400">IF:</span> {stmt.condition}
                                <span className="text-emerald-400 ml-2">THEN:</span> {stmt.action}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Risk Management */}
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <button
              onClick={() => setExpandedSection(expandedSection === 'risk' ? null : 'risk')}
              className="w-full flex items-center justify-between"
            >
              <div className="flex items-center gap-2">
                <ChevronRight className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSection === 'risk' ? 'rotate-90' : ''}`} />
                <span className="text-sm font-medium">Risk Management</span>
              </div>
              <AlertCircle className="w-4 h-4 text-zinc-500" />
            </button>
            <AnimatePresence>
              {expandedSection === 'risk' && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-3 space-y-3 overflow-hidden"
                >
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase">Daily Stop</label>
                      {editing ? (
                        <input
                          type="text"
                          value={editedPlan?.risk_management?.daily_stop || ''}
                          onChange={(e) => setEditedPlan({
                            ...editedPlan,
                            risk_management: { ...editedPlan.risk_management, daily_stop: e.target.value }
                          })}
                          className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-xs text-white outline-none"
                          placeholder="e.g., $500"
                        />
                      ) : (
                        <p className="text-xs text-red-400 mt-1">{gamePlan?.risk_management?.daily_stop || 'Not set'}</p>
                      )}
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase">Per Trade Risk</label>
                      {editing ? (
                        <input
                          type="text"
                          value={editedPlan?.risk_management?.per_trade_risk || ''}
                          onChange={(e) => setEditedPlan({
                            ...editedPlan,
                            risk_management: { ...editedPlan.risk_management, per_trade_risk: e.target.value }
                          })}
                          className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-xs text-white outline-none"
                          placeholder="e.g., 1% of account"
                        />
                      ) : (
                        <p className="text-xs text-zinc-300 mt-1">{gamePlan?.risk_management?.per_trade_risk || 'Not set'}</p>
                      )}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] text-zinc-500 uppercase">Risk-Off Conditions</label>
                    {editing ? (
                      <textarea
                        value={editedPlan?.risk_management?.risk_off_conditions || ''}
                        onChange={(e) => setEditedPlan({
                          ...editedPlan,
                          risk_management: { ...editedPlan.risk_management, risk_off_conditions: e.target.value }
                        })}
                        className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-xs text-white outline-none resize-none"
                        rows={2}
                        placeholder="When will you stop trading? (e.g., 2 consecutive losses)"
                      />
                    ) : (
                      <p className="text-xs text-zinc-300 mt-1">{gamePlan?.risk_management?.risk_off_conditions || 'Not set'}</p>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* Right Column */}
        <div className="space-y-3">
          {/* Recent Plans */}
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
              <Calendar className="w-4 h-4 text-zinc-500" />
              Recent Game Plans
            </h3>
            <div className="space-y-2">
              {recentPlans.map((plan) => (
                <div
                  key={plan.date}
                  className={`p-2 rounded cursor-pointer transition-colors ${
                    plan.date === gamePlan?.date ? 'bg-amber-500/20 border border-amber-500/30' : 'hover:bg-white/5'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-zinc-400">
                      {new Date(plan.date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                    </span>
                    {plan.is_complete && <Check className="w-3 h-3 text-emerald-400" />}
                  </div>
                  <div className="flex items-center gap-2 mt-1 text-xs">
                    <span className="text-zinc-500">{plan.stocks_count} stocks</span>
                    {plan.is_night_before && <span className="text-cyan-400">Night prep</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Session Goals */}
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <h3 className="text-sm font-medium mb-2 flex items-center gap-2">
              <Target className="w-4 h-4 text-zinc-500" />
              Session Goals
            </h3>
            <div className="space-y-2 text-xs">
              {editing ? (
                <>
                  <div>
                    <label className="text-[10px] text-zinc-500">Primary Goal</label>
                    <input
                      type="text"
                      value={editedPlan?.session_goals?.primary_goal || ''}
                      onChange={(e) => setEditedPlan({
                        ...editedPlan,
                        session_goals: { ...editedPlan.session_goals, primary_goal: e.target.value }
                      })}
                      className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-white outline-none"
                      placeholder="Main focus for today"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-zinc-500">What to Avoid</label>
                    <input
                      type="text"
                      value={editedPlan?.session_goals?.what_to_avoid || ''}
                      onChange={(e) => setEditedPlan({
                        ...editedPlan,
                        session_goals: { ...editedPlan.session_goals, what_to_avoid: e.target.value }
                      })}
                      className="w-full mt-1 p-2 rounded bg-black/30 border border-white/10 text-white outline-none"
                      placeholder="Common mistakes to avoid"
                    />
                  </div>
                </>
              ) : (
                <>
                  <p className="text-zinc-300">{gamePlan?.session_goals?.primary_goal || 'No primary goal set'}</p>
                  {gamePlan?.session_goals?.what_to_avoid && (
                    <p className="text-red-400">Avoid: {gamePlan.session_goals.what_to_avoid}</p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Add Stock Modal */}
      <AnimatePresence>
        {showAddStock && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4"
            onClick={() => setShowAddStock(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-zinc-900 rounded-xl border border-zinc-700 w-full max-w-lg max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-4 border-b border-zinc-700 flex items-center justify-between">
                <h3 className="text-lg font-semibold">Add Stock to Game Plan</h3>
                <button onClick={() => setShowAddStock(false)} className="text-zinc-400 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="p-4 space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Symbol *</label>
                    <input
                      type="text"
                      value={newStock.symbol}
                      onChange={(e) => setNewStock({ ...newStock, symbol: e.target.value.toUpperCase() })}
                      placeholder="NVDA"
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-amber-500 outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Direction</label>
                    <select
                      value={newStock.direction}
                      onChange={(e) => setNewStock({ ...newStock, direction: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-amber-500 outline-none"
                    >
                      <option value="long">Long</option>
                      <option value="short">Short</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">Catalyst</label>
                  <input
                    type="text"
                    value={newStock.catalyst}
                    onChange={(e) => setNewStock({ ...newStock, catalyst: e.target.value })}
                    placeholder="e.g., Earnings beat, FDA approval"
                    className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-amber-500 outline-none"
                  />
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Entry</label>
                    <input
                      type="text"
                      value={newStock.key_levels.entry}
                      onChange={(e) => setNewStock({ ...newStock, key_levels: { ...newStock.key_levels, entry: e.target.value } })}
                      placeholder="$150"
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-amber-500 outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Target</label>
                    <input
                      type="text"
                      value={newStock.key_levels.target_1}
                      onChange={(e) => setNewStock({ ...newStock, key_levels: { ...newStock.key_levels, target_1: e.target.value } })}
                      placeholder="$160"
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-emerald-500 outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Stop</label>
                    <input
                      type="text"
                      value={newStock.key_levels.stop}
                      onChange={(e) => setNewStock({ ...newStock, key_levels: { ...newStock.key_levels, stop: e.target.value } })}
                      placeholder="$145"
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-red-500 outline-none"
                    />
                  </div>
                </div>

                {/* IF/THEN Statements */}
                <div>
                  <label className="text-xs text-zinc-500 mb-2 block">IF/THEN Statements</label>
                  <div className="space-y-2">
                    {newStock.if_then_statements.map((stmt, idx) => (
                      <div key={idx} className="grid grid-cols-2 gap-2">
                        <input
                          type="text"
                          value={stmt.condition}
                          onChange={(e) => updateIfThen(idx, 'condition', e.target.value)}
                          placeholder={`IF condition ${idx + 1}...`}
                          className="px-2 py-1.5 rounded bg-white/5 border border-white/10 text-xs focus:border-cyan-500 outline-none"
                        />
                        <input
                          type="text"
                          value={stmt.action}
                          onChange={(e) => updateIfThen(idx, 'action', e.target.value)}
                          placeholder={`THEN action ${idx + 1}...`}
                          className="px-2 py-1.5 rounded bg-white/5 border border-white/10 text-xs focus:border-emerald-500 outline-none"
                        />
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">Priority</label>
                  <select
                    value={newStock.priority}
                    onChange={(e) => setNewStock({ ...newStock, priority: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-amber-500 outline-none"
                  >
                    <option value="primary">Primary</option>
                    <option value="secondary">Secondary</option>
                  </select>
                </div>
              </div>

              <div className="p-4 border-t border-zinc-700 flex justify-end gap-2">
                <button
                  onClick={() => setShowAddStock(false)}
                  className="px-4 py-2 rounded-lg bg-zinc-700 text-white text-sm hover:bg-zinc-600"
                >
                  Cancel
                </button>
                <button
                  onClick={handleAddStock}
                  disabled={!newStock.symbol}
                  className="px-4 py-2 rounded-lg bg-amber-500 text-black text-sm font-medium hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  Add Stock
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default GamePlanTab;
