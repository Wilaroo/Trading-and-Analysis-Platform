import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, Clock, Target, X, TrendingUp } from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', onClick, hover = true }) => (
  <div 
    onClick={onClick}
    className={`bg-paper rounded-lg p-4 border border-white/10 ${
      hover ? 'transition-all duration-200 hover:border-primary/30' : ''
    } ${onClick ? 'cursor-pointer' : ''} ${className}`}
  >
    {children}
  </div>
);

const StrategyCard = ({ strategy, onClick }) => {
  const categoryColors = {
    intraday: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    swing: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    investment: 'bg-green-500/20 text-green-400 border-green-500/30'
  };

  return (
    <Card onClick={onClick} className="group">
      <div className="flex items-start justify-between mb-3">
        <span className={`badge ${categoryColors[strategy.category]}`}>
          {strategy.category}
        </span>
        <span className="text-xs text-zinc-500 font-mono">{strategy.id}</span>
      </div>
      <h3 className="font-semibold mb-2 group-hover:text-primary transition-colors">
        {strategy.name}
      </h3>
      <div className="flex flex-wrap gap-1 mb-3">
        {strategy.indicators?.slice(0, 3).map((ind, idx) => (
          <span key={idx} className="text-xs bg-white/5 px-2 py-0.5 rounded text-zinc-400">
            {ind}
          </span>
        ))}
      </div>
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {strategy.timeframe}
        </span>
        <span className="flex items-center gap-1">
          <Target className="w-3 h-3" />
          {strategy.risk_reward}
        </span>
      </div>
    </Card>
  );
};

// ===================== STRATEGIES PAGE =====================
const StrategiesPage = () => {
  const [strategies, setStrategies] = useState([]);
  const [category, setCategory] = useState('all');
  const [selectedStrategy, setSelectedStrategy] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadStrategies();
  }, []);

  const loadStrategies = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/strategies');
      setStrategies(res.data.strategies);
    } catch (err) { console.error('Failed to load strategies:', err); }
    finally { setLoading(false); }
  };

  const filteredStrategies = category === 'all' 
    ? strategies 
    : strategies.filter(s => s.category === category);

  const categoryColors = {
    intraday: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    swing: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    investment: 'bg-green-500/20 text-green-400 border-green-500/30'
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="strategies-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-primary" />
            Trading Strategies
          </h1>
          <p className="text-zinc-500 text-sm">50 detailed strategies with criteria</p>
        </div>
      </div>

      {/* Category Filter */}
      <div className="flex gap-2">
        {['all', 'intraday', 'swing', 'investment'].map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              category === cat
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'bg-white/5 text-zinc-400 hover:bg-white/10 hover:text-white'
            }`}
          >
            {cat.charAt(0).toUpperCase() + cat.slice(1)}
            {cat !== 'all' && (
              <span className="ml-2 text-xs opacity-60">
                ({strategies.filter(s => s.category === cat).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Strategies Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading ? (
          Array.from({ length: 6 }).map((_, idx) => (
            <div key={idx} className="bg-paper rounded-lg p-4 border border-white/10 animate-pulse">
              <div className="h-6 bg-white/5 rounded w-20 mb-3"></div>
              <div className="h-5 bg-white/5 rounded w-3/4 mb-2"></div>
              <div className="h-4 bg-white/5 rounded w-1/2"></div>
            </div>
          ))
        ) : (
          filteredStrategies.map((strategy) => (
            <StrategyCard
              key={strategy.id}
              strategy={strategy}
              onClick={() => setSelectedStrategy(strategy)}
            />
          ))
        )}
      </div>

      {/* Strategy Details Modal */}
      <AnimatePresence>
        {selectedStrategy && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={() => setSelectedStrategy(null)}
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-paper border border-white/10 rounded-xl max-w-2xl w-full p-6 max-h-[80vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between mb-6">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`badge ${categoryColors[selectedStrategy.category]}`}>
                      {selectedStrategy.category}
                    </span>
                    <span className="text-xs text-zinc-500 font-mono">{selectedStrategy.id}</span>
                  </div>
                  <h2 className="text-xl font-bold">{selectedStrategy.name}</h2>
                </div>
                <button onClick={() => setSelectedStrategy(null)} className="text-zinc-500 hover:text-white">
                  <X className="w-6 h-6" />
                </button>
              </div>

              {/* Description */}
              <div className="mb-6">
                <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-2">Description</h3>
                <p className="text-zinc-300">{selectedStrategy.description}</p>
              </div>

              {/* Criteria */}
              <div className="mb-6">
                <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-2">Entry Criteria</h3>
                <ul className="space-y-2">
                  {selectedStrategy.criteria?.map((criteria, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-sm text-zinc-300">
                      <TrendingUp className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
                      {criteria}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Indicators & Settings */}
              <div className="grid grid-cols-2 gap-4 mb-6">
                <div>
                  <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-2">Indicators</h3>
                  <div className="flex flex-wrap gap-1">
                    {selectedStrategy.indicators?.map((ind, idx) => (
                      <span key={idx} className="text-xs bg-white/5 px-2 py-1 rounded text-zinc-400">
                        {ind}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-2">Details</h3>
                  <div className="space-y-1 text-sm">
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">Timeframe:</span> {selectedStrategy.timeframe}
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">Risk/Reward:</span> {selectedStrategy.risk_reward}
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default StrategiesPage;
