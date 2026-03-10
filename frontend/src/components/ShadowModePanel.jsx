import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Layers,
  Plus,
  Play,
  Pause,
  CheckCircle,
  XCircle,
  Clock,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Filter,
  AlertTriangle,
  Target,
  Eye,
  EyeOff
} from 'lucide-react';
import api from '../utils/api';

// Card component
const Card = ({ children, className = '' }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${className}`}>
    {children}
  </div>
);

// Filter Card
const FilterCard = ({ filter, onValidate, onDeactivate }) => {
  const [validating, setValidating] = useState(false);
  
  const handleValidate = async () => {
    setValidating(true);
    try {
      await onValidate(filter.id);
    } finally {
      setValidating(false);
    }
  };
  
  const totalSignals = filter.signals_won + filter.signals_lost;
  
  return (
    <div className={`p-4 rounded-lg border ${
      filter.is_validated 
        ? 'bg-green-500/5 border-green-500/20' 
        : 'bg-white/5 border-white/10'
    }`}>
      <div className="flex items-center justify-between mb-2">
        <h4 className="font-medium">{filter.name}</h4>
        <div className="flex items-center gap-2">
          {filter.is_validated && (
            <span className="text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded">
              Validated
            </span>
          )}
          <span className={`text-xs px-2 py-0.5 rounded ${
            filter.is_active ? 'bg-primary/20 text-primary' : 'bg-zinc-500/20 text-zinc-400'
          }`}>
            {filter.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
      </div>
      
      <p className="text-sm text-zinc-400 mb-3">{filter.description}</p>
      
      <div className="grid grid-cols-3 gap-3 mb-3">
        <div className="text-center">
          <p className="text-lg font-bold">{totalSignals}</p>
          <p className="text-xs text-zinc-500">Signals</p>
        </div>
        <div className="text-center">
          <p className={`text-lg font-bold ${filter.win_rate >= 0.5 ? 'text-green-400' : 'text-red-400'}`}>
            {(filter.win_rate * 100).toFixed(0)}%
          </p>
          <p className="text-xs text-zinc-500">Win Rate</p>
        </div>
        <div className="text-center">
          <p className={`text-lg font-bold ${filter.total_r >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {filter.total_r?.toFixed(1)}R
          </p>
          <p className="text-xs text-zinc-500">Total R</p>
        </div>
      </div>
      
      <div className="flex gap-2">
        <button
          onClick={handleValidate}
          disabled={validating || totalSignals < 20}
          className="flex-1 btn-secondary text-sm py-1.5 flex items-center justify-center gap-1"
        >
          {validating ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <CheckCircle className="w-4 h-4" />
          )}
          Validate
        </button>
        <button
          onClick={() => onDeactivate(filter.id)}
          className="px-3 py-1.5 text-sm bg-red-500/10 text-red-400 rounded hover:bg-red-500/20"
        >
          <XCircle className="w-4 h-4" />
        </button>
      </div>
      
      {filter.validation_notes && (
        <p className="text-xs text-zinc-500 mt-2">{filter.validation_notes}</p>
      )}
    </div>
  );
};

// Signal Row
const SignalRow = ({ signal }) => {
  const statusColors = {
    pending: 'text-yellow-400 bg-yellow-500/10',
    won: 'text-green-400 bg-green-500/10',
    lost: 'text-red-400 bg-red-500/10',
    expired: 'text-zinc-400 bg-zinc-500/10'
  };
  
  const StatusIcon = {
    pending: Clock,
    won: TrendingUp,
    lost: TrendingDown,
    expired: XCircle
  }[signal.status] || Clock;
  
  return (
    <div className={`p-3 rounded-lg ${statusColors[signal.status] || statusColors.pending}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <StatusIcon className="w-4 h-4" />
          <span className="font-medium">{signal.symbol}</span>
          <span className="text-sm">{signal.setup_type}</span>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {signal.status !== 'pending' && (
            <span className={signal.would_have_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
              ${signal.would_have_pnl?.toFixed(0) || 0} ({signal.would_have_r?.toFixed(1) || 0}R)
            </span>
          )}
          <span className="text-zinc-500 uppercase text-xs">{signal.status}</span>
        </div>
      </div>
      <div className="text-xs text-zinc-500 mt-1">
        Entry: ${signal.signal_price?.toFixed(2)} | 
        Stop: ${signal.stop_price?.toFixed(2)} | 
        Target: ${signal.target_price?.toFixed(2)}
      </div>
    </div>
  );
};

// New Filter Form
const NewFilterForm = ({ onSubmit, onCancel }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [filterType, setFilterType] = useState('entry');
  const [submitting, setSubmitting] = useState(false);
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    
    setSubmitting(true);
    try {
      await onSubmit({
        name,
        description,
        filter_type: filterType,
        criteria: {}
      });
      setName('');
      setDescription('');
    } finally {
      setSubmitting(false);
    }
  };
  
  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4 bg-white/5 rounded-lg border border-white/10">
      <h4 className="font-medium">Create New Filter</h4>
      
      <div>
        <label className="text-xs text-zinc-400 block mb-1">Filter Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
          placeholder="e.g., High TQS Only"
          required
        />
      </div>
      
      <div>
        <label className="text-xs text-zinc-400 block mb-1">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none resize-none"
          rows={2}
          placeholder="What does this filter test?"
        />
      </div>
      
      <div>
        <label className="text-xs text-zinc-400 block mb-1">Filter Type</label>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
        >
          <option value="entry">Entry Filter</option>
          <option value="exit">Exit Filter</option>
          <option value="position_size">Position Size</option>
          <option value="risk">Risk Filter</option>
        </select>
      </div>
      
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="flex-1 btn-primary text-sm"
        >
          {submitting ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Create Filter'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 text-sm bg-white/5 rounded hover:bg-white/10"
        >
          Cancel
        </button>
      </div>
    </form>
  );
};

// New Signal Form
const NewSignalForm = ({ filters, onSubmit, onCancel }) => {
  const [signal, setSignal] = useState({
    symbol: '',
    direction: 'long',
    setup_type: '',
    signal_price: 0,
    stop_price: 0,
    target_price: 0,
    filter_id: '',
    tqs_score: 0
  });
  const [submitting, setSubmitting] = useState(false);
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit(signal);
      onCancel();
    } finally {
      setSubmitting(false);
    }
  };
  
  const updateSignal = (key, value) => {
    setSignal(prev => ({ ...prev, [key]: value }));
  };
  
  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4 bg-white/5 rounded-lg border border-white/10">
      <h4 className="font-medium">Record Shadow Signal</h4>
      
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-zinc-400 block mb-1">Symbol</label>
          <input
            type="text"
            value={signal.symbol}
            onChange={(e) => updateSignal('symbol', e.target.value.toUpperCase())}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none uppercase"
            placeholder="AAPL"
            required
          />
        </div>
        <div>
          <label className="text-xs text-zinc-400 block mb-1">Setup Type</label>
          <input
            type="text"
            value={signal.setup_type}
            onChange={(e) => updateSignal('setup_type', e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
            placeholder="bull_flag"
            required
          />
        </div>
      </div>
      
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-zinc-400 block mb-1">Entry Price</label>
          <input
            type="number"
            step="0.01"
            value={signal.signal_price}
            onChange={(e) => updateSignal('signal_price', parseFloat(e.target.value))}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
            required
          />
        </div>
        <div>
          <label className="text-xs text-zinc-400 block mb-1">Stop Price</label>
          <input
            type="number"
            step="0.01"
            value={signal.stop_price}
            onChange={(e) => updateSignal('stop_price', parseFloat(e.target.value))}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
            required
          />
        </div>
        <div>
          <label className="text-xs text-zinc-400 block mb-1">Target Price</label>
          <input
            type="number"
            step="0.01"
            value={signal.target_price}
            onChange={(e) => updateSignal('target_price', parseFloat(e.target.value))}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
            required
          />
        </div>
      </div>
      
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-zinc-400 block mb-1">Filter (Optional)</label>
          <select
            value={signal.filter_id}
            onChange={(e) => updateSignal('filter_id', e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
          >
            <option value="">No Filter</option>
            {filters.map(f => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-400 block mb-1">TQS Score</label>
          <input
            type="number"
            min="0"
            max="100"
            value={signal.tqs_score}
            onChange={(e) => updateSignal('tqs_score', parseFloat(e.target.value))}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
          />
        </div>
      </div>
      
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting || !signal.symbol}
          className="flex-1 btn-primary text-sm"
        >
          {submitting ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Record Signal'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 text-sm bg-white/5 rounded hover:bg-white/10"
        >
          Cancel
        </button>
      </div>
    </form>
  );
};

const ShadowModePanel = () => {
  const [filters, setFilters] = useState([]);
  const [signals, setSignals] = useState([]);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showNewFilter, setShowNewFilter] = useState(false);
  const [showNewSignal, setShowNewSignal] = useState(false);
  const [showSignals, setShowSignals] = useState(true);
  
  // Load data
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [filtersRes, signalsRes, reportRes] = await Promise.all([
        api.get('/api/slow-learning/shadow/filters'),
        api.get('/api/slow-learning/shadow/signals?limit=20'),
        api.get('/api/slow-learning/shadow/report?days=30')
      ]);
      
      if (filtersRes.data.success) setFilters(filtersRes.data.filters || []);
      if (signalsRes.data.success) setSignals(signalsRes.data.signals || []);
      if (reportRes.data.success) setReport(reportRes.data.report);
    } catch (err) {
      console.error('Error loading shadow mode data:', err);
    } finally {
      setLoading(false);
    }
  }, []);
  
  useEffect(() => {
    loadData();
  }, [loadData]);
  
  // Create filter
  const createFilter = async (filterData) => {
    try {
      const res = await api.post('/api/slow-learning/shadow/filters', filterData);
      if (res.data.success) {
        setShowNewFilter(false);
        loadData();
      }
    } catch (err) {
      console.error('Error creating filter:', err);
    }
  };
  
  // Validate filter
  const validateFilter = async (filterId) => {
    try {
      await api.post(`/api/slow-learning/shadow/filters/${filterId}/validate`);
      loadData();
    } catch (err) {
      console.error('Error validating filter:', err);
    }
  };
  
  // Deactivate filter
  const deactivateFilter = async (filterId) => {
    try {
      await api.post(`/api/slow-learning/shadow/filters/${filterId}/deactivate`);
      loadData();
    } catch (err) {
      console.error('Error deactivating filter:', err);
    }
  };
  
  // Record signal
  const recordSignal = async (signalData) => {
    try {
      await api.post('/api/slow-learning/shadow/signals', signalData);
      loadData();
    } catch (err) {
      console.error('Error recording signal:', err);
    }
  };
  
  // Update outcomes
  const updateOutcomes = async () => {
    try {
      await api.post('/api/slow-learning/shadow/update-outcomes');
      loadData();
    } catch (err) {
      console.error('Error updating outcomes:', err);
    }
  };
  
  if (loading && !report) {
    return (
      <Card>
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-8 h-8 text-primary animate-spin" />
        </div>
      </Card>
    );
  }
  
  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-purple-400" />
          <h3 className="font-semibold">Shadow Mode</h3>
          <span className="text-xs bg-purple-500/20 text-purple-400 px-2 py-0.5 rounded">
            Paper Trading
          </span>
        </div>
        <div className="flex gap-2">
          <button
            onClick={updateOutcomes}
            className="btn-secondary text-sm flex items-center gap-1"
          >
            <RefreshCw className="w-4 h-4" />
            Update
          </button>
        </div>
      </div>
      
      {/* Summary Stats */}
      {report && (
        <div className="grid grid-cols-4 gap-3 mb-4">
          <div className="bg-white/5 rounded-lg p-3 text-center">
            <p className="text-xl font-bold">{report.total_signals}</p>
            <p className="text-xs text-zinc-500">Total Signals</p>
          </div>
          <div className="bg-white/5 rounded-lg p-3 text-center">
            <p className="text-xl font-bold text-yellow-400">{report.signals_pending}</p>
            <p className="text-xs text-zinc-500">Pending</p>
          </div>
          <div className="bg-white/5 rounded-lg p-3 text-center">
            <p className={`text-xl font-bold ${report.overall_win_rate >= 0.5 ? 'text-green-400' : 'text-red-400'}`}>
              {(report.overall_win_rate * 100).toFixed(0)}%
            </p>
            <p className="text-xs text-zinc-500">Win Rate</p>
          </div>
          <div className="bg-white/5 rounded-lg p-3 text-center">
            <p className={`text-xl font-bold ${report.total_r >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {report.total_r?.toFixed(1)}R
            </p>
            <p className="text-xs text-zinc-500">Total R</p>
          </div>
        </div>
      )}
      
      {/* Filters Section */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h4 className="font-medium flex items-center gap-2">
            <Filter className="w-4 h-4" />
            Filters ({filters.length})
          </h4>
          <button
            onClick={() => setShowNewFilter(!showNewFilter)}
            className="text-sm text-primary hover:text-primary/80 flex items-center gap-1"
          >
            <Plus className="w-4 h-4" />
            New Filter
          </button>
        </div>
        
        <AnimatePresence>
          {showNewFilter && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden mb-4"
            >
              <NewFilterForm
                onSubmit={createFilter}
                onCancel={() => setShowNewFilter(false)}
              />
            </motion.div>
          )}
        </AnimatePresence>
        
        {filters.length > 0 ? (
          <div className="grid md:grid-cols-2 gap-3">
            {filters.map(filter => (
              <FilterCard
                key={filter.id}
                filter={filter}
                onValidate={validateFilter}
                onDeactivate={deactivateFilter}
              />
            ))}
          </div>
        ) : (
          <p className="text-center text-zinc-500 py-6">
            No filters yet. Create one to start testing!
          </p>
        )}
      </div>
      
      {/* Signals Section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <button
            onClick={() => setShowSignals(!showSignals)}
            className="font-medium flex items-center gap-2 hover:text-primary"
          >
            {showSignals ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            Recent Signals ({signals.length})
          </button>
          <button
            onClick={() => setShowNewSignal(!showNewSignal)}
            className="text-sm text-primary hover:text-primary/80 flex items-center gap-1"
          >
            <Plus className="w-4 h-4" />
            Record Signal
          </button>
        </div>
        
        <AnimatePresence>
          {showNewSignal && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden mb-4"
            >
              <NewSignalForm
                filters={filters}
                onSubmit={recordSignal}
                onCancel={() => setShowNewSignal(false)}
              />
            </motion.div>
          )}
        </AnimatePresence>
        
        {showSignals && signals.length > 0 && (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {signals.map(signal => (
              <SignalRow key={signal.id} signal={signal} />
            ))}
          </div>
        )}
        
        {showSignals && signals.length === 0 && (
          <p className="text-center text-zinc-500 py-6">
            No signals yet. Record your first shadow trade!
          </p>
        )}
      </div>
      
      {/* Recommendations */}
      {report && (report.filters_to_activate?.length > 0 || report.filters_to_deactivate?.length > 0) && (
        <div className="mt-6 p-4 bg-white/5 rounded-lg border border-white/10">
          <h4 className="font-medium mb-3 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-yellow-400" />
            Recommendations
          </h4>
          {report.filters_to_activate?.length > 0 && (
            <div className="mb-2">
              <span className="text-green-400 text-sm">Ready to Activate:</span>
              <span className="text-sm ml-2">{report.filters_to_activate.join(', ')}</span>
            </div>
          )}
          {report.filters_to_deactivate?.length > 0 && (
            <div>
              <span className="text-red-400 text-sm">Consider Removing:</span>
              <span className="text-sm ml-2">{report.filters_to_deactivate.join(', ')}</span>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};

export default ShadowModePanel;
