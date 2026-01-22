import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BookOpen,
  Clock,
  Activity,
  AlertTriangle,
  Target,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Zap,
  Shield,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Star,
  Ban,
  CheckCircle,
  DollarSign
} from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${hover ? 'hover:border-primary/30 transition-all' : ''} ${className}`}>
    {children}
  </div>
);

// Collapsible Section Component
const CollapsibleSection = ({ title, icon: Icon, children, defaultOpen = false }) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  
  return (
    <div className="border border-white/10 rounded-lg overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-4 py-3 flex items-center justify-between bg-white/5 hover:bg-white/10 transition-colors"
      >
        <div className="flex items-center gap-3">
          <Icon className="w-5 h-5 text-primary" />
          <span className="font-semibold">{title}</span>
        </div>
        <ChevronDown className={`w-5 h-5 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="p-4 border-t border-white/10">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// Market Regime Badge
const RegimeBadge = ({ regime }) => {
  const styles = {
    high_strength_high_weakness: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    high_strength_low_weakness: 'bg-green-500/20 text-green-400 border-green-500/30',
    high_weakness_low_strength: 'bg-red-500/20 text-red-400 border-red-500/30',
    low_strength_low_weakness: 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
    breakout_momentum: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    range_fade: 'bg-purple-500/20 text-purple-400 border-purple-500/30'
  };
  
  const labels = {
    high_strength_high_weakness: 'Volatile Two-Way',
    high_strength_low_weakness: 'Strong Uptrend',
    high_weakness_low_strength: 'Strong Downtrend',
    low_strength_low_weakness: 'Choppy Range',
    breakout_momentum: 'Momentum Market',
    range_fade: 'Mean Reversion'
  };
  
  return (
    <span className={`px-2 py-1 rounded-full border text-xs font-medium ${styles[regime] || styles.low_strength_low_weakness}`}>
      {labels[regime] || regime}
    </span>
  );
};

// Strategy Recommender Component
const StrategyRecommender = () => {
  const [regime, setRegime] = useState('high_strength_low_weakness');
  const [timeOfDay, setTimeOfDay] = useState('morning_session');
  const [rvol, setRvol] = useState(2.0);
  const [hasCatalyst, setHasCatalyst] = useState(false);
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(false);

  const getRecommendations = async () => {
    setLoading(true);
    try {
      const res = await api.post('/api/rules/recommend', {
        market_regime: regime,
        time_of_day: timeOfDay,
        rvol: rvol,
        has_catalyst: hasCatalyst
      });
      setRecommendations(res.data.recommendations || []);
    } catch (err) {
      console.error('Failed to get recommendations:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    getRecommendations();
  }, [regime, timeOfDay, rvol, hasCatalyst]);

  return (
    <Card hover={false}>
      <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
        <Zap className="w-5 h-5 text-primary" />
        Strategy Recommender
      </h3>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div>
          <label className="text-xs text-zinc-500 uppercase block mb-1">Market Regime</label>
          <select
            value={regime}
            onChange={(e) => setRegime(e.target.value)}
            className="w-full bg-subtle border border-white/10 rounded px-2 py-1.5 text-sm"
          >
            <option value="high_strength_high_weakness">Volatile Two-Way</option>
            <option value="high_strength_low_weakness">Strong Uptrend</option>
            <option value="high_weakness_low_strength">Strong Downtrend</option>
            <option value="low_strength_low_weakness">Choppy Range</option>
            <option value="breakout_momentum">Momentum Market</option>
            <option value="range_fade">Mean Reversion</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500 uppercase block mb-1">Time of Day</label>
          <select
            value={timeOfDay}
            onChange={(e) => setTimeOfDay(e.target.value)}
            className="w-full bg-subtle border border-white/10 rounded px-2 py-1.5 text-sm"
          >
            <option value="opening_auction">Opening Auction (9:30-9:35)</option>
            <option value="opening_drive">Opening Drive (9:35-9:45)</option>
            <option value="morning_momentum">Morning Momentum (9:45-10:00)</option>
            <option value="morning_session">Morning Session (10:00-10:45)</option>
            <option value="late_morning">Late Morning (10:45-11:30)</option>
            <option value="midday">Midday (11:30-1:30)</option>
            <option value="afternoon">Afternoon (1:30-3:00)</option>
            <option value="close">Close (3:00-4:00)</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500 uppercase block mb-1">RVOL: {rvol.toFixed(1)}x</label>
          <input
            type="range"
            min="1"
            max="6"
            step="0.5"
            value={rvol}
            onChange={(e) => setRvol(parseFloat(e.target.value))}
            className="w-full"
          />
        </div>
        <div className="flex items-end">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={hasCatalyst}
              onChange={(e) => setHasCatalyst(e.target.checked)}
              className="rounded"
            />
            <span className="text-sm">Has Catalyst</span>
          </label>
        </div>
      </div>
      
      <div className="space-y-2">
        <p className="text-xs text-zinc-500 uppercase">Recommended Strategies</p>
        {loading ? (
          <div className="flex items-center justify-center py-4">
            <RefreshCw className="w-5 h-5 animate-spin text-primary" />
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            {recommendations.map((rec, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-lg border ${
                  rec.avoid ? 'bg-red-500/10 border-red-500/30' : 
                  rec.regime_match && rec.time_match ? 'bg-green-500/10 border-green-500/30' :
                  rec.regime_match || rec.time_match ? 'bg-primary/10 border-primary/30' :
                  'bg-white/5 border-white/10'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-sm">{rec.strategy}</span>
                  <span className="text-xs text-zinc-500">Score: {rec.score}</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {rec.regime_match && (
                    <span className="text-xs px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded">Regime ✓</span>
                  )}
                  {rec.time_match && (
                    <span className="text-xs px-1.5 py-0.5 bg-blue-500/20 text-blue-400 rounded">Time ✓</span>
                  )}
                  {rec.avoid && (
                    <span className="text-xs px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">Avoid</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
};

// Main Trading Rules Page
const TradingRulesPage = () => {
  const [rules, setRules] = useState({});
  const [gamePlan, setGamePlan] = useState({});
  const [avoidance, setAvoidance] = useState({});
  const [catalyst, setCatalyst] = useState({});
  const [loading, setLoading] = useState(true);

  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const [rulesRes, gamePlanRes, avoidRes, catalystRes] = await Promise.all([
        api.get('/api/rules/summary'),
        api.get('/api/rules/game-plan'),
        api.get('/api/rules/avoidance'),
        api.get('/api/rules/catalyst-scoring')
      ]);
      setRules(rulesRes.data);
      setGamePlan(gamePlanRes.data);
      setAvoidance(avoidRes.data);
      setCatalyst(catalystRes.data);
    } catch (err) {
      console.error('Failed to load rules:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRules(); }, [loadRules]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in" data-testid="trading-rules-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-3">
            <BookOpen className="w-7 h-7 text-primary" />
            Trading Rules & Playbook
          </h1>
          <p className="text-zinc-500 mt-1">Consolidated knowledge from SMB cheat sheets</p>
        </div>
      </div>

      {/* Strategy Recommender */}
      <StrategyRecommender />

      {/* Quick Reference Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4 text-primary" />
            <span className="text-xs text-zinc-500 uppercase">RVOL Thresholds</span>
          </div>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between"><span>Min In Play</span><span className="font-mono text-primary">1.5x</span></div>
            <div className="flex justify-between"><span>Strong</span><span className="font-mono text-green-400">2.0x</span></div>
            <div className="flex justify-between"><span>High Conviction</span><span className="font-mono text-green-400">3.0x</span></div>
            <div className="flex justify-between"><span>Exceptional</span><span className="font-mono text-yellow-400">5.0x+</span></div>
          </div>
        </Card>
        
        <Card>
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-4 h-4 text-primary" />
            <span className="text-xs text-zinc-500 uppercase">Best Times</span>
          </div>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between"><span>Prime</span><span className="font-mono text-green-400">10:00-10:45</span></div>
            <div className="flex justify-between"><span>Opening</span><span className="font-mono text-yellow-400">&lt; 9:45</span></div>
            <div className="flex justify-between"><span>Avoid Scalps</span><span className="font-mono text-red-400">&gt; 3 PM</span></div>
            <div className="flex justify-between"><span>Midday</span><span className="font-mono text-zinc-500">Reduce Size</span></div>
          </div>
        </Card>
        
        <Card>
          <div className="flex items-center gap-2 mb-2">
            <Shield className="w-4 h-4 text-primary" />
            <span className="text-xs text-zinc-500 uppercase">Stop Rules</span>
          </div>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between"><span>Standard</span><span className="font-mono">$.02 below</span></div>
            <div className="flex justify-between"><span>One-and-Done</span><span className="text-xs">Back$ide, Off Sides</span></div>
            <div className="flex justify-between"><span>Max 2x</span><span className="text-xs">Rubber Band</span></div>
          </div>
        </Card>
        
        <Card>
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-4 h-4 text-primary" />
            <span className="text-xs text-zinc-500 uppercase">Scaling</span>
          </div>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between"><span>Thirds</span><span className="font-mono">1R/2R/3R</span></div>
            <div className="flex justify-between"><span>Halves</span><span className="font-mono">2x/3x</span></div>
            <div className="flex justify-between"><span>Waves</span><span className="text-xs">HitchHiker</span></div>
            <div className="flex justify-between"><span>Full</span><span className="text-xs">VWAP target</span></div>
          </div>
        </Card>
      </div>

      {/* Game Plan Framework */}
      <CollapsibleSection title="Daily Game Plan Framework" icon={Star} defaultOpen={true}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {Object.entries(gamePlan.daily_routine || {}).map(([phase, items]) => (
            <div key={phase}>
              <h4 className="font-semibold text-primary mb-2 capitalize">{phase.replace('_', ' ')}</h4>
              <ul className="space-y-1">
                {items.map((item, idx) => (
                  <li key={idx} className="text-sm text-zinc-300 flex items-start gap-2">
                    <ChevronRight className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        
        <div className="mt-4 p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
          <h4 className="font-semibold text-yellow-400 mb-2">Common Mistakes to Avoid</h4>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {(gamePlan.common_mistakes || []).map((mistake, idx) => (
              <div key={idx} className="text-sm text-zinc-400 flex items-center gap-2">
                <Ban className="w-3 h-3 text-red-400" />
                {mistake}
              </div>
            ))}
          </div>
        </div>
      </CollapsibleSection>

      {/* Market Regimes */}
      <CollapsibleSection title="Market Context Regimes" icon={BarChart3}>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            { key: 'high_strength_low_weakness', icon: TrendingUp, color: 'green' },
            { key: 'high_weakness_low_strength', icon: TrendingDown, color: 'red' },
            { key: 'high_strength_high_weakness', icon: Activity, color: 'yellow' },
            { key: 'low_strength_low_weakness', icon: Activity, color: 'zinc' },
            { key: 'breakout_momentum', icon: Zap, color: 'blue' },
            { key: 'range_fade', icon: Target, color: 'purple' }
          ].map(({ key, icon: Icon, color }) => (
            <div key={key} className={`p-4 rounded-lg bg-${color}-500/10 border border-${color}-500/30`}>
              <div className="flex items-center gap-2 mb-2">
                <Icon className={`w-5 h-5 text-${color}-400`} />
                <RegimeBadge regime={key} />
              </div>
              <p className="text-sm text-zinc-300 mb-2">
                {key === 'high_strength_low_weakness' && 'Strong uptrend - buy dips, avoid shorts'}
                {key === 'high_weakness_low_strength' && 'Strong downtrend - sell rallies, avoid longs'}
                {key === 'high_strength_high_weakness' && 'Volatile two-way - both directions work'}
                {key === 'low_strength_low_weakness' && 'Choppy range - reduce size 50%, mean reversion'}
                {key === 'breakout_momentum' && 'Momentum market - avoid fades'}
                {key === 'range_fade' && 'Mean reversion - avoid breakouts'}
              </p>
            </div>
          ))}
        </div>
      </CollapsibleSection>

      {/* Catalyst Scoring */}
      <CollapsibleSection title="Catalyst Scoring (-10 to +10)" icon={Zap}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h4 className="font-semibold text-green-400 mb-3">Positive Catalysts</h4>
            <div className="space-y-2">
              {Object.entries(catalyst.positive_scores || {}).map(([score, data]) => (
                <div key={score} className="p-2 bg-green-500/10 rounded border border-green-500/20">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-bold text-green-400">{score}</span>
                    <span className="text-xs text-zinc-500">{data.action}</span>
                  </div>
                  <p className="text-xs text-zinc-400">{data.examples?.join(', ')}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h4 className="font-semibold text-red-400 mb-3">Negative Catalysts</h4>
            <div className="space-y-2">
              {Object.entries(catalyst.negative_scores || {}).map(([score, data]) => (
                <div key={score} className="p-2 bg-red-500/10 rounded border border-red-500/20">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-bold text-red-400">{score}</span>
                    <span className="text-xs text-zinc-500">{data.action}</span>
                  </div>
                  <p className="text-xs text-zinc-400">{data.examples?.join(', ')}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
        
        <div className="mt-4 p-3 bg-primary/10 border border-primary/30 rounded-lg">
          <h4 className="font-semibold text-primary mb-2">Scoring Tips</h4>
          <ul className="grid grid-cols-2 gap-2">
            {(catalyst.scoring_tips || []).map((tip, idx) => (
              <li key={idx} className="text-sm text-zinc-300 flex items-start gap-2">
                <CheckCircle className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                {tip}
              </li>
            ))}
          </ul>
        </div>
      </CollapsibleSection>

      {/* Avoidance Rules */}
      <CollapsibleSection title="Avoidance Rules" icon={AlertTriangle}>
        <div className="mb-4">
          <h4 className="font-semibold text-red-400 mb-3">Universal Rules - ALWAYS Avoid</h4>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {(avoidance.universal_avoidance || []).map((rule, idx) => (
              <div key={idx} className="p-2 bg-red-500/10 rounded border border-red-500/20 flex items-center gap-2">
                <Ban className="w-4 h-4 text-red-400 flex-shrink-0" />
                <span className="text-sm">{rule}</span>
              </div>
            ))}
          </div>
        </div>
        
        <div>
          <h4 className="font-semibold text-yellow-400 mb-3">Strategy-Specific Avoidance</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(avoidance.strategy_specific || {}).slice(0, 6).map(([strat, rules]) => (
              <div key={strat} className="p-3 bg-white/5 rounded-lg border border-white/10">
                <h5 className="font-medium text-primary capitalize mb-2">{strat.replace(/_/g, ' ')}</h5>
                <ul className="space-y-1">
                  {rules.slice(0, 3).map((rule, idx) => (
                    <li key={idx} className="text-xs text-zinc-400 flex items-start gap-1">
                      <span className="text-red-400">✗</span>
                      {rule}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </CollapsibleSection>
    </div>
  );
};

export default TradingRulesPage;
