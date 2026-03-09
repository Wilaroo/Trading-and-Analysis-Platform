import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BookOpen, Plus, X, Save, Edit3, Trash2, ChevronDown, ChevronRight,
  Target, TrendingUp, TrendingDown, AlertCircle, Check, Star,
  Zap, Activity, BarChart3, Clock, DollarSign, Percent, Award
} from 'lucide-react';
import api from '../../utils/api';

// SMB Playbook Component
const PlaybookTab = ({ onSelectPlaybook }) => {
  const [playbooks, setPlaybooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [selectedPlaybook, setSelectedPlaybook] = useState(null);
  const [summary, setSummary] = useState(null);
  const [expandedPlaybook, setExpandedPlaybook] = useState(null);

  // Form state for new playbook
  const [formData, setFormData] = useState({
    name: '',
    setup_type: '',
    description: '',
    market_context: '',
    catalyst_type: 'Technical Setup Only',
    trade_style: 'M2M',
    if_then_statements: [
      { condition: '', action: '', notes: '' },
      { condition: '', action: '', notes: '' },
      { condition: '', action: '', notes: '' }
    ],
    entry_rules: { trigger: '', confirmation: '', timing: '', notes: '' },
    exit_rules: { target_1: '', target_2: '', target_3: '', scaling_rules: '', trail_stop: '', notes: '' },
    stop_rules: { initial_stop: '', break_even_rule: '', time_stop: '', notes: '' },
    risk_reward_target: 2.0,
    max_risk_percent: 1.0,
    best_time_of_day: '',
    notes: '',
    tags: []
  });

  const loadPlaybooks = useCallback(async () => {
    try {
      setLoading(true);
      const [playbooksRes, summaryRes] = await Promise.all([
        api.get('/api/journal/playbooks'),
        api.get('/api/journal/playbooks/summary')
      ]);
      setPlaybooks(playbooksRes.data.playbooks || []);
      setSummary(summaryRes.data);
    } catch (err) {
      console.error('Failed to load playbooks:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPlaybooks();
  }, [loadPlaybooks]);

  const handleCreatePlaybook = async () => {
    try {
      const res = await api.post('/api/journal/playbooks', formData);
      if (res.data.success) {
        setPlaybooks([res.data.playbook, ...playbooks]);
        setShowCreateForm(false);
        setFormData({
          name: '', setup_type: '', description: '', market_context: '',
          catalyst_type: 'Technical Setup Only', trade_style: 'M2M',
          if_then_statements: [
            { condition: '', action: '', notes: '' },
            { condition: '', action: '', notes: '' },
            { condition: '', action: '', notes: '' }
          ],
          entry_rules: { trigger: '', confirmation: '', timing: '', notes: '' },
          exit_rules: { target_1: '', target_2: '', target_3: '', scaling_rules: '', trail_stop: '', notes: '' },
          stop_rules: { initial_stop: '', break_even_rule: '', time_stop: '', notes: '' },
          risk_reward_target: 2.0, max_risk_percent: 1.0, best_time_of_day: '', notes: '', tags: []
        });
      }
    } catch (err) {
      console.error('Failed to create playbook:', err);
    }
  };

  const updateIfThen = (index, field, value) => {
    const updated = [...formData.if_then_statements];
    updated[index] = { ...updated[index], [field]: value };
    setFormData({ ...formData, if_then_statements: updated });
  };

  const getTradeStyleColor = (style) => {
    switch (style) {
      case 'A+': return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
      case 'T2H': return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
      case 'M2M': return 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30';
      default: return 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="playbook-tab">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-cyan-400" />
            My Playbooks
          </h2>
          <p className="text-xs text-zinc-500">Document repeatable trade setups with IF/THEN rules</p>
        </div>
        <button
          onClick={() => setShowCreateForm(true)}
          className="px-3 py-1.5 rounded-lg bg-cyan-500 text-black text-sm font-medium hover:bg-cyan-400 transition-colors flex items-center gap-1"
          data-testid="create-playbook-btn"
        >
          <Plus className="w-4 h-4" />
          New Playbook
        </button>
      </div>

      {/* Summary Stats */}
      {summary && (
        <div className="grid grid-cols-4 gap-3">
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <p className="text-xs text-zinc-500">Total Playbooks</p>
            <p className="text-xl font-bold text-white">{summary.total_playbooks}</p>
          </div>
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <p className="text-xs text-zinc-500">Total Trades</p>
            <p className="text-xl font-bold text-white">{summary.total_trades}</p>
          </div>
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <p className="text-xs text-zinc-500">Total P&L</p>
            <p className={`text-xl font-bold ${summary.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              ${summary.total_pnl?.toFixed(0) || 0}
            </p>
          </div>
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <p className="text-xs text-zinc-500">Trade Styles</p>
            <div className="flex gap-1 mt-1">
              {Object.entries(summary.by_trade_style || {}).slice(0, 3).map(([style, data]) => (
                <span key={style} className={`text-[9px] px-1.5 py-0.5 rounded ${getTradeStyleColor(style)}`}>
                  {style}: {data.count}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Playbooks List */}
      <div className="space-y-2 max-h-[600px] overflow-y-auto">
        {playbooks.length === 0 ? (
          <div className="text-center py-12 text-zinc-500">
            <BookOpen className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No playbooks yet. Create your first one!</p>
            <p className="text-xs mt-1">Document your best trade setups with clear IF/THEN rules</p>
          </div>
        ) : (
          playbooks.map((pb) => (
            <motion.div
              key={pb.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="p-3 rounded-lg bg-white/5 border border-white/10 hover:border-cyan-500/30 transition-all cursor-pointer"
              onClick={() => setExpandedPlaybook(expandedPlaybook === pb.id ? null : pb.id)}
            >
              {/* Playbook Header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ChevronRight className={`w-4 h-4 text-zinc-500 transition-transform ${expandedPlaybook === pb.id ? 'rotate-90' : ''}`} />
                  <span className="font-medium text-white">{pb.name}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border ${getTradeStyleColor(pb.trade_style)}`}>
                    {pb.trade_style}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-zinc-500">{pb.total_trades} trades</span>
                  <span className={pb.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}>
                    {pb.win_rate}% win
                  </span>
                  <span className={pb.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                    ${pb.total_pnl?.toFixed(0) || 0}
                  </span>
                </div>
              </div>

              {/* Expanded Content */}
              <AnimatePresence>
                {expandedPlaybook === pb.id && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="mt-3 pt-3 border-t border-white/10"
                  >
                    <div className="grid grid-cols-2 gap-4">
                      {/* Left Column */}
                      <div className="space-y-3">
                        <div>
                          <p className="text-[10px] text-zinc-500 uppercase mb-1">Setup Type</p>
                          <p className="text-sm text-white">{pb.setup_type}</p>
                        </div>
                        <div>
                          <p className="text-[10px] text-zinc-500 uppercase mb-1">Market Context</p>
                          <p className="text-sm text-white">{pb.market_context || 'Any'}</p>
                        </div>
                        <div>
                          <p className="text-[10px] text-zinc-500 uppercase mb-1">Catalyst</p>
                          <p className="text-sm text-white">{pb.catalyst_type}</p>
                        </div>
                        <div>
                          <p className="text-[10px] text-zinc-500 uppercase mb-1">Risk/Reward Target</p>
                          <p className="text-sm text-white">{pb.risk_reward_target}R</p>
                        </div>
                      </div>

                      {/* Right Column - IF/THEN Statements */}
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase mb-2">IF/THEN Rules</p>
                        <div className="space-y-2">
                          {pb.if_then_statements?.map((stmt, idx) => (
                            stmt.condition && (
                              <div key={idx} className="p-2 rounded bg-black/30 text-xs">
                                <p className="text-cyan-400">IF: {stmt.condition}</p>
                                <p className="text-emerald-400">THEN: {stmt.action}</p>
                                {stmt.notes && <p className="text-zinc-500 mt-1">{stmt.notes}</p>}
                              </div>
                            )
                          ))}
                        </div>
                      </div>
                    </div>

                    {/* Description */}
                    {pb.description && (
                      <div className="mt-3">
                        <p className="text-[10px] text-zinc-500 uppercase mb-1">Description</p>
                        <p className="text-xs text-zinc-300">{pb.description}</p>
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          ))
        )}
      </div>

      {/* Create Playbook Modal */}
      <AnimatePresence>
        {showCreateForm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4"
            onClick={() => setShowCreateForm(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-zinc-900 rounded-xl border border-zinc-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-4 border-b border-zinc-700 flex items-center justify-between">
                <h3 className="text-lg font-semibold">Create New Playbook</h3>
                <button onClick={() => setShowCreateForm(false)} className="text-zinc-400 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="p-4 space-y-4">
                {/* Basic Info */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Playbook Name *</label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      placeholder="e.g., NVDA Earnings Gap Play"
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-cyan-500 outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Setup Type *</label>
                    <select
                      value={formData.setup_type}
                      onChange={(e) => setFormData({ ...formData, setup_type: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-cyan-500 outline-none"
                    >
                      <option value="">Select setup type...</option>
                      {summary?.setup_types?.map((type) => (
                        <option key={type} value={type}>{type}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Trade Style</label>
                    <select
                      value={formData.trade_style}
                      onChange={(e) => setFormData({ ...formData, trade_style: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-cyan-500 outline-none"
                    >
                      {summary?.trade_styles?.map((style) => (
                        <option key={style} value={style}>{style}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Catalyst Type</label>
                    <select
                      value={formData.catalyst_type}
                      onChange={(e) => setFormData({ ...formData, catalyst_type: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-cyan-500 outline-none"
                    >
                      {summary?.catalyst_types?.map((type) => (
                        <option key={type} value={type}>{type}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Market Context</label>
                    <select
                      value={formData.market_context}
                      onChange={(e) => setFormData({ ...formData, market_context: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-cyan-500 outline-none"
                    >
                      <option value="">Any context...</option>
                      {summary?.market_contexts?.map((ctx) => (
                        <option key={ctx} value={ctx}>{ctx}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">Description</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    placeholder="Describe this setup and when it works best..."
                    rows={2}
                    className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-cyan-500 outline-none resize-none"
                  />
                </div>

                {/* IF/THEN Statements */}
                <div>
                  <label className="text-xs text-zinc-500 mb-2 block">IF/THEN Statements (3 Rules)</label>
                  <div className="space-y-2">
                    {formData.if_then_statements.map((stmt, idx) => (
                      <div key={idx} className="p-3 rounded-lg bg-black/30 border border-white/5">
                        <div className="grid grid-cols-2 gap-2">
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
                        <input
                          type="text"
                          value={stmt.notes}
                          onChange={(e) => updateIfThen(idx, 'notes', e.target.value)}
                          placeholder="Notes (optional)"
                          className="w-full mt-1 px-2 py-1 rounded bg-white/5 border border-white/10 text-xs text-zinc-500 focus:border-white/30 outline-none"
                        />
                      </div>
                    ))}
                  </div>
                </div>

                {/* Risk Parameters */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Target R:R</label>
                    <input
                      type="number"
                      step="0.1"
                      value={formData.risk_reward_target}
                      onChange={(e) => setFormData({ ...formData, risk_reward_target: parseFloat(e.target.value) })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-cyan-500 outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Max Risk %</label>
                    <input
                      type="number"
                      step="0.1"
                      value={formData.max_risk_percent}
                      onChange={(e) => setFormData({ ...formData, max_risk_percent: parseFloat(e.target.value) })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:border-cyan-500 outline-none"
                    />
                  </div>
                </div>
              </div>

              <div className="p-4 border-t border-zinc-700 flex justify-end gap-2">
                <button
                  onClick={() => setShowCreateForm(false)}
                  className="px-4 py-2 rounded-lg bg-zinc-700 text-white text-sm hover:bg-zinc-600"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreatePlaybook}
                  disabled={!formData.name || !formData.setup_type}
                  className="px-4 py-2 rounded-lg bg-cyan-500 text-black text-sm font-medium hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  <Save className="w-4 h-4" />
                  Create Playbook
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default PlaybookTab;
