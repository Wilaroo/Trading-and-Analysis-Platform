import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { 
  Link2, Link2Off, RefreshCw, TrendingUp, TrendingDown, 
  DollarSign, Briefcase, ShoppingCart, X, AlertCircle,
  Play, Square, Activity, Clock, CheckCircle, XCircle
} from 'lucide-react';
import api from '../utils/api';

// ===================== IB CONNECTION STATUS =====================
const ConnectionStatus = ({ status, onConnect, onDisconnect, loading }) => {
  const isConnected = status?.connected;
  
  return (
    <div className="bg-paper border border-white/10 rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          {isConnected ? <Link2 className="w-5 h-5 text-green-400" /> : <Link2Off className="w-5 h-5 text-zinc-500" />}
          IB Gateway Connection
        </h2>
        <div className={`px-3 py-1 rounded-full text-sm font-medium ${
          isConnected ? 'bg-green-500/20 text-green-400' : 'bg-zinc-700/50 text-zinc-400'
        }`}>
          {isConnected ? 'Connected' : 'Disconnected'}
        </div>
      </div>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div className="bg-zinc-800/50 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">Host</div>
          <div className="text-sm text-white font-mono">{status?.host || '127.0.0.1'}</div>
        </div>
        <div className="bg-zinc-800/50 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">Port</div>
          <div className="text-sm text-white font-mono">{status?.port || '4002'}</div>
        </div>
        <div className="bg-zinc-800/50 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">Client ID</div>
          <div className="text-sm text-white font-mono">{status?.client_id || '1'}</div>
        </div>
        <div className="bg-zinc-800/50 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">Account</div>
          <div className="text-sm text-white font-mono">{status?.account_id || 'N/A'}</div>
        </div>
      </div>
      
      <div className="flex gap-3">
        {!isConnected ? (
          <button
            onClick={onConnect}
            disabled={loading}
            data-testid="ib-connect-btn"
            className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Connect to IB Gateway
          </button>
        ) : (
          <button
            onClick={onDisconnect}
            disabled={loading}
            data-testid="ib-disconnect-btn"
            className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
            Disconnect
          </button>
        )}
      </div>
      
      {!isConnected && (
        <div className="mt-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <div className="flex items-start gap-2 text-amber-400 text-sm">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <div>
              <strong>Make sure IB Gateway is running</strong>
              <p className="text-amber-400/70 text-xs mt-1">
                Open IB Gateway, login to your paper account (DUN615665), and ensure API connections are enabled on port 4002.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ===================== ACCOUNT SUMMARY =====================
const AccountSummary = ({ summary, loading }) => {
  if (loading) {
    return (
      <div className="bg-paper border border-white/10 rounded-xl p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-zinc-700 rounded w-1/3"></div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[1,2,3,4].map(i => (
              <div key={i} className="h-20 bg-zinc-800 rounded-lg"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }
  
  if (!summary) return null;
  
  const formatCurrency = (val) => {
    if (val === undefined || val === null) return '$0.00';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
  };
  
  return (
    <div className="bg-paper border border-white/10 rounded-xl p-6">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <DollarSign className="w-5 h-5 text-primary" />
        Account Summary
      </h2>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-gradient-to-br from-blue-500/20 to-blue-600/10 border border-blue-500/20 rounded-lg p-4">
          <div className="text-xs text-blue-400 mb-1">Net Liquidation</div>
          <div className="text-xl font-bold text-white">{formatCurrency(summary.net_liquidation)}</div>
        </div>
        <div className="bg-gradient-to-br from-green-500/20 to-green-600/10 border border-green-500/20 rounded-lg p-4">
          <div className="text-xs text-green-400 mb-1">Buying Power</div>
          <div className="text-xl font-bold text-white">{formatCurrency(summary.buying_power)}</div>
        </div>
        <div className="bg-gradient-to-br from-purple-500/20 to-purple-600/10 border border-purple-500/20 rounded-lg p-4">
          <div className="text-xs text-purple-400 mb-1">Cash Balance</div>
          <div className="text-xl font-bold text-white">{formatCurrency(summary.cash || summary.total_cash_value)}</div>
        </div>
        <div className={`bg-gradient-to-br ${summary.unrealized_pnl >= 0 ? 'from-emerald-500/20 to-emerald-600/10 border-emerald-500/20' : 'from-red-500/20 to-red-600/10 border-red-500/20'} border rounded-lg p-4`}>
          <div className={`text-xs ${summary.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} mb-1`}>Unrealized P&L</div>
          <div className={`text-xl font-bold ${summary.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {formatCurrency(summary.unrealized_pnl)}
          </div>
        </div>
      </div>
    </div>
  );
};

// ===================== POSITIONS TABLE =====================
const PositionsTable = ({ positions, loading }) => {
  if (loading) {
    return (
      <div className="bg-paper border border-white/10 rounded-xl p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-zinc-700 rounded w-1/4"></div>
          <div className="space-y-2">
            {[1,2,3].map(i => (
              <div key={i} className="h-12 bg-zinc-800 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }
  
  return (
    <div className="bg-paper border border-white/10 rounded-xl p-6">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <Briefcase className="w-5 h-5 text-primary" />
        Positions ({positions?.length || 0})
      </h2>
      
      {positions && positions.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-left text-xs text-zinc-500 border-b border-white/10">
                <th className="pb-2 pr-4">Symbol</th>
                <th className="pb-2 pr-4">Quantity</th>
                <th className="pb-2 pr-4">Avg Cost</th>
                <th className="pb-2 pr-4">Market Value</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos, idx) => (
                <tr key={idx} className="border-b border-white/5 hover:bg-white/5">
                  <td className="py-3 pr-4">
                    <span className="font-semibold text-white">{pos.symbol}</span>
                    <span className="text-xs text-zinc-500 ml-2">{pos.sec_type}</span>
                  </td>
                  <td className={`py-3 pr-4 font-mono ${pos.quantity >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {pos.quantity > 0 ? '+' : ''}{pos.quantity}
                  </td>
                  <td className="py-3 pr-4 text-zinc-300 font-mono">${pos.avg_cost?.toFixed(2)}</td>
                  <td className="py-3 pr-4 text-white font-mono">${pos.market_value?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-8 text-zinc-500">
          <Briefcase className="w-12 h-12 mx-auto mb-2 opacity-30" />
          <p>No open positions</p>
        </div>
      )}
    </div>
  );
};

// ===================== ORDER FORM =====================
const OrderForm = ({ onSubmit, loading, disabled }) => {
  const [formData, setFormData] = useState({
    symbol: '',
    action: 'BUY',
    quantity: 1,
    order_type: 'MKT',
    limit_price: '',
    stop_price: ''
  });
  
  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(formData);
  };
  
  return (
    <div className="bg-paper border border-white/10 rounded-xl p-6">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <ShoppingCart className="w-5 h-5 text-primary" />
        Place Order
      </h2>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Symbol</label>
            <input
              type="text"
              value={formData.symbol}
              onChange={(e) => setFormData({...formData, symbol: e.target.value.toUpperCase()})}
              placeholder="AAPL"
              data-testid="order-symbol-input"
              className="w-full px-3 py-2 bg-zinc-800 border border-white/10 rounded-lg text-white placeholder-zinc-500 focus:border-primary focus:outline-none"
              required
              disabled={disabled}
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Action</label>
            <select
              value={formData.action}
              onChange={(e) => setFormData({...formData, action: e.target.value})}
              data-testid="order-action-select"
              className="w-full px-3 py-2 bg-zinc-800 border border-white/10 rounded-lg text-white focus:border-primary focus:outline-none"
              disabled={disabled}
            >
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
            </select>
          </div>
        </div>
        
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Quantity</label>
            <input
              type="number"
              value={formData.quantity}
              onChange={(e) => setFormData({...formData, quantity: parseInt(e.target.value) || 1})}
              min="1"
              data-testid="order-quantity-input"
              className="w-full px-3 py-2 bg-zinc-800 border border-white/10 rounded-lg text-white focus:border-primary focus:outline-none"
              required
              disabled={disabled}
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Order Type</label>
            <select
              value={formData.order_type}
              onChange={(e) => setFormData({...formData, order_type: e.target.value})}
              data-testid="order-type-select"
              className="w-full px-3 py-2 bg-zinc-800 border border-white/10 rounded-lg text-white focus:border-primary focus:outline-none"
              disabled={disabled}
            >
              <option value="MKT">Market</option>
              <option value="LMT">Limit</option>
              <option value="STP">Stop</option>
              <option value="STP_LMT">Stop Limit</option>
            </select>
          </div>
        </div>
        
        {(formData.order_type === 'LMT' || formData.order_type === 'STP_LMT') && (
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Limit Price</label>
            <input
              type="number"
              value={formData.limit_price}
              onChange={(e) => setFormData({...formData, limit_price: e.target.value})}
              step="0.01"
              placeholder="0.00"
              data-testid="order-limit-price-input"
              className="w-full px-3 py-2 bg-zinc-800 border border-white/10 rounded-lg text-white placeholder-zinc-500 focus:border-primary focus:outline-none"
              required
              disabled={disabled}
            />
          </div>
        )}
        
        {(formData.order_type === 'STP' || formData.order_type === 'STP_LMT') && (
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Stop Price</label>
            <input
              type="number"
              value={formData.stop_price}
              onChange={(e) => setFormData({...formData, stop_price: e.target.value})}
              step="0.01"
              placeholder="0.00"
              data-testid="order-stop-price-input"
              className="w-full px-3 py-2 bg-zinc-800 border border-white/10 rounded-lg text-white placeholder-zinc-500 focus:border-primary focus:outline-none"
              required
              disabled={disabled}
            />
          </div>
        )}
        
        <button
          type="submit"
          disabled={loading || disabled || !formData.symbol}
          data-testid="submit-order-btn"
          className={`w-full py-3 rounded-lg font-semibold transition-colors flex items-center justify-center gap-2 ${
            formData.action === 'BUY' 
              ? 'bg-green-600 hover:bg-green-500 text-white' 
              : 'bg-red-600 hover:bg-red-500 text-white'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : null}
          {formData.action} {formData.quantity} {formData.symbol || 'shares'}
        </button>
        
        {disabled && (
          <p className="text-xs text-amber-400 text-center">Connect to IB Gateway to place orders</p>
        )}
      </form>
    </div>
  );
};

// ===================== OPEN ORDERS =====================
const OpenOrders = ({ orders, loading, onCancel }) => {
  const getStatusColor = (status) => {
    switch (status?.toLowerCase()) {
      case 'filled': return 'text-green-400';
      case 'cancelled': return 'text-red-400';
      case 'presubmitted':
      case 'submitted': return 'text-blue-400';
      default: return 'text-amber-400';
    }
  };
  
  const getStatusIcon = (status) => {
    switch (status?.toLowerCase()) {
      case 'filled': return <CheckCircle className="w-4 h-4" />;
      case 'cancelled': return <XCircle className="w-4 h-4" />;
      default: return <Clock className="w-4 h-4" />;
    }
  };
  
  return (
    <div className="bg-paper border border-white/10 rounded-xl p-6">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <Activity className="w-5 h-5 text-primary" />
        Open Orders ({orders?.length || 0})
      </h2>
      
      {orders && orders.length > 0 ? (
        <div className="space-y-2">
          {orders.map((order, idx) => (
            <div key={idx} className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
              <div className="flex items-center gap-3">
                <div className={getStatusColor(order.status)}>
                  {getStatusIcon(order.status)}
                </div>
                <div>
                  <span className={`font-semibold ${order.action === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>
                    {order.action}
                  </span>
                  <span className="text-white ml-2">{order.quantity} {order.symbol}</span>
                  <span className="text-zinc-500 ml-2">@ {order.order_type}</span>
                  {order.limit_price && <span className="text-zinc-400 ml-1">${order.limit_price}</span>}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`text-xs ${getStatusColor(order.status)}`}>{order.status}</span>
                {order.status !== 'Filled' && order.status !== 'Cancelled' && (
                  <button
                    onClick={() => onCancel(order.order_id)}
                    className="p-1.5 text-zinc-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                    title="Cancel Order"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-zinc-500">
          <Activity className="w-12 h-12 mx-auto mb-2 opacity-30" />
          <p>No open orders</p>
        </div>
      )}
    </div>
  );
};

// ===================== MAIN IB TRADING PAGE =====================
const IBTradingPage = () => {
  const [connectionStatus, setConnectionStatus] = useState(null);
  const [accountSummary, setAccountSummary] = useState(null);
  const [positions, setPositions] = useState([]);
  const [openOrders, setOpenOrders] = useState([]);
  const [loading, setLoading] = useState({
    connection: false,
    account: false,
    positions: false,
    orders: false,
    placeOrder: false
  });
  const [error, setError] = useState(null);
  
  const isConnected = connectionStatus?.connected;
  
  // Fetch connection status
  const fetchConnectionStatus = useCallback(async () => {
    try {
      const res = await api.get('/api/ib/status');
      setConnectionStatus(res.data);
    } catch (err) {
      console.error('Failed to fetch IB status:', err);
    }
  }, []);
  
  // Connect to IB
  const handleConnect = async () => {
    setLoading(prev => ({...prev, connection: true}));
    setError(null);
    try {
      await api.post('/api/ib/connect');
      await fetchConnectionStatus();
      // Fetch data after connecting
      await Promise.all([fetchAccountData(), fetchPositions(), fetchOpenOrders()]);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to connect to IB Gateway');
    } finally {
      setLoading(prev => ({...prev, connection: false}));
    }
  };
  
  // Disconnect from IB
  const handleDisconnect = async () => {
    setLoading(prev => ({...prev, connection: true}));
    try {
      await api.post('/api/ib/disconnect');
      await fetchConnectionStatus();
      setAccountSummary(null);
      setPositions([]);
      setOpenOrders([]);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to disconnect');
    } finally {
      setLoading(prev => ({...prev, connection: false}));
    }
  };
  
  // Fetch account data
  const fetchAccountData = async () => {
    if (!isConnected) return;
    setLoading(prev => ({...prev, account: true}));
    try {
      const res = await api.get('/api/ib/account/summary');
      setAccountSummary(res.data);
    } catch (err) {
      console.error('Failed to fetch account summary:', err);
    } finally {
      setLoading(prev => ({...prev, account: false}));
    }
  };
  
  // Fetch positions
  const fetchPositions = async () => {
    if (!isConnected) return;
    setLoading(prev => ({...prev, positions: true}));
    try {
      const res = await api.get('/api/ib/account/positions');
      setPositions(res.data.positions || []);
    } catch (err) {
      console.error('Failed to fetch positions:', err);
    } finally {
      setLoading(prev => ({...prev, positions: false}));
    }
  };
  
  // Fetch open orders
  const fetchOpenOrders = async () => {
    if (!isConnected) return;
    setLoading(prev => ({...prev, orders: true}));
    try {
      const res = await api.get('/api/ib/orders/open');
      setOpenOrders(res.data.orders || []);
    } catch (err) {
      console.error('Failed to fetch orders:', err);
    } finally {
      setLoading(prev => ({...prev, orders: false}));
    }
  };
  
  // Place order
  const handlePlaceOrder = async (orderData) => {
    setLoading(prev => ({...prev, placeOrder: true}));
    setError(null);
    try {
      const payload = {
        symbol: orderData.symbol,
        action: orderData.action,
        quantity: orderData.quantity,
        order_type: orderData.order_type
      };
      
      if (orderData.limit_price) payload.limit_price = parseFloat(orderData.limit_price);
      if (orderData.stop_price) payload.stop_price = parseFloat(orderData.stop_price);
      
      await api.post('/api/ib/order', payload);
      await fetchOpenOrders();
      await fetchAccountData();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to place order');
    } finally {
      setLoading(prev => ({...prev, placeOrder: false}));
    }
  };
  
  // Cancel order
  const handleCancelOrder = async (orderId) => {
    try {
      await api.delete(`/api/ib/order/${orderId}`);
      await fetchOpenOrders();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to cancel order');
    }
  };
  
  // Initial load
  useEffect(() => {
    fetchConnectionStatus();
  }, [fetchConnectionStatus]);
  
  // Refresh data when connected
  useEffect(() => {
    if (isConnected) {
      fetchAccountData();
      fetchPositions();
      fetchOpenOrders();
      
      // Auto-refresh every 30 seconds
      const interval = setInterval(() => {
        fetchAccountData();
        fetchPositions();
        fetchOpenOrders();
      }, 30000);
      
      return () => clearInterval(interval);
    }
  }, [isConnected]);
  
  return (
    <div className="space-y-6" data-testid="ib-trading-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <div className="p-2 bg-primary/20 rounded-lg">
              <TrendingUp className="w-6 h-6 text-primary" />
            </div>
            Interactive Brokers
          </h1>
          <p className="text-zinc-400 mt-1">Paper Trading • Account {connectionStatus?.account_id || 'DUN615665'}</p>
        </div>
        
        {isConnected && (
          <button
            onClick={() => {
              fetchAccountData();
              fetchPositions();
              fetchOpenOrders();
            }}
            className="flex items-center gap-2 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-white rounded-lg transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        )}
      </div>
      
      {/* Error Alert */}
      {error && (
        <motion.div 
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg flex items-center justify-between"
        >
          <div className="flex items-center gap-2 text-red-400">
            <AlertCircle className="w-5 h-5" />
            {error}
          </div>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
            <X className="w-4 h-4" />
          </button>
        </motion.div>
      )}
      
      {/* Connection Status */}
      <ConnectionStatus 
        status={connectionStatus}
        onConnect={handleConnect}
        onDisconnect={handleDisconnect}
        loading={loading.connection}
      />
      
      {/* Account Summary */}
      {isConnected && (
        <AccountSummary summary={accountSummary} loading={loading.account} />
      )}
      
      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Order Form */}
        <OrderForm 
          onSubmit={handlePlaceOrder}
          loading={loading.placeOrder}
          disabled={!isConnected}
        />
        
        {/* Open Orders */}
        <OpenOrders 
          orders={openOrders}
          loading={loading.orders}
          onCancel={handleCancelOrder}
        />
      </div>
      
      {/* Positions */}
      {isConnected && (
        <PositionsTable positions={positions} loading={loading.positions} />
      )}
    </div>
  );
};

export default IBTradingPage;
