import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MoreHorizontal,
  X as CloseIcon,
  Plus,
  Bell,
  Loader2,
  CheckCircle2,
  AlertTriangle
} from 'lucide-react';
import api from '../utils/api';

/**
 * QuickActionsMenu - Reusable dropdown for quick actions on any ticker
 * 
 * Actions:
 * - Close Position (if user has position)
 * - Add to Watchlist
 * - Create Price Alert
 * 
 * Usage:
 * <QuickActionsMenu symbol="NVDA" hasPosition={true} onAction={(action) => console.log(action)} />
 */
const QuickActionsMenu = ({ 
  symbol, 
  hasPosition = false, 
  currentPrice = null,
  onAction,
  variant = 'icon', // 'icon' | 'buttons' | 'compact'
  className = ''
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(null);
  const [result, setResult] = useState(null);
  const [alertValue, setAlertValue] = useState('');
  const [showAlertInput, setShowAlertInput] = useState(false);

  const handleClosePosition = async () => {
    setLoading('close');
    setResult(null);
    try {
      const res = await api.post('/api/quick-actions/close-position', { symbol });
      setResult({ success: true, message: res.data.message || `Closed ${symbol} position` });
      onAction?.({ type: 'close', symbol, data: res.data });
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to close position';
      setResult({ success: false, message: msg });
    }
    setLoading(null);
  };

  const handleAddToWatchlist = async () => {
    setLoading('add');
    setResult(null);
    try {
      const res = await api.post('/api/quick-actions/add-to-watchlist', { 
        symbol, 
        source: 'quick_action',
        reason: 'Added via quick action'
      });
      setResult({ success: true, message: res.data.message || `Added ${symbol} to watchlist` });
      onAction?.({ type: 'add', symbol, data: res.data });
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to add to watchlist';
      setResult({ success: false, message: msg });
    }
    setLoading(null);
  };

  const handleCreateAlert = async () => {
    if (!alertValue) {
      setShowAlertInput(true);
      return;
    }

    setLoading('alert');
    setResult(null);
    try {
      const targetPrice = parseFloat(alertValue);
      const condition = currentPrice && targetPrice > currentPrice ? 'above' : 'below';
      
      const res = await api.post('/api/quick-actions/create-alert', {
        symbol,
        alert_type: 'price',
        condition,
        value: targetPrice,
        note: `Quick alert from ${currentPrice ? `$${currentPrice.toFixed(2)}` : 'current price'}`
      });
      setResult({ success: true, message: res.data.description || `Alert created for ${symbol}` });
      onAction?.({ type: 'alert', symbol, data: res.data });
      setShowAlertInput(false);
      setAlertValue('');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to create alert';
      setResult({ success: false, message: msg });
    }
    setLoading(null);
  };

  // Clear result after 3 seconds
  React.useEffect(() => {
    if (result) {
      const timer = setTimeout(() => setResult(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [result]);

  // Variant: Inline buttons (for modal footer, etc.)
  if (variant === 'buttons') {
    return (
      <div className={`flex items-center gap-2 ${className}`} data-testid={`quick-actions-${symbol}`}>
        {hasPosition && (
          <button
            onClick={handleClosePosition}
            disabled={loading === 'close'}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors disabled:opacity-50"
            data-testid="quick-action-close"
          >
            {loading === 'close' ? <Loader2 className="w-3 h-3 animate-spin" /> : <CloseIcon className="w-3 h-3" />}
            Close
          </button>
        )}
        <button
          onClick={handleAddToWatchlist}
          disabled={loading === 'add'}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-cyan-500/20 text-cyan-400 rounded-lg hover:bg-cyan-500/30 transition-colors disabled:opacity-50"
          data-testid="quick-action-add"
        >
          {loading === 'add' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
          Add
        </button>
        <button
          onClick={handleCreateAlert}
          disabled={loading === 'alert'}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-yellow-500/20 text-yellow-400 rounded-lg hover:bg-yellow-500/30 transition-colors disabled:opacity-50"
          data-testid="quick-action-alert"
        >
          {loading === 'alert' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bell className="w-3 h-3" />}
          Alert
        </button>
        {result && (
          <span className={`text-xs ${result.success ? 'text-green-400' : 'text-red-400'}`}>
            {result.message}
          </span>
        )}
      </div>
    );
  }

  // Variant: Compact (small inline text buttons)
  if (variant === 'compact') {
    return (
      <div className={`flex items-center gap-1 text-[12px] ${className}`} data-testid={`quick-actions-${symbol}`}>
        {hasPosition && (
          <button
            onClick={handleClosePosition}
            disabled={loading === 'close'}
            className="text-red-400 hover:text-red-300 hover:underline disabled:opacity-50"
            data-testid="quick-action-close"
          >
            {loading === 'close' ? '...' : 'close'}
          </button>
        )}
        <button
          onClick={handleAddToWatchlist}
          disabled={loading === 'add'}
          className="text-cyan-400 hover:text-cyan-300 hover:underline disabled:opacity-50"
          data-testid="quick-action-add"
        >
          {loading === 'add' ? '...' : 'add'}
        </button>
        <button
          onClick={handleCreateAlert}
          disabled={loading === 'alert'}
          className="text-yellow-400 hover:text-yellow-300 hover:underline disabled:opacity-50"
          data-testid="quick-action-alert"
        >
          {loading === 'alert' ? '...' : 'alert'}
        </button>
      </div>
    );
  }

  // Default: Icon dropdown
  return (
    <div className={`relative ${className}`} data-testid={`quick-actions-${symbol}`}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="p-1.5 rounded-md hover:bg-white/10 transition-colors"
        data-testid="quick-actions-trigger"
      >
        <MoreHorizontal className="w-4 h-4 text-zinc-400" />
      </button>

      <AnimatePresence>
        {isOpen && (
          <>
            {/* Backdrop */}
            <div 
              className="fixed inset-0 z-40" 
              onClick={() => {
                setIsOpen(false);
                setShowAlertInput(false);
              }} 
            />
            
            {/* Dropdown */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: -10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -10 }}
              className="absolute right-0 top-full mt-1 z-50 w-48 bg-zinc-800 rounded-lg border border-zinc-700 shadow-xl overflow-hidden"
            >
              <div className="p-2 border-b border-zinc-700">
                <span className="text-xs font-semibold text-zinc-400">{symbol} Quick Actions</span>
              </div>

              <div className="p-1">
                {hasPosition && (
                  <button
                    onClick={handleClosePosition}
                    disabled={loading === 'close'}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-400 hover:bg-red-500/10 rounded-md transition-colors disabled:opacity-50"
                    data-testid="quick-action-close"
                  >
                    {loading === 'close' ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <CloseIcon className="w-4 h-4" />
                    )}
                    Close Position
                  </button>
                )}

                <button
                  onClick={handleAddToWatchlist}
                  disabled={loading === 'add'}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-cyan-400 hover:bg-cyan-500/10 rounded-md transition-colors disabled:opacity-50"
                  data-testid="quick-action-add"
                >
                  {loading === 'add' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Plus className="w-4 h-4" />
                  )}
                  Add to Watchlist
                </button>

                {showAlertInput ? (
                  <div className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        placeholder="Price"
                        value={alertValue}
                        onChange={(e) => setAlertValue(e.target.value)}
                        className="w-20 px-2 py-1 text-xs bg-zinc-700 border border-zinc-600 rounded text-white"
                        autoFocus
                        data-testid="alert-price-input"
                      />
                      <button
                        onClick={handleCreateAlert}
                        disabled={loading === 'alert' || !alertValue}
                        className="px-2 py-1 text-xs bg-yellow-500/20 text-yellow-400 rounded hover:bg-yellow-500/30 disabled:opacity-50"
                      >
                        {loading === 'alert' ? '...' : 'Set'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowAlertInput(true)}
                    disabled={loading === 'alert'}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-yellow-400 hover:bg-yellow-500/10 rounded-md transition-colors disabled:opacity-50"
                    data-testid="quick-action-alert"
                  >
                    {loading === 'alert' ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Bell className="w-4 h-4" />
                    )}
                    Create Alert
                  </button>
                )}
              </div>

              {result && (
                <div className={`px-3 py-2 text-xs border-t border-zinc-700 ${
                  result.success ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                }`}>
                  <div className="flex items-center gap-1">
                    {result.success ? (
                      <CheckCircle2 className="w-3 h-3" />
                    ) : (
                      <AlertTriangle className="w-3 h-3" />
                    )}
                    {result.message}
                  </div>
                </div>
              )}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
};

export default QuickActionsMenu;
