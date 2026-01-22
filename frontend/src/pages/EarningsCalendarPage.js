import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Calendar, 
  RefreshCw, 
  TrendingUp, 
  TrendingDown, 
  BarChart3, 
  Activity,
  ChevronRight,
  ChevronLeft,
  X,
  Target,
  Zap,
  Clock,
  AlertTriangle,
  Star,
  Calculator
} from 'lucide-react';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  Cell,
  LineChart,
  Line
} from 'recharts';
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

const PriceDisplay = ({ value, className = '' }) => {
  if (value === null || value === undefined) return <span className="text-zinc-500">--</span>;
  const isPositive = value >= 0;
  return (
    <span className={`font-mono flex items-center gap-1 ${isPositive ? 'text-green-400' : 'text-red-400'} ${className}`}>
      {isPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {isPositive ? '+' : ''}{value.toFixed(2)}%
    </span>
  );
};

// Catalyst Score Badge Component
const CatalystScoreBadge = ({ score, rating, bias, size = 'md' }) => {
  const getBgColor = (rating) => {
    if (rating === 'A+' || rating === 'A') return 'bg-green-500/30 border-green-500';
    if (rating === 'B+' || rating === 'B') return 'bg-green-500/20 border-green-500/50';
    if (rating === 'C') return 'bg-yellow-500/20 border-yellow-500/50';
    if (rating === 'D') return 'bg-red-500/20 border-red-500/50';
    return 'bg-red-500/30 border-red-500';
  };
  
  const getTextColor = (rating) => {
    if (rating === 'A+' || rating === 'A' || rating === 'B+' || rating === 'B') return 'text-green-400';
    if (rating === 'C') return 'text-yellow-400';
    return 'text-red-400';
  };
  
  return (
    <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border ${getBgColor(rating)}`}>
      <Star className={`${size === 'lg' ? 'w-5 h-5' : 'w-4 h-4'} ${getTextColor(rating)}`} />
      <div className="text-center">
        <p className={`${size === 'lg' ? 'text-xl' : 'text-lg'} font-bold ${getTextColor(rating)}`}>
          {score >= 0 ? '+' : ''}{score}
        </p>
        <p className="text-xs text-zinc-400">{rating} • {bias}</p>
      </div>
    </div>
  );
};

// Quick Catalyst Scorer Component
const QuickCatalystScorer = ({ symbol, onScore }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState({
    eps_beat_pct: 0,
    revenue_beat_pct: 0,
    guidance: 'inline',
    price_reaction_pct: 0,
    volume_multiple: 1.0
  });

  const handleScore = async () => {
    setLoading(true);
    try {
      const res = await api.post('/api/catalyst/score/quick', {
        symbol,
        ...inputs
      });
      setResult(res.data);
      if (onScore) onScore(res.data);
    } catch (err) {
      console.error('Scoring failed:', err);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="btn-secondary flex items-center gap-2"
        data-testid="open-catalyst-scorer"
      >
        <Calculator className="w-4 h-4" />
        Score Catalyst
      </button>
    );
  }

  return (
    <Card hover={false} className="mt-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold flex items-center gap-2">
          <Calculator className="w-5 h-5 text-primary" />
          Catalyst Scorer - {symbol}
        </h3>
        <button onClick={() => setIsOpen(false)} className="text-zinc-500 hover:text-white">
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        <div>
          <label className="text-xs text-zinc-500 block mb-1">EPS Beat %</label>
          <input
            type="number"
            step="0.1"
            value={inputs.eps_beat_pct}
            onChange={(e) => setInputs({...inputs, eps_beat_pct: parseFloat(e.target.value) || 0})}
            className="w-full bg-subtle border border-white/10 rounded px-2 py-1.5 text-sm"
            placeholder="5.2"
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500 block mb-1">Revenue Beat %</label>
          <input
            type="number"
            step="0.1"
            value={inputs.revenue_beat_pct}
            onChange={(e) => setInputs({...inputs, revenue_beat_pct: parseFloat(e.target.value) || 0})}
            className="w-full bg-subtle border border-white/10 rounded px-2 py-1.5 text-sm"
            placeholder="2.1"
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500 block mb-1">Guidance</label>
          <select
            value={inputs.guidance}
            onChange={(e) => setInputs({...inputs, guidance: e.target.value})}
            className="w-full bg-subtle border border-white/10 rounded px-2 py-1.5 text-sm"
          >
            <option value="raised">Raised</option>
            <option value="inline">In-line</option>
            <option value="lowered">Lowered</option>
            <option value="cut">Cut</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500 block mb-1">Price Move %</label>
          <input
            type="number"
            step="0.1"
            value={inputs.price_reaction_pct}
            onChange={(e) => setInputs({...inputs, price_reaction_pct: parseFloat(e.target.value) || 0})}
            className="w-full bg-subtle border border-white/10 rounded px-2 py-1.5 text-sm"
            placeholder="4.5"
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500 block mb-1">Volume (x avg)</label>
          <input
            type="number"
            step="0.1"
            value={inputs.volume_multiple}
            onChange={(e) => setInputs({...inputs, volume_multiple: parseFloat(e.target.value) || 1})}
            className="w-full bg-subtle border border-white/10 rounded px-2 py-1.5 text-sm"
            placeholder="2.3"
          />
        </div>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={handleScore}
          disabled={loading}
          className="btn-primary flex items-center gap-2"
          data-testid="calculate-catalyst-score"
        >
          {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          Calculate Score
        </button>

        {result && (
          <div className="flex items-center gap-4">
            <CatalystScoreBadge 
              score={result.raw_score} 
              rating={result.rating} 
              bias={result.bias}
              size="lg"
            />
            <p className="text-sm text-zinc-400">{result.interpretation}</p>
          </div>
        )}
      </div>

      {result && (
        <div className="mt-4 grid grid-cols-4 gap-2">
          {Object.entries(result.components).map(([key, comp]) => (
            <div key={key} className="bg-white/5 rounded p-2 text-center">
              <p className="text-xs text-zinc-500 capitalize">{key.replace('_', ' ')}</p>
              <p className={`font-bold ${comp.score >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {comp.score >= 0 ? '+' : ''}{comp.score}
              </p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};

// ===================== EARNINGS CALENDAR PAGE =====================
const EarningsCalendarPage = () => {
  const [calendar, setCalendar] = useState([]);
  const [groupedData, setGroupedData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedEarning, setSelectedEarning] = useState(null);
  const [detailedData, setDetailedData] = useState(null);
  const [ivData, setIvData] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [dateRange, setDateRange] = useState({
    start: new Date().toISOString().split('T')[0],
    end: new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
  });
  const [viewMode, setViewMode] = useState('list'); // 'list' or 'calendar'

  const loadEarningsCalendar = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/earnings/calendar', {
        params: {
          start_date: dateRange.start,
          end_date: dateRange.end
        }
      });
      setCalendar(res.data.calendar || []);
      setGroupedData(res.data.grouped_by_date || []);
    } catch (err) { 
      console.error('Failed to load earnings calendar:', err); 
    }
    finally { setLoading(false); }
  }, [dateRange]);

  useEffect(() => { loadEarningsCalendar(); }, [loadEarningsCalendar]);

  const loadEarningsDetail = async (symbol) => {
    setLoadingDetail(true);
    try {
      const [detailRes, ivRes] = await Promise.all([
        api.get(`/api/earnings/${symbol}`),
        api.get(`/api/earnings/iv/${symbol}`)
      ]);
      setDetailedData(detailRes.data);
      setIvData(ivRes.data);
    } catch (err) { 
      console.error('Failed to load earnings detail:', err); 
    }
    finally { setLoadingDetail(false); }
  };

  const handleSelectEarning = (earning) => {
    setSelectedEarning(earning);
    loadEarningsDetail(earning.symbol);
  };

  const navigateWeek = (direction) => {
    const days = direction === 'next' ? 7 : -7;
    const newStart = new Date(new Date(dateRange.start).getTime() + days * 24 * 60 * 60 * 1000);
    const newEnd = new Date(new Date(dateRange.end).getTime() + days * 24 * 60 * 60 * 1000);
    setDateRange({
      start: newStart.toISOString().split('T')[0],
      end: newEnd.toISOString().split('T')[0]
    });
  };

  const getSentimentColor = (sentiment) => {
    if (sentiment?.includes('Bullish')) return 'text-green-400';
    if (sentiment?.includes('Bearish')) return 'text-red-400';
    return 'text-yellow-400';
  };

  const getSentimentBg = (sentiment) => {
    if (sentiment?.includes('Bullish')) return 'bg-green-500/20 border-green-500/30';
    if (sentiment?.includes('Bearish')) return 'bg-red-500/20 border-red-500/30';
    return 'bg-yellow-500/20 border-yellow-500/30';
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="earnings-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Calendar className="w-6 h-6 text-primary" />
            Earnings Calendar
          </h1>
          <p className="text-zinc-500 text-sm">Track earnings, IV, whispers & historical data</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setViewMode(viewMode === 'list' ? 'calendar' : 'list')}
            className="btn-secondary"
          >
            {viewMode === 'list' ? 'Calendar View' : 'List View'}
          </button>
          <button onClick={loadEarningsCalendar} className="btn-secondary flex items-center gap-2">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Date Navigation */}
      <Card hover={false}>
        <div className="flex items-center justify-between">
          <button 
            onClick={() => navigateWeek('prev')}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <div className="text-center">
            <p className="text-lg font-semibold">
              {new Date(dateRange.start).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - {new Date(dateRange.end).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            </p>
            <p className="text-sm text-zinc-500">{calendar.length} earnings reports</p>
          </div>
          <button 
            onClick={() => navigateWeek('next')}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      </Card>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="text-center">
          <p className="text-xs text-zinc-500 uppercase">Total Reports</p>
          <p className="text-2xl font-bold text-primary">{calendar.length}</p>
        </Card>
        <Card className="text-center">
          <p className="text-xs text-zinc-500 uppercase">Before Open</p>
          <p className="text-2xl font-bold">{calendar.filter(c => c.time === 'Before Open').length}</p>
        </Card>
        <Card className="text-center">
          <p className="text-xs text-zinc-500 uppercase">After Close</p>
          <p className="text-2xl font-bold">{calendar.filter(c => c.time === 'After Close').length}</p>
        </Card>
        <Card className="text-center">
          <p className="text-xs text-zinc-500 uppercase">High IV (>50%)</p>
          <p className="text-2xl font-bold text-yellow-400">
            {calendar.filter(c => c.implied_volatility?.current_iv > 50).length}
          </p>
        </Card>
      </div>

      {/* Earnings List */}
      {loading ? (
        <Card hover={false} className="animate-pulse">
          <div className="h-64 bg-white/5 rounded"></div>
        </Card>
      ) : viewMode === 'list' ? (
        <Card hover={false}>
          <h2 className="font-semibold mb-4">Upcoming Earnings</h2>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Symbol</th>
                  <th>Time</th>
                  <th>EPS Est.</th>
                  <th>Whisper</th>
                  <th>IV</th>
                  <th>Exp. Move</th>
                  <th>Sentiment</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {calendar.map((earning, idx) => (
                  <tr 
                    key={idx} 
                    className="cursor-pointer hover:bg-white/5"
                    onClick={() => handleSelectEarning(earning)}
                  >
                    <td className="text-zinc-400">
                      {new Date(earning.earnings_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </td>
                    <td>
                      <div>
                        <span className="font-bold text-primary">{earning.symbol}</span>
                        <p className="text-xs text-zinc-500">{earning.company_name}</p>
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${earning.time === 'Before Open' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-blue-500/20 text-blue-400'}`}>
                        {earning.time === 'Before Open' ? 'BMO' : 'AMC'}
                      </span>
                    </td>
                    <td className="font-mono">${earning.eps_estimate?.toFixed(2)}</td>
                    <td>
                      <div className="flex items-center gap-1">
                        <span className="font-mono">${earning.whisper_eps?.toFixed(2)}</span>
                        {earning.whisper_vs_consensus > 0 ? (
                          <TrendingUp className="w-3 h-3 text-green-400" />
                        ) : (
                          <TrendingDown className="w-3 h-3 text-red-400" />
                        )}
                      </div>
                    </td>
                    <td>
                      <span className={`font-mono ${earning.implied_volatility?.current_iv > 50 ? 'text-yellow-400' : 'text-zinc-400'}`}>
                        {earning.implied_volatility?.current_iv}%
                      </span>
                    </td>
                    <td className="font-mono">±{earning.implied_volatility?.expected_move_percent}%</td>
                    <td>
                      <span className={`badge ${getSentimentBg(earning.whisper?.sentiment)}`}>
                        {earning.whisper?.sentiment}
                      </span>
                    </td>
                    <td>
                      <ChevronRight className="w-4 h-4 text-zinc-500" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        /* Calendar View */
        <div className="grid grid-cols-7 gap-2">
          {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(day => (
            <div key={day} className="text-center text-xs text-zinc-500 uppercase py-2">{day}</div>
          ))}
          {groupedData.map((day, idx) => (
            <Card key={idx} className="min-h-[100px] p-2" hover={false}>
              <p className="text-xs text-zinc-400 mb-2">
                {new Date(day.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </p>
              <div className="space-y-1">
                {[...day.before_open, ...day.after_close].slice(0, 3).map((e, i) => (
                  <button
                    key={i}
                    onClick={() => handleSelectEarning(e)}
                    className="w-full text-left text-xs p-1 rounded bg-white/5 hover:bg-white/10 truncate"
                  >
                    <span className="text-primary font-medium">{e.symbol}</span>
                    <span className="text-zinc-500 ml-1">{e.time === 'Before Open' ? 'BMO' : 'AMC'}</span>
                  </button>
                ))}
                {day.count > 3 && (
                  <p className="text-xs text-zinc-500">+{day.count - 3} more</p>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Earnings Detail Modal */}
      <AnimatePresence>
        {selectedEarning && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto"
            onClick={() => setSelectedEarning(null)}
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-paper border border-white/10 rounded-xl max-w-4xl w-full p-6 my-8"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between mb-6">
                <div>
                  <div className="flex items-center gap-3">
                    <h2 className="text-2xl font-bold text-primary">{selectedEarning.symbol}</h2>
                    <span className={`badge ${selectedEarning.time === 'Before Open' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-blue-500/20 text-blue-400'}`}>
                      {selectedEarning.time}
                    </span>
                  </div>
                  <p className="text-zinc-400">{selectedEarning.company_name}</p>
                  <p className="text-sm text-zinc-500">
                    {selectedEarning.fiscal_quarter} • {new Date(selectedEarning.earnings_date).toLocaleDateString()}
                  </p>
                </div>
                <button onClick={() => setSelectedEarning(null)} className="text-zinc-500 hover:text-white">
                  <X className="w-6 h-6" />
                </button>
              </div>

              {loadingDetail ? (
                <div className="animate-pulse space-y-4">
                  <div className="h-32 bg-white/5 rounded"></div>
                  <div className="h-48 bg-white/5 rounded"></div>
                </div>
              ) : (
                <div className="space-y-6 max-h-[70vh] overflow-y-auto">
                  {/* Estimates & Whispers */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-white/5 rounded-lg p-3">
                      <p className="text-xs text-zinc-500 uppercase">EPS Estimate</p>
                      <p className="text-xl font-mono font-bold">${detailedData?.eps_estimate?.toFixed(2)}</p>
                      <p className="text-xs text-zinc-500">{detailedData?.analyst_count} analysts</p>
                    </div>
                    <div className="bg-white/5 rounded-lg p-3">
                      <p className="text-xs text-zinc-500 uppercase">Whisper EPS</p>
                      <p className="text-xl font-mono font-bold">${detailedData?.whisper_eps?.toFixed(2)}</p>
                      <p className={`text-xs ${detailedData?.whisper_vs_consensus > 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {detailedData?.whisper_vs_consensus > 0 ? '+' : ''}{detailedData?.whisper_vs_consensus?.toFixed(1)}% vs consensus
                      </p>
                    </div>
                    <div className="bg-white/5 rounded-lg p-3">
                      <p className="text-xs text-zinc-500 uppercase">Revenue Est.</p>
                      <p className="text-xl font-mono font-bold">${detailedData?.revenue_estimate_b?.toFixed(1)}B</p>
                    </div>
                    <div className={`rounded-lg p-3 ${getSentimentBg(detailedData?.whisper?.sentiment)}`}>
                      <p className="text-xs text-zinc-500 uppercase">Sentiment</p>
                      <p className={`text-xl font-bold ${getSentimentColor(detailedData?.whisper?.sentiment)}`}>
                        {detailedData?.whisper?.sentiment}
                      </p>
                      <p className="text-xs text-zinc-400">{detailedData?.whisper?.confidence}% confidence</p>
                    </div>
                  </div>

                  {/* Catalyst Scorer */}
                  <QuickCatalystScorer symbol={selectedEarning.symbol} />

                  {/* Implied Volatility Section */}
                  <Card hover={false}>
                    <h3 className="font-semibold mb-4 flex items-center gap-2">
                      <Activity className="w-5 h-5 text-yellow-400" />
                      Implied Volatility Analysis
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
                      <div className="bg-white/5 rounded-lg p-3 text-center">
                        <p className="text-xs text-zinc-500">Current IV</p>
                        <p className={`text-lg font-mono font-bold ${ivData?.current_iv > 50 ? 'text-yellow-400' : 'text-white'}`}>
                          {ivData?.current_iv}%
                        </p>
                      </div>
                      <div className="bg-white/5 rounded-lg p-3 text-center">
                        <p className="text-xs text-zinc-500">IV Rank</p>
                        <p className="text-lg font-mono font-bold">{ivData?.iv_rank}%</p>
                      </div>
                      <div className="bg-white/5 rounded-lg p-3 text-center">
                        <p className="text-xs text-zinc-500">IV Percentile</p>
                        <p className="text-lg font-mono font-bold">{ivData?.iv_percentile}%</p>
                      </div>
                      <div className="bg-white/5 rounded-lg p-3 text-center">
                        <p className="text-xs text-zinc-500">Expected Move</p>
                        <p className="text-lg font-mono font-bold text-primary">±{ivData?.expected_move?.percent}%</p>
                      </div>
                      <div className="bg-white/5 rounded-lg p-3 text-center">
                        <p className="text-xs text-zinc-500">Straddle Cost</p>
                        <p className="text-lg font-mono font-bold">${ivData?.expected_move?.straddle_cost}</p>
                      </div>
                    </div>
                    
                    {/* IV Term Structure Chart */}
                    {ivData?.term_structure && (
                      <div className="h-40 mt-4">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={ivData.term_structure}>
                            <XAxis dataKey="dte" tick={{ fill: '#71717a', fontSize: 10 }} />
                            <YAxis tick={{ fill: '#71717a', fontSize: 10 }} domain={['auto', 'auto']} />
                            <Tooltip 
                              contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                              labelFormatter={(v) => `${v} DTE`}
                            />
                            <Line type="monotone" dataKey="iv" stroke="#eab308" strokeWidth={2} dot={{ fill: '#eab308' }} />
                          </LineChart>
                        </ResponsiveContainer>
                        <p className="text-xs text-zinc-500 text-center mt-1">IV Term Structure (Days to Expiration)</p>
                      </div>
                    )}
                    
                    {ivData?.recommendation && (
                      <div className="mt-4 p-3 bg-primary/10 border border-primary/30 rounded-lg">
                        <p className="text-sm flex items-center gap-2">
                          <Zap className="w-4 h-4 text-primary" />
                          <span className="text-primary font-medium">Strategy Suggestion:</span>
                          <span className="text-zinc-300">{ivData.recommendation}</span>
                        </p>
                      </div>
                    )}
                  </Card>

                  {/* Historical Earnings Performance */}
                  <Card hover={false}>
                    <h3 className="font-semibold mb-4 flex items-center gap-2">
                      <BarChart3 className="w-5 h-5 text-blue-400" />
                      Historical Earnings Performance
                    </h3>
                    
                    {/* Statistics */}
                    <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mb-4">
                      <div className="bg-white/5 rounded p-2 text-center">
                        <p className="text-xs text-zinc-500">Beat Rate</p>
                        <p className="font-bold text-green-400">{detailedData?.statistics?.beat_rate}%</p>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <p className="text-xs text-zinc-500">Avg Surprise</p>
                        <p className={`font-bold ${detailedData?.statistics?.avg_surprise > 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {detailedData?.statistics?.avg_surprise > 0 ? '+' : ''}{detailedData?.statistics?.avg_surprise}%
                        </p>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <p className="text-xs text-zinc-500">Avg Reaction</p>
                        <p className={`font-bold ${detailedData?.statistics?.avg_stock_reaction > 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {detailedData?.statistics?.avg_stock_reaction > 0 ? '+' : ''}{detailedData?.statistics?.avg_stock_reaction}%
                        </p>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <p className="text-xs text-zinc-500">Max Up</p>
                        <p className="font-bold text-green-400">+{detailedData?.statistics?.max_positive_reaction}%</p>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <p className="text-xs text-zinc-500">Max Down</p>
                        <p className="font-bold text-red-400">{detailedData?.statistics?.max_negative_reaction}%</p>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <p className="text-xs text-zinc-500">Avg IV Crush</p>
                        <p className="font-bold text-yellow-400">{detailedData?.statistics?.avg_iv_crush}%</p>
                      </div>
                    </div>
                    
                    {/* Historical Chart */}
                    {detailedData?.detailed_history && (
                      <div className="h-48">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={detailedData.detailed_history.slice(0, 8).reverse()}>
                            <XAxis dataKey="quarter" tick={{ fill: '#71717a', fontSize: 10 }} />
                            <YAxis tick={{ fill: '#71717a', fontSize: 10 }} />
                            <Tooltip 
                              contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                            />
                            <Bar dataKey="eps_surprise_percent" name="EPS Surprise %" radius={[4, 4, 0, 0]}>
                              {detailedData.detailed_history.slice(0, 8).reverse().map((entry, index) => (
                                <Cell key={index} fill={entry.eps_surprise_percent >= 0 ? '#22c55e' : '#ef4444'} />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                        <p className="text-xs text-zinc-500 text-center mt-1">EPS Surprise % by Quarter</p>
                      </div>
                    )}
                    
                    {/* Historical Table */}
                    <div className="mt-4 overflow-x-auto">
                      <table className="data-table text-sm">
                        <thead>
                          <tr>
                            <th>Quarter</th>
                            <th>EPS Est.</th>
                            <th>EPS Act.</th>
                            <th>Surprise</th>
                            <th>Stock Move</th>
                            <th>IV Crush</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detailedData?.detailed_history?.slice(0, 6).map((h, idx) => (
                            <tr key={idx}>
                              <td className="text-zinc-400">{h.quarter}</td>
                              <td className="font-mono">${h.eps_estimate?.toFixed(2)}</td>
                              <td className="font-mono">${h.eps_actual?.toFixed(2)}</td>
                              <td>
                                <PriceDisplay value={h.eps_surprise_percent} />
                              </td>
                              <td>
                                <PriceDisplay value={h.stock_reaction_1d} />
                              </td>
                              <td className="font-mono text-yellow-400">
                                {(h.iv_before - h.iv_after).toFixed(0)}%
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Card>
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default EarningsCalendarPage;
