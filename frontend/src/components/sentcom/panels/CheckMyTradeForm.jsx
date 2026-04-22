import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Target, X } from 'lucide-react';
import { toast } from 'sonner';

// ============================================================================
// Utilities, TypingIndicator, HoverTimestamp, StreamMessage, Sparkline,
// GlassCard, PulsingDot — extracted to ./sentcom/{utils,primitives}/*
// ============================================================================

// Check My Trade Form
export const CheckMyTradeForm = ({ onSubmit, loading, onClose }) => {
  const [symbol, setSymbol] = useState('');
  const [action, setAction] = useState('BUY');
  const [entryPrice, setEntryPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!symbol.trim()) {
      toast.error('Enter a symbol');
      return;
    }
    if (!entryPrice || !stopLoss) {
      toast.error('Enter entry and stop prices for full analysis');
      return;
    }
    onSubmit({
      symbol: symbol.toUpperCase(),
      action,
      entry_price: parseFloat(entryPrice),
      stop_loss: parseFloat(stopLoss)
    });
    // Clear form after submit
    setSymbol('');
    setEntryPrice('');
    setStopLoss('');
    onClose?.();
  };

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="bg-black/40 rounded-xl p-4 border border-white/10 mb-4"
    >
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-medium text-white flex items-center gap-2">
          <Target className="w-4 h-4 text-cyan-400" />
          Check Our Trade
        </h4>
        <button onClick={onClose} className="p-1 hover:bg-white/10 rounded">
          <X className="w-4 h-4 text-zinc-400" />
        </button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="Symbol"
            className="flex-1 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
            data-testid="check-trade-symbol"
          />
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>
        <div className="flex gap-2">
          <input
            type="number"
            step="0.01"
            value={entryPrice}
            onChange={(e) => setEntryPrice(e.target.value)}
            placeholder="Entry $"
            className="flex-1 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          />
          <input
            type="number"
            step="0.01"
            value={stopLoss}
            onChange={(e) => setStopLoss(e.target.value)}
            placeholder="Stop $"
            className="flex-1 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full px-4 py-2 bg-gradient-to-r from-cyan-500 to-violet-500 rounded-lg text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {loading ? 'Checking...' : 'Check This Trade'}
        </button>
      </form>
    </motion.div>
  );
};
