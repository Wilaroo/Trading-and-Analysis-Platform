import React, { useState, useEffect, useCallback, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Sun, TrendingUp, TrendingDown, AlertTriangle, Target, Clock, Shield, BarChart3 } from 'lucide-react';
import api from '../utils/api';

const MorningBriefingModal = memo(({ isOpen, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [briefing, setBriefing] = useState(null);

  const loadBriefing = useCallback(async () => {
    setLoading(true);
    try {
      const [gamePlanRes, drcRes, positionsRes, scannerRes, botRes] = await Promise.allSettled([
        api.get('/api/journal/gameplan/today', { timeout: 10000 }),
        api.get('/api/journal/drc/today', { timeout: 10000 }),
        api.get('/api/portfolio', { timeout: 10000 }),
        api.get('/api/live-scanner/status', { timeout: 10000 }),
        api.get('/api/trading-bot/status', { timeout: 10000 }),
      ]);

      setBriefing({
        gamePlan: gamePlanRes.status === 'fulfilled' ? gamePlanRes.value.data?.game_plan : null,
        drc: drcRes.status === 'fulfilled' ? drcRes.value.data?.drc : null,
        positions: positionsRes.status === 'fulfilled' ? positionsRes.value.data?.positions || [] : [],
        scanner: scannerRes.status === 'fulfilled' ? scannerRes.value.data : null,
        bot: botRes.status === 'fulfilled' ? botRes.value.data : null,
      });
    } catch (err) {
      console.error('Failed to load morning briefing:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) loadBriefing();
  }, [isOpen, loadBriefing]);

  if (!isOpen) return null;

  const gp = briefing?.gamePlan;
  const positions = briefing?.positions || [];
  const scanner = briefing?.scanner;
  const bot = briefing?.bot;
  const openPositions = positions.filter(p => (p.quantity || p.shares || 0) !== 0);
  const totalUnrealizedPnl = openPositions.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.95, opacity: 0, y: 20 }}
          transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border border-white/10"
          style={{ background: 'linear-gradient(180deg, rgba(15,23,42,0.98) 0%, rgba(10,15,25,0.98) 100%)' }}
          onClick={(e) => e.stopPropagation()}
          data-testid="morning-briefing-modal"
        >
          {/* Header */}
          <div className="sticky top-0 z-10 flex items-center justify-between p-5 border-b border-white/10" style={{ background: 'rgba(15,23,42,0.95)', backdropFilter: 'blur(12px)' }}>
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #f59e0b, #ef4444)' }}>
                <Sun className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">Morning Briefing</h2>
                <p className="text-xs text-zinc-400">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}</p>
              </div>
            </div>
            <button onClick={onClose} className="p-2 rounded-lg hover:bg-white/10 transition-colors" data-testid="close-briefing">
              <X className="w-5 h-5 text-zinc-400" />
            </button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-48">
              <div className="w-8 h-8 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <div className="p-5 space-y-4">
              {/* Overnight Positions */}
              {openPositions.length > 0 && (
                <section>
                  <div className="flex items-center gap-2 mb-2">
                    <BarChart3 className="w-4 h-4 text-cyan-400" />
                    <h3 className="text-sm font-semibold text-white">Open Positions ({openPositions.length})</h3>
                    <span className={`ml-auto text-sm font-bold ${totalUnrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {totalUnrealizedPnl >= 0 ? '+' : ''}${totalUnrealizedPnl.toLocaleString(undefined, {maximumFractionDigits: 0})}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {openPositions.slice(0, 6).map((p, i) => (
                      <div key={i} className="p-2 rounded-lg bg-white/[0.03] border border-white/5 flex items-center justify-between">
                        <div>
                          <span className="text-xs font-mono text-white">{p.symbol}</span>
                          <span className="text-[10px] text-zinc-500 ml-1">{p.quantity || p.shares} shares</span>
                        </div>
                        <span className={`text-xs font-medium ${(p.unrealized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          ${(p.unrealized_pnl || 0).toFixed(0)}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Today's Game Plan */}
              {gp && (
                <section>
                  <div className="flex items-center gap-2 mb-2">
                    <Target className="w-4 h-4 text-amber-400" />
                    <h3 className="text-sm font-semibold text-white">Today's Game Plan</h3>
                  </div>
                  <div className="p-3 rounded-lg bg-white/[0.03] border border-white/5 space-y-2">
                    {gp.market_bias && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-zinc-500">Market Bias:</span>
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                          gp.market_bias === 'bullish' ? 'bg-emerald-500/20 text-emerald-400' :
                          gp.market_bias === 'bearish' ? 'bg-red-500/20 text-red-400' :
                          'bg-zinc-500/20 text-zinc-400'
                        }`}>{gp.market_bias}</span>
                      </div>
                    )}
                    {(gp.stocks_in_play || []).length > 0 && (
                      <div>
                        <span className="text-xs text-zinc-500">Stocks in Play:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {gp.stocks_in_play.map((s, i) => (
                            <span key={i} className="text-xs px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                              {s.symbol} {s.catalyst && <span className="text-zinc-500">— {s.catalyst}</span>}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {gp.focus_setups && (
                      <div className="text-xs text-zinc-400">
                        <span className="text-zinc-500">Focus:</span> {gp.focus_setups}
                      </div>
                    )}
                    {gp.risk_notes && (
                      <div className="text-xs text-zinc-400">
                        <span className="text-zinc-500">Risk:</span> {gp.risk_notes}
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* System Status */}
              <section>
                <div className="flex items-center gap-2 mb-2">
                  <Shield className="w-4 h-4 text-violet-400" />
                  <h3 className="text-sm font-semibold text-white">System Status</h3>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="p-2 rounded-lg bg-white/[0.03] border border-white/5 text-center">
                    <div className={`text-xs font-medium ${scanner?.mode ? 'text-emerald-400' : 'text-zinc-500'}`}>
                      {scanner?.mode || 'Idle'}
                    </div>
                    <div className="text-[10px] text-zinc-500">Scanner</div>
                  </div>
                  <div className="p-2 rounded-lg bg-white/[0.03] border border-white/5 text-center">
                    <div className={`text-xs font-medium ${bot?.is_active ? 'text-emerald-400' : 'text-zinc-500'}`}>
                      {bot?.is_active ? 'Active' : 'Idle'}
                    </div>
                    <div className="text-[10px] text-zinc-500">Trading Bot</div>
                  </div>
                  <div className="p-2 rounded-lg bg-white/[0.03] border border-white/5 text-center">
                    <div className="text-xs font-medium text-amber-400">Paper</div>
                    <div className="text-[10px] text-zinc-500">Account Mode</div>
                  </div>
                </div>
              </section>

              {/* Quick Actions */}
              <section className="pt-2 border-t border-white/5">
                <div className="flex items-center gap-2">
                  <button
                    onClick={onClose}
                    className="flex-1 py-2.5 rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 text-white text-sm font-medium hover:brightness-110 transition-all"
                    data-testid="start-trading-btn"
                  >
                    Let's Trade
                  </button>
                </div>
              </section>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
});

export default MorningBriefingModal;
