import React, { useState, useEffect, useCallback } from 'react';
import { 
  Award, 
  TrendingUp, 
  TrendingDown, 
  RefreshCw, 
  ChevronDown,
  ChevronUp,
  Shield,
  AlertTriangle,
  Loader2,
  Info
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';

// Grade color mapping
const getGradeColor = (grade) => {
  if (!grade) return 'text-zinc-400';
  if (grade.startsWith('A')) return 'text-emerald-400';
  if (grade.startsWith('B')) return 'text-cyan-400';
  if (grade.startsWith('C')) return 'text-yellow-400';
  if (grade.startsWith('D')) return 'text-orange-400';
  return 'text-red-400';
};

const getGradeBg = (grade) => {
  if (!grade) return 'bg-zinc-500/10';
  if (grade.startsWith('A')) return 'bg-emerald-500/10 border-emerald-500/30';
  if (grade.startsWith('B')) return 'bg-cyan-500/10 border-cyan-500/30';
  if (grade.startsWith('C')) return 'bg-yellow-500/10 border-yellow-500/30';
  if (grade.startsWith('D')) return 'bg-orange-500/10 border-orange-500/30';
  return 'bg-red-500/10 border-red-500/30';
};

const getSignalIcon = (signal) => {
  if (signal === 'LONG') return <TrendingUp className="w-3 h-3 text-emerald-400" />;
  if (signal === 'SHORT') return <TrendingDown className="w-3 h-3 text-red-400" />;
  return <Shield className="w-3 h-3 text-zinc-400" />;
};

// Individual quality stock card
const QualityStockCard = ({ stock, onClick }) => {
  const grade = stock.grade || 'C';
  const score = stock.composite_score || 0;
  const signal = stock.quality_signal || 'NEUTRAL';
  const isHighQuality = stock.is_high_quality;
  const isLowQuality = stock.is_low_quality;
  
  return (
    <div 
      onClick={() => onClick?.(stock)}
      className={`p-3 rounded-lg border cursor-pointer transition-all hover:border-cyan-500/50 ${
        isHighQuality 
          ? 'border-emerald-500/30 bg-emerald-500/5' 
          : isLowQuality 
            ? 'border-red-500/30 bg-red-500/5'
            : 'border-white/10 bg-zinc-900/50'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-bold text-white">{stock.symbol}</span>
          <span className={`text-xs font-bold px-1.5 py-0.5 rounded border ${getGradeBg(grade)} ${getGradeColor(grade)}`}>
            {grade}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {getSignalIcon(signal)}
          <span className={`text-xs font-mono ${
            signal === 'LONG' ? 'text-emerald-400' : signal === 'SHORT' ? 'text-red-400' : 'text-zinc-400'
          }`}>
            {signal}
          </span>
        </div>
      </div>
      
      {/* Quality Metrics Bar */}
      <div className="grid grid-cols-4 gap-1 mb-2">
        {['accruals', 'roe', 'cfa', 'da'].map((metric) => {
          const value = stock.component_scores?.[metric] || 0;
          const color = value >= 70 ? 'bg-emerald-500' : value >= 40 ? 'bg-yellow-500' : 'bg-red-500';
          return (
            <div key={metric} className="flex flex-col">
              <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
                <div 
                  className={`h-full ${color} transition-all`}
                  style={{ width: `${value}%` }}
                />
              </div>
              <span className="text-[8px] text-zinc-500 uppercase mt-0.5 text-center">
                {metric === 'da' ? 'D/A' : metric === 'cfa' ? 'CF/A' : metric.toUpperCase()}
              </span>
            </div>
          );
        })}
      </div>
      
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-500">Quality Score</span>
        <span className="font-mono text-cyan-400">{Math.round(score)}/400</span>
      </div>
    </div>
  );
};

// Main Quality Panel Component
const QualityPanel = ({ opportunities = [], onTickerSelect }) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [qualityData, setQualityData] = useState([]);
  const [filterMode, setFilterMode] = useState('all'); // all, high, low
  const [showLeaderboard, setShowLeaderboard] = useState(false);
  const [leaderboard, setLeaderboard] = useState([]);

  // Fetch quality scores for opportunities
  const fetchQualityScores = useCallback(async () => {
    if (!opportunities.length) {
      setQualityData([]);
      return;
    }

    setIsLoading(true);
    try {
      const symbols = opportunities.map(o => o.symbol).filter(Boolean).slice(0, 20);
      
      // Fetch quality scores for each symbol
      const scores = await Promise.all(
        symbols.map(async (symbol) => {
          try {
            const res = await api.get(`/api/quality/score/${symbol}`);
            return res.data?.data ? { ...res.data.data, symbol } : null;
          } catch {
            return null;
          }
        })
      );
      
      setQualityData(scores.filter(Boolean));
    } catch (err) {
      console.error('Error fetching quality scores:', err);
    } finally {
      setIsLoading(false);
    }
  }, [opportunities]);

  // Fetch leaderboard
  const fetchLeaderboard = useCallback(async () => {
    try {
      const res = await api.get('/api/quality/leaderboard?limit=10');
      setLeaderboard(res.data?.leaderboard || []);
    } catch (err) {
      console.error('Error fetching leaderboard:', err);
    }
  }, []);

  useEffect(() => {
    if (opportunities.length > 0) {
      fetchQualityScores();
    }
  }, [opportunities, fetchQualityScores]);

  useEffect(() => {
    if (showLeaderboard && leaderboard.length === 0) {
      fetchLeaderboard();
    }
  }, [showLeaderboard, leaderboard.length, fetchLeaderboard]);

  // Filter data based on mode
  const filteredData = qualityData.filter(stock => {
    if (filterMode === 'high') return stock.is_high_quality;
    if (filterMode === 'low') return stock.is_low_quality;
    return true;
  });

  // Stats
  const highQualityCount = qualityData.filter(s => s.is_high_quality).length;
  const lowQualityCount = qualityData.filter(s => s.is_low_quality).length;
  const avgGrade = qualityData.length > 0 
    ? Math.round(qualityData.reduce((sum, s) => sum + (s.percentile_rank || 50), 0) / qualityData.length)
    : 0;

  const handleStockClick = (stock) => {
    if (onTickerSelect) {
      // Find the full opportunity data
      const opp = opportunities.find(o => o.symbol === stock.symbol);
      if (opp) {
        onTickerSelect(opp);
      }
    }
  };

  if (!isExpanded) {
    return (
      <div className="bg-[#0A0A0A] border border-white/10 rounded-lg p-3">
        <button 
          onClick={() => setIsExpanded(true)}
          className="w-full flex items-center justify-between"
        >
          <div className="flex items-center gap-2">
            <Award className="w-5 h-5 text-amber-400" />
            <span className="text-sm font-semibold uppercase tracking-wider text-white">Quality Factor</span>
            {qualityData.length > 0 && (
              <span className="text-xs text-zinc-500">({highQualityCount} high / {lowQualityCount} low)</span>
            )}
          </div>
          <ChevronDown className="w-4 h-4 text-zinc-400" />
        </button>
      </div>
    );
  }

  return (
    <div className="bg-[#0A0A0A] border border-white/10 rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <button 
          onClick={() => setIsExpanded(false)}
          className="flex items-center gap-2"
        >
          <Award className="w-5 h-5 text-amber-400" />
          <span className="text-sm font-semibold uppercase tracking-wider text-white">Quality Factor</span>
          <ChevronUp className="w-4 h-4 text-zinc-400" />
        </button>
        
        <div className="flex items-center gap-2">
          {/* Toggle Leaderboard */}
          <button
            onClick={() => setShowLeaderboard(!showLeaderboard)}
            className={`px-2 py-1 text-xs rounded ${
              showLeaderboard ? 'bg-amber-500/20 text-amber-400' : 'bg-zinc-800 text-zinc-400'
            }`}
          >
            Leaderboard
          </button>
          
          {/* Refresh */}
          <button
            onClick={fetchQualityScores}
            disabled={isLoading}
            className="p-1.5 rounded bg-zinc-800 text-zinc-400 hover:text-white transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Info Banner */}
      <div className="flex items-start gap-2 p-2 rounded bg-amber-500/5 border border-amber-500/20 mb-4">
        <Info className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-zinc-400">
          <span className="text-amber-400 font-medium">Earnings Quality</span> scores based on 4 factors: 
          Accruals, ROE, Cash Flow/Assets, Debt/Assets. 
          High quality stocks tend to outperform, especially in bear markets.
        </p>
      </div>

      {showLeaderboard ? (
        // Leaderboard View
        <div>
          <h4 className="text-xs text-zinc-500 uppercase mb-2">Top Quality Stocks</h4>
          {leaderboard.length === 0 ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
            </div>
          ) : (
            <div className="space-y-2 max-h-[300px] overflow-y-auto">
              {leaderboard.map((stock, idx) => (
                <div 
                  key={stock.symbol}
                  className="flex items-center justify-between p-2 rounded bg-zinc-900/50 border border-white/5"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-zinc-500 w-4">#{idx + 1}</span>
                    <span className="font-bold text-white">{stock.symbol}</span>
                    <span className={`text-xs font-bold px-1.5 py-0.5 rounded border ${getGradeBg(stock.grade)} ${getGradeColor(stock.grade)}`}>
                      {stock.grade}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-zinc-400">{Math.round(stock.composite_score)}/400</span>
                    {getSignalIcon(stock.quality_signal)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        // Opportunities Quality View
        <div>
          {/* Stats Row */}
          {qualityData.length > 0 && (
            <div className="grid grid-cols-3 gap-2 mb-4">
              <div className="p-2 rounded bg-emerald-500/5 border border-emerald-500/20 text-center">
                <p className="text-lg font-bold text-emerald-400">{highQualityCount}</p>
                <p className="text-[10px] text-zinc-500 uppercase">High Quality</p>
              </div>
              <div className="p-2 rounded bg-zinc-800/50 border border-white/10 text-center">
                <p className="text-lg font-bold text-white">{avgGrade}%</p>
                <p className="text-[10px] text-zinc-500 uppercase">Avg Percentile</p>
              </div>
              <div className="p-2 rounded bg-red-500/5 border border-red-500/20 text-center">
                <p className="text-lg font-bold text-red-400">{lowQualityCount}</p>
                <p className="text-[10px] text-zinc-500 uppercase">Low Quality</p>
              </div>
            </div>
          )}

          {/* Filter Tabs */}
          <div className="flex gap-1 mb-3">
            {[
              { key: 'all', label: 'All' },
              { key: 'high', label: 'High Quality', icon: TrendingUp },
              { key: 'low', label: 'Low Quality', icon: AlertTriangle }
            ].map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setFilterMode(key)}
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
                  filterMode === key 
                    ? 'bg-cyan-500/20 text-cyan-400' 
                    : 'bg-zinc-800 text-zinc-400 hover:text-white'
                }`}
              >
                {Icon && <Icon className="w-3 h-3" />}
                {label}
              </button>
            ))}
          </div>

          {/* Quality Cards */}
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-cyan-400" />
              <span className="ml-2 text-sm text-zinc-400">Analyzing quality...</span>
            </div>
          ) : filteredData.length === 0 ? (
            <div className="text-center py-6">
              <Award className="w-10 h-10 text-zinc-600 mx-auto mb-2" />
              <p className="text-zinc-400 text-sm">
                {qualityData.length === 0 
                  ? 'Run a scan to see quality scores'
                  : 'No stocks match this filter'}
              </p>
            </div>
          ) : (
            <div className="grid md:grid-cols-2 gap-2 max-h-[350px] overflow-y-auto">
              {filteredData.map((stock) => (
                <QualityStockCard 
                  key={stock.symbol} 
                  stock={stock} 
                  onClick={handleStockClick}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default QualityPanel;
