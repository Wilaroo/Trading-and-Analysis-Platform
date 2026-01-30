import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';
import api from '../utils/api';
import { formatCurrency } from '../utils/tradingUtils';

const QuickTradeModal = ({ ticker, action, onClose, onSuccess }) => {
  const [quantity, setQuantity] = useState(10);
  const [orderType, setOrderType] = useState('MKT');
  const [limitPrice, setLimitPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const quote = ticker?.quote || ticker;
  const price = quote?.price || 0;

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    
    try {
      const orderData = {
        symbol: ticker.symbol,
        action: action,
        quantity: quantity,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? parseFloat(limitPrice) : null
      };
      
      await api.post('/api/ib/order', orderData);
      onSuccess?.();
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to place order');
    }
    setSubmitting(false);
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="bg-[#0A0A0A] border border-white/10 w-full max-w-md rounded-lg p-6"
          onClick={e => e.stopPropagation()}
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-white">
              {action === 'BUY' ? 'Buy' : 'Short'} {ticker?.symbol}
            </h3>
            <button onClick={onClose} className="text-zinc-400 hover:text-white">
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-xs text-zinc-500 uppercase">Quantity</label>
              <div className="flex gap-2 mt-1">
                {[10, 50, 100, 500].map(q => (
                  <button
                    key={q}
                    onClick={() => setQuantity(q)}
                    className={`flex-1 py-2 rounded text-sm ${
                      quantity === q ? 'bg-cyan-500 text-black' : 'bg-zinc-800 text-white hover:bg-zinc-700'
                    }`}
                  >
                    {q}
                  </button>
                ))}
              </div>
              <input
                type="number"
                value={quantity}
                onChange={e => setQuantity(parseInt(e.target.value) || 0)}
                className="w-full mt-2 px-3 py-2 bg-zinc-900 border border-white/10 rounded text-white"
              />
            </div>

            <div>
              <label className="text-xs text-zinc-500 uppercase">Order Type</label>
              <div className="flex gap-2 mt-1">
                {['MKT', 'LMT'].map(type => (
                  <button
                    key={type}
                    onClick={() => setOrderType(type)}
                    className={`flex-1 py-2 rounded text-sm ${
                      orderType === type ? 'bg-cyan-500 text-black' : 'bg-zinc-800 text-white hover:bg-zinc-700'
                    }`}
                  >
                    {type === 'MKT' ? 'Market' : 'Limit'}
                  </button>
                ))}
              </div>
            </div>

            {orderType === 'LMT' && (
              <div>
                <label className="text-xs text-zinc-500 uppercase">Limit Price</label>
                <input
                  type="number"
                  step="0.01"
                  value={limitPrice}
                  onChange={e => setLimitPrice(e.target.value)}
                  placeholder={price.toFixed(2)}
                  className="w-full mt-1 px-3 py-2 bg-zinc-900 border border-white/10 rounded text-white"
                />
              </div>
            )}

            <div className="bg-zinc-900 rounded p-3">
              <div className="flex justify-between text-sm">
                <span className="text-zinc-500">Est. {action === 'BUY' ? 'Cost' : 'Proceeds'}</span>
                <span className="text-white font-mono">
                  {formatCurrency(price * quantity)}
                </span>
              </div>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded p-3 text-red-400 text-sm">
                {error}
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={submitting || quantity <= 0}
              className={`w-full py-3 rounded font-bold text-sm ${
                action === 'BUY' 
                  ? 'bg-green-500 hover:bg-green-400 text-black' 
                  : 'bg-red-500 hover:bg-red-400 text-white'
              } disabled:opacity-50`}
            >
              {submitting ? 'Placing Order...' : `${action === 'BUY' ? 'Buy' : 'Short'} ${quantity} shares`}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

export default QuickTradeModal;
