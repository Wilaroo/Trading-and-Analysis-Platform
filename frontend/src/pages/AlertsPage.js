import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bell, RefreshCw, Zap, Check, Trash2, Calendar, TrendingUp, TrendingDown } from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

// ===================== ALERTS PAGE =====================
const AlertsPage = () => {
  const [alerts, setAlerts] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [earningsSummary, setEarningsSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [filter, setFilter] = useState('all');
  const [activeTab, setActiveTab] = useState('strategy'); // 'strategy' or 'earnings'

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/alerts', { params: { unread_only: filter === 'unread' } });
      setAlerts(res.data.alerts || []);
    } catch (err) { console.error('Failed to load alerts:', err); }
    finally { setLoading(false); }
  }, [filter]);

  const loadNotifications = useCallback(async () => {
    try {
      const [notifRes, summaryRes] = await Promise.all([
        api.get('/api/notifications', { params: { unread_only: filter === 'unread' } }),
        api.get('/api/notifications/earnings-summary')
      ]);
      setNotifications(notifRes.data.notifications || []);
      setEarningsSummary(summaryRes.data);
    } catch (err) { console.error('Failed to load notifications:', err); }
  }, [filter]);

  useEffect(() => { 
    loadAlerts(); 
    loadNotifications();
  }, [loadAlerts, loadNotifications]);

  const generateAlerts = async () => {
    setGenerating(true);
    try {
      await api.post('/api/alerts/generate');
      loadAlerts();
    } catch (err) { console.error('Failed to generate alerts:', err); }
    finally { setGenerating(false); }
  };

  const checkEarningsNotifications = async () => {
    setGenerating(true);
    try {
      await api.get('/api/notifications/check-earnings');
      loadNotifications();
    } catch (err) { console.error('Failed to check earnings:', err); }
    finally { setGenerating(false); }
  };

  const markAsRead = async (alertId) => {
    try {
      await api.put(`/api/alerts/${alertId}/read`);
      loadAlerts();
    } catch (err) { console.error('Failed to mark alert as read:', err); }
  };

  const markNotificationRead = async (key) => {
    try {
      await api.post(`/api/notifications/${key}/read`);
      loadNotifications();
    } catch (err) { console.error('Failed to mark notification as read:', err); }
  };

  const deleteAlert = async (alertId) => {
    try {
      await api.delete(`/api/alerts/${alertId}`);
      loadAlerts();
    } catch (err) { console.error('Failed to delete alert:', err); }
  };

  const deleteNotification = async (key) => {
    try {
      await api.delete(`/api/notifications/${key}`);
      loadNotifications();
    } catch (err) { console.error('Failed to delete notification:', err); }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="alerts-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Bell className="w-6 h-6 text-primary" />
            Alert Center
          </h1>
          <p className="text-zinc-500 text-sm">Strategy matches & earnings notifications</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => { loadAlerts(); loadNotifications(); }} className="btn-secondary flex items-center gap-2">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          {activeTab === 'strategy' ? (
            <button
              onClick={generateAlerts}
              disabled={generating}
              className="btn-primary flex items-center gap-2"
              data-testid="generate-alerts-btn"
            >
              {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              Scan for Alerts
            </button>
          ) : (
            <button
              onClick={checkEarningsNotifications}
              disabled={generating}
              className="btn-primary flex items-center gap-2"
              data-testid="check-earnings-btn"
            >
              {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Calendar className="w-4 h-4" />}
              Check Earnings
            </button>
          )}
        </div>
      </div>

      {/* Earnings Summary Cards */}
      {earningsSummary && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card className="bg-gradient-to-br from-primary/10 to-primary/5">
            <p className="text-xs text-zinc-500 uppercase">Watchlist Stocks</p>
            <p className="text-2xl font-bold mt-1">{earningsSummary.watchlist_count}</p>
          </Card>
          <Card className="bg-gradient-to-br from-yellow-500/10 to-yellow-500/5">
            <p className="text-xs text-zinc-500 uppercase">Earnings This Week</p>
            <p className="text-2xl font-bold mt-1 text-yellow-400">{earningsSummary.earnings_this_week}</p>
            {earningsSummary.symbols_this_week?.length > 0 && (
              <p className="text-xs text-zinc-400 mt-1">{earningsSummary.symbols_this_week.join(', ')}</p>
            )}
          </Card>
          <Card className="bg-gradient-to-br from-blue-500/10 to-blue-500/5">
            <p className="text-xs text-zinc-500 uppercase">Earnings Next Week</p>
            <p className="text-2xl font-bold mt-1 text-blue-400">{earningsSummary.earnings_next_week}</p>
            {earningsSummary.symbols_next_week?.length > 0 && (
              <p className="text-xs text-zinc-400 mt-1">{earningsSummary.symbols_next_week.join(', ')}</p>
            )}
          </Card>
          <Card className="bg-gradient-to-br from-red-500/10 to-red-500/5">
            <p className="text-xs text-zinc-500 uppercase">High IV Earnings</p>
            <p className="text-2xl font-bold mt-1 text-red-400">{earningsSummary.high_iv_earnings}</p>
          </Card>
        </div>
      )}

      {/* Tab Selector */}
      <div className="flex gap-2 border-b border-white/10 pb-2">
        <button
          onClick={() => setActiveTab('strategy')}
          className={`px-4 py-2 rounded-t-lg text-sm font-medium transition-colors ${
            activeTab === 'strategy'
              ? 'bg-primary/20 text-primary border-b-2 border-primary'
              : 'text-zinc-400 hover:text-white'
          }`}
        >
          <Zap className="w-4 h-4 inline mr-2" />
          Strategy Alerts ({alerts.length})
        </button>
        <button
          onClick={() => setActiveTab('earnings')}
          className={`px-4 py-2 rounded-t-lg text-sm font-medium transition-colors ${
            activeTab === 'earnings'
              ? 'bg-primary/20 text-primary border-b-2 border-primary'
              : 'text-zinc-400 hover:text-white'
          }`}
        >
          <Calendar className="w-4 h-4 inline mr-2" />
          Earnings Notifications ({notifications.length})
        </button>
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-2">
        {['all', 'unread'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              filter === f
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'bg-white/5 text-zinc-400 hover:bg-white/10 hover:text-white'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Strategy Alerts List */}
      {activeTab === 'strategy' && (
        <Card hover={false}>
          <h2 className="font-semibold mb-4">Strategy Alerts ({alerts.length})</h2>
          
          {loading ? (
            <div className="animate-pulse space-y-3">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-20 bg-white/5 rounded"></div>
              ))}
            </div>
          ) : alerts.length > 0 ? (
            <div className="space-y-3">
              <AnimatePresence>
                {alerts.map((alert, idx) => (
                  <motion.div
                    key={alert._id || idx}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: -100 }}
                    className={`glass-card rounded-lg p-4 ${
                      !alert.read ? 'border-l-4 border-l-primary' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-4">
                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                          alert.score >= 70 ? 'bg-green-500/20' : 
                          alert.score >= 50 ? 'bg-yellow-500/20' : 
                          'bg-blue-500/20'
                        }`}>
                          <Zap className={`w-5 h-5 ${
                            alert.score >= 70 ? 'text-green-400' : 
                            alert.score >= 50 ? 'text-yellow-400' : 
                            'text-blue-400'
                          }`} />
                        </div>
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-bold text-primary">{alert.symbol}</span>
                            <span className="badge badge-info">{alert.strategy_id}</span>
                            <span className="text-sm text-zinc-400">Score: {alert.score}</span>
                          </div>
                          <p className="text-sm text-zinc-300">{alert.strategy_name}</p>
                          <p className="text-xs text-zinc-500 mt-1">
                            {new Date(alert.timestamp).toLocaleString()}
                          </p>
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-2">
                        {!alert.read && (
                          <button
                            onClick={() => markAsRead(alert._id)}
                            className="p-2 text-zinc-500 hover:text-green-400 transition-colors"
                            title="Mark as read"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                        )}
                        <button
                          onClick={() => deleteAlert(alert._id)}
                          className="p-2 text-zinc-500 hover:text-red-400 transition-colors"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          ) : (
            <div className="text-center py-12">
              <Zap className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
              <p className="text-zinc-500">No strategy alerts yet</p>
              <p className="text-zinc-600 text-sm mt-1">Click "Scan for Alerts" to find strategy matches</p>
            </div>
          )}
        </Card>
      )}

      {/* Earnings Notifications List */}
      {activeTab === 'earnings' && (
        <Card hover={false}>
          <h2 className="font-semibold mb-4">Earnings Notifications ({notifications.length})</h2>
          
          {notifications.length > 0 ? (
            <div className="space-y-3">
              <AnimatePresence>
                {notifications.map((notif, idx) => (
                  <motion.div
                    key={notif.key || idx}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: -100 }}
                    className={`glass-card rounded-lg p-4 ${
                      !notif.read ? 'border-l-4 border-l-yellow-500' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-4">
                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                          notif.priority === 'high' ? 'bg-red-500/20' : 'bg-yellow-500/20'
                        }`}>
                          <Calendar className={`w-5 h-5 ${
                            notif.priority === 'high' ? 'text-red-400' : 'text-yellow-400'
                          }`} />
                        </div>
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-bold text-primary">{notif.symbol}</span>
                            <span className={`badge ${
                              notif.priority === 'high' ? 'bg-red-500/20 text-red-400' : 'bg-yellow-500/20 text-yellow-400'
                            }`}>
                              {notif.type === 'earnings_upcoming' ? 'Earnings' : notif.type}
                            </span>
                          </div>
                          <p className="text-sm text-zinc-300">{notif.message}</p>
                          {notif.eps_estimate && (
                            <p className="text-xs text-zinc-400 mt-1">EPS Est: ${notif.eps_estimate}</p>
                          )}
                          <p className="text-xs text-zinc-500 mt-1">
                            {new Date(notif.created_at).toLocaleString()}
                          </p>
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-2">
                        {!notif.read && (
                          <button
                            onClick={() => markNotificationRead(notif.key)}
                            className="p-2 text-zinc-500 hover:text-green-400 transition-colors"
                            title="Mark as read"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                        )}
                        <button
                          onClick={() => deleteNotification(notif.key)}
                          className="p-2 text-zinc-500 hover:text-red-400 transition-colors"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          ) : (
            <div className="text-center py-12">
              <Calendar className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
              <p className="text-zinc-500">No earnings notifications</p>
              <p className="text-zinc-600 text-sm mt-1">Add stocks to your watchlist and click "Check Earnings" to get notified</p>
            </div>
          )}
        </Card>
      )}
    </div>
  );
};

export default AlertsPage;
