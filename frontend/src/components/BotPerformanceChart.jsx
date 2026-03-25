/**
 * BotPerformanceChart - Custom proprietary equity curve chart
 * 
 * Features:
 * - Custom SVG-based chart (no external dependencies)
 * - Equity curve with gradient fill
 * - Trade markers (green=win, red=loss)
 * - Time range toggle: Today | Week | Month | YTD | All
 * - Quick stats: Trades, Win Rate, Avg R, Best, Worst
 * - Hover tooltips showing trade details
 * - Auto-refresh every 30 seconds
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { safePolling } from '../utils/safePolling';
import { motion } from 'framer-motion';
import { TrendingUp, TrendingDown, ChevronRight, Activity } from 'lucide-react';
import api, { safeGet, safePost } from '../utils/api';

const AUTO_REFRESH_INTERVAL = 30000; // 30 seconds

// Custom Time Range Button
const TimeRangeButton = ({ active, onClick, children }) => (
  <button
    onClick={onClick}
    className={`px-3 py-1 rounded text-xs font-medium transition-all ${
      active 
        ? 'bg-cyan-400 text-black' 
        : 'bg-white/10 text-zinc-400 hover:bg-white/20 hover:text-white'
    }`}
  >
    {children}
  </button>
);

// Stat Item Display
const StatItem = ({ label, value, color = 'white', prefix = '', suffix = '' }) => (
  <span className="text-zinc-400 text-xs">
    {label}: <span className={`text-${color} font-mono`}>{prefix}{value}{suffix}</span>
  </span>
);

// Custom SVG Chart Component
const CustomEquityChart = ({ data, width = 800, height = 200 }) => {
  const [hoveredPoint, setHoveredPoint] = useState(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  
  // Calculate chart dimensions with padding
  const padding = { top: 20, right: 20, bottom: 30, left: 60 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  
  // Calculate min/max values for scaling
  const chartMetrics = useMemo(() => {
    if (!data || data.length === 0) {
      return { minValue: 0, maxValue: 100, minTime: 0, maxTime: 1 };
    }
    
    const values = data.map(d => d.value);
    const times = data.map(d => d.time);
    
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const valueRange = maxValue - minValue || 1;
    
    return {
      minValue: minValue - valueRange * 0.1,
      maxValue: maxValue + valueRange * 0.1,
      minTime: Math.min(...times),
      maxTime: Math.max(...times),
    };
  }, [data]);
  
  // Scale functions
  const scaleX = useCallback((time) => {
    const { minTime, maxTime } = chartMetrics;
    const range = maxTime - minTime || 1;
    return padding.left + ((time - minTime) / range) * chartWidth;
  }, [chartMetrics, chartWidth, padding.left]);
  
  const scaleY = useCallback((value) => {
    const { minValue, maxValue } = chartMetrics;
    const range = maxValue - minValue || 1;
    return padding.top + chartHeight - ((value - minValue) / range) * chartHeight;
  }, [chartMetrics, chartHeight, padding.top]);
  
  // Generate path for the line
  const linePath = useMemo(() => {
    if (!data || data.length === 0) return '';
    
    return data.map((point, i) => {
      const x = scaleX(point.time);
      const y = scaleY(point.value);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    }).join(' ');
  }, [data, scaleX, scaleY]);
  
  // Generate path for the gradient fill area
  const areaPath = useMemo(() => {
    if (!data || data.length === 0) return '';
    
    const firstX = scaleX(data[0].time);
    const lastX = scaleX(data[data.length - 1].time);
    const bottomY = padding.top + chartHeight;
    
    return `${linePath} L ${lastX} ${bottomY} L ${firstX} ${bottomY} Z`;
  }, [data, linePath, scaleX, padding.top, chartHeight]);
  
  // Generate Y-axis labels
  const yAxisLabels = useMemo(() => {
    const { minValue, maxValue } = chartMetrics;
    const range = maxValue - minValue;
    const labels = [];
    const steps = 4;
    
    for (let i = 0; i <= steps; i++) {
      const value = minValue + (range * i / steps);
      labels.push({
        value: value,
        y: scaleY(value),
        label: value >= 0 ? `$${Math.abs(value).toFixed(0)}` : `-$${Math.abs(value).toFixed(0)}`
      });
    }
    
    return labels;
  }, [chartMetrics, scaleY]);
  
  // Generate X-axis labels (time)
  const xAxisLabels = useMemo(() => {
    if (!data || data.length === 0) return [];
    
    const labels = [];
    const steps = Math.min(5, data.length);
    const stepSize = Math.floor(data.length / steps);
    
    for (let i = 0; i < data.length; i += stepSize) {
      const point = data[i];
      const date = new Date(point.time * 1000);
      labels.push({
        x: scaleX(point.time),
        label: date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      });
    }
    
    return labels;
  }, [data, scaleX]);
  
  // Handle mouse move for tooltip
  const handleMouseMove = (e) => {
    if (!data || data.length === 0) return;
    
    const rect = e.currentTarget.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    
    setMousePos({ x: mouseX, y: mouseY });
    
    // Find closest data point
    let closest = null;
    let closestDist = Infinity;
    
    data.forEach((point, index) => {
      const x = scaleX(point.time);
      const dist = Math.abs(x - mouseX);
      if (dist < closestDist && dist < 30) {
        closestDist = dist;
        closest = { ...point, index, x, y: scaleY(point.value) };
      }
    });
    
    setHoveredPoint(closest);
  };
  
  // Determine if overall trend is positive
  const isPositive = data && data.length >= 2 
    ? data[data.length - 1].value >= data[0].value 
    : true;
  
  const gradientId = `equity-gradient-${Math.random().toString(36).substr(2, 9)}`;
  const glowId = `equity-glow-${Math.random().toString(36).substr(2, 9)}`;
  
  return (
    <svg 
      width="100%" 
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="overflow-visible"
      onMouseMove={handleMouseMove}
      onMouseLeave={() => setHoveredPoint(null)}
    >
      {/* Definitions */}
      <defs>
        {/* Gradient fill */}
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={isPositive ? '#00FF94' : '#FF2E2E'} stopOpacity="0.3" />
          <stop offset="100%" stopColor={isPositive ? '#00FF94' : '#FF2E2E'} stopOpacity="0" />
        </linearGradient>
        
        {/* Glow effect */}
        <filter id={glowId} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      
      {/* Grid lines */}
      {yAxisLabels.map((label, i) => (
        <line
          key={`grid-${i}`}
          x1={padding.left}
          y1={label.y}
          x2={width - padding.right}
          y2={label.y}
          stroke="rgba(255,255,255,0.05)"
          strokeDasharray="4,4"
        />
      ))}
      
      {/* Y-axis labels */}
      {yAxisLabels.map((label, i) => (
        <text
          key={`y-label-${i}`}
          x={padding.left - 10}
          y={label.y + 4}
          textAnchor="end"
          fill="#6B7280"
          fontSize="10"
          fontFamily="monospace"
        >
          {label.label}
        </text>
      ))}
      
      {/* X-axis labels */}
      {xAxisLabels.map((label, i) => (
        <text
          key={`x-label-${i}`}
          x={label.x}
          y={height - 8}
          textAnchor="middle"
          fill="#6B7280"
          fontSize="10"
          fontFamily="monospace"
        >
          {label.label}
        </text>
      ))}
      
      {/* Area fill */}
      {data && data.length > 0 && (
        <path
          d={areaPath}
          fill={`url(#${gradientId})`}
        />
      )}
      
      {/* Line */}
      {data && data.length > 0 && (
        <path
          d={linePath}
          fill="none"
          stroke={isPositive ? '#00FF94' : '#FF2E2E'}
          strokeWidth="2"
          filter={`url(#${glowId})`}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
      
      {/* Trade markers */}
      {data && data.map((point, i) => {
        if (!point.pnl) return null;
        const x = scaleX(point.time);
        const y = scaleY(point.value);
        const isWin = point.pnl >= 0;
        
        return (
          <g key={`marker-${i}`}>
            <circle
              cx={x}
              cy={y}
              r={hoveredPoint?.index === i ? 6 : 4}
              fill={isWin ? '#00FF94' : '#FF2E2E'}
              opacity={hoveredPoint?.index === i ? 1 : 0.7}
              className="transition-all duration-150"
            />
            {/* Outer glow for markers */}
            <circle
              cx={x}
              cy={y}
              r={hoveredPoint?.index === i ? 10 : 8}
              fill="none"
              stroke={isWin ? '#00FF94' : '#FF2E2E'}
              strokeWidth="1"
              opacity={hoveredPoint?.index === i ? 0.5 : 0.2}
            />
          </g>
        );
      })}
      
      {/* Hover crosshair */}
      {hoveredPoint && (
        <>
          <line
            x1={hoveredPoint.x}
            y1={padding.top}
            x2={hoveredPoint.x}
            y2={padding.top + chartHeight}
            stroke="rgba(0,255,148,0.3)"
            strokeDasharray="4,4"
          />
          <line
            x1={padding.left}
            y1={hoveredPoint.y}
            x2={width - padding.right}
            y2={hoveredPoint.y}
            stroke="rgba(0,255,148,0.3)"
            strokeDasharray="4,4"
          />
        </>
      )}
      
      {/* Tooltip */}
      {hoveredPoint && (
        <g>
          <rect
            x={Math.min(hoveredPoint.x + 10, width - 130)}
            y={Math.max(hoveredPoint.y - 50, 10)}
            width="120"
            height="45"
            rx="6"
            fill="rgba(24,24,27,0.95)"
            stroke="rgba(255,255,255,0.1)"
          />
          <text
            x={Math.min(hoveredPoint.x + 20, width - 120)}
            y={Math.max(hoveredPoint.y - 30, 30)}
            fill="#fff"
            fontSize="12"
            fontWeight="bold"
          >
            ${hoveredPoint.value?.toFixed(2)}
          </text>
          {hoveredPoint.pnl !== undefined && (
            <text
              x={Math.min(hoveredPoint.x + 20, width - 120)}
              y={Math.max(hoveredPoint.y - 15, 45)}
              fill={hoveredPoint.pnl >= 0 ? '#00FF94' : '#FF2E2E'}
              fontSize="11"
            >
              {hoveredPoint.pnl >= 0 ? '+' : ''}${hoveredPoint.pnl?.toFixed(2)}
            </text>
          )}
          <text
            x={Math.min(hoveredPoint.x + 20, width - 120)}
            y={Math.max(hoveredPoint.y, 60)}
            fill="#6B7280"
            fontSize="10"
          >
            {new Date(hoveredPoint.time * 1000).toLocaleTimeString()}
          </text>
        </g>
      )}
      
      {/* No data message */}
      {(!data || data.length === 0) && (
        <text
          x={width / 2}
          y={height / 2}
          textAnchor="middle"
          fill="#6B7280"
          fontSize="14"
        >
          No trading data available
        </text>
      )}
    </svg>
  );
};

// Main Component
const BotPerformanceChart = ({ 
  trades = [],
  todayPnl = 0,
  className = '',
  onViewFullAnalytics,
  autoRefresh = true,
  compact = false
}) => {
  const [timeRange, setTimeRange] = useState('today');
  const [chartData, setChartData] = useState([]);
  const [stats, setStats] = useState({
    totalTrades: 0,
    winRate: 0,
    avgR: 0,
    bestTrade: 0,
    worstTrade: 0,
    realizedPnl: 0,
    unrealizedPnl: 0,
    openPositions: 0,
  });
  const [isLoading, setIsLoading] = useState(false);
  const cacheRef = useRef({}); // Cache per time range for instant switching

  // Fetch equity curve data from API
  const fetchEquityCurve = useCallback(async () => {
    // If cached, use cache immediately for instant visual switch
    if (cacheRef.current[timeRange]) {
      const cached = cacheRef.current[timeRange];
      setChartData(cached.chartData);
      setStats(cached.stats);
    }
    
    try {
      const data = await safeGet(`/api/trading-bot/performance/equity-curve?period=${timeRange}`);
      if (data?.success) {
          const equityData = data.equity_curve.map(point => ({
            time: Math.floor(point.time / 1000),
            value: point.value,
            pnl: point.pnl || 0,
          }));
          
          const summary = data.summary || {};
          const newStats = {
            totalTrades: summary.trades_count || 0,
            winRate: summary.win_rate || 0,
            avgR: summary.avg_r || 0,
            bestTrade: summary.best_trade || 0,
            worstTrade: summary.worst_trade || 0,
            realizedPnl: summary.realized_pnl || 0,
            unrealizedPnl: summary.unrealized_pnl || 0,
            openPositions: summary.open_positions || 0,
          };
          
          // Cache for this time range
          cacheRef.current[timeRange] = { chartData: equityData, stats: newStats };
          
          setChartData(equityData);
          setStats(newStats);
      }
    } catch (err) {
      console.error('Failed to fetch equity curve:', err);
      if (chartData.length === 0) {
        generateDemoData();
      }
    } finally {
      setIsLoading(false);
    }
  }, [timeRange]);

  // Initial fetch and auto-refresh
  useEffect(() => {
    // Show loading briefly for visual feedback on time range switch
    setIsLoading(true);
    fetchEquityCurve();
    
    if (autoRefresh) {
      return safePolling(fetchEquityCurve, AUTO_REFRESH_INTERVAL, { immediate: false });
    }
  }, [fetchEquityCurve, autoRefresh]);

  // Generate demo data for display when no real trades
  const generateDemoData = () => {
    const now = Math.floor(Date.now() / 1000);
    const hourInSec = 3600;
    
    const demoData = [
      { time: now - 5 * hourInSec, value: 0, pnl: 0 },
      { time: now - 4 * hourInSec, value: 842, pnl: 842 },
      { time: now - 3 * hourInSec, value: 2098, pnl: 1256 },
      { time: now - 2 * hourInSec, value: 1675, pnl: -423 },
      { time: now - 1 * hourInSec, value: 2847, pnl: 1172 },
      { time: now, value: 2500, pnl: -347 },
    ];
    
    setChartData(demoData);
    setStats({
      totalTrades: 5,
      winRate: 60,
      avgR: 1.5,
      bestTrade: 1256,
      worstTrade: -423,
      realizedPnl: 2500,
      unrealizedPnl: 0,
      openPositions: 0,
    });
  };

  const isPositive = todayPnl >= 0;
  
  // Compact mode - smaller version for sidebar
  if (compact) {
    return (
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className={`relative overflow-hidden rounded-xl p-3 w-full ${className} ${
          isPositive 
            ? 'bg-gradient-to-br from-emerald-500/5 via-zinc-900/50 to-zinc-900/50 border border-emerald-500/20' 
            : 'bg-gradient-to-br from-rose-500/5 via-zinc-900/50 to-zinc-900/50 border border-rose-500/20'
        }`}
        data-testid="bot-performance-compact"
      >
        {/* Header - Compact */}
        <div className="relative flex justify-between items-center mb-2">
          <div className="flex items-center gap-2">
            {isPositive ? (
              <TrendingUp className="w-4 h-4 text-emerald-400" />
            ) : (
              <TrendingDown className="w-4 h-4 text-red-400" />
            )}
            <span className="font-bold text-sm text-white">BOT PERFORMANCE</span>
            {isLoading && (
              <Activity className="w-3 h-3 text-cyan-400 animate-spin" />
            )}
          </div>
          <span className={`font-mono text-base font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}${todayPnl.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </span>
        </div>
        
        {/* Chart - Full Width */}
        <div className="w-full h-[100px] bg-gradient-to-b from-zinc-800/30 to-transparent rounded-lg overflow-hidden mb-3">
          <CustomEquityChart data={chartData} width={400} height={100} />
        </div>
        
        {/* Stats Row - Horizontal */}
        <div className="grid grid-cols-4 gap-2 mb-2">
          <div className="text-center p-2 rounded-lg bg-black/20">
            <p className="text-[9px] text-zinc-500 uppercase">Trades</p>
            <p className="text-base font-bold text-white">{stats.totalTrades}</p>
          </div>
          <div className="text-center p-2 rounded-lg bg-black/20">
            <p className="text-[9px] text-zinc-500 uppercase">Win Rate</p>
            <p className={`text-base font-bold ${stats.winRate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
              {stats.winRate.toFixed(0)}%
            </p>
          </div>
          <div className="text-center p-2 rounded-lg bg-black/20">
            <p className="text-[9px] text-zinc-500 uppercase">Open</p>
            <p className="text-base font-bold text-cyan-400">{stats.openPositions || 0}</p>
          </div>
          <div className="text-center p-2 rounded-lg bg-black/20">
            <p className="text-[9px] text-zinc-500 uppercase">Unrealized</p>
            <p className={`text-base font-bold ${stats.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {stats.unrealizedPnl >= 0 ? '+' : ''}{Math.abs(stats.unrealizedPnl || 0).toFixed(0)}
            </p>
          </div>
        </div>
        
        {/* Time Range - Full Width */}
        <div className="flex gap-1 justify-between">
          {['today', 'week', 'month', 'ytd'].map(range => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              className={`flex-1 px-2 py-1 text-[10px] rounded transition-all ${
                timeRange === range 
                  ? 'bg-cyan-400/20 text-cyan-400 font-medium' 
                  : 'text-zinc-500 hover:text-zinc-400 hover:bg-white/5'
              }`}
            >
              {range === 'ytd' ? 'YTD' : range.charAt(0).toUpperCase() + range.slice(1)}
            </button>
          ))}
        </div>
      </motion.div>
    );
  }
  
  // Full mode
  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`relative overflow-hidden rounded-xl p-4 ${className} ${
        isPositive 
          ? 'bg-gradient-to-br from-emerald-500/5 via-zinc-900/50 to-zinc-900/50 border border-emerald-500/20' 
          : 'bg-gradient-to-br from-rose-500/5 via-zinc-900/50 to-zinc-900/50 border border-rose-500/20'
      }`}
    >
      {/* Subtle glow effect based on P&L */}
      <div className={`absolute top-0 left-0 w-32 h-32 rounded-full blur-3xl opacity-20 pointer-events-none ${
        isPositive ? 'bg-emerald-500' : 'bg-rose-500'
      }`} />
      
      {/* Header */}
      <div className="relative flex justify-between items-center mb-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            {isPositive ? (
              <TrendingUp className="w-5 h-5 text-emerald-400" />
            ) : (
              <TrendingDown className="w-5 h-5 text-red-400" />
            )}
            <h2 className="font-bold text-lg">BOT PERFORMANCE</h2>
          </div>
          <span className={`font-mono text-lg ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}${todayPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} today
          </span>
          {isLoading && (
            <Activity className="w-4 h-4 text-cyan-400 animate-spin" />
          )}
        </div>
        
        {/* Time Range Toggle */}
        <div className="flex gap-1">
          {['today', 'week', 'month', 'ytd', 'all'].map(range => (
            <TimeRangeButton
              key={range}
              active={timeRange === range}
              onClick={() => setTimeRange(range)}
            >
              {range === 'ytd' ? 'YTD' : range.charAt(0).toUpperCase() + range.slice(1)}
            </TimeRangeButton>
          ))}
        </div>
      </div>
      
      {/* Custom Chart */}
      <div className="w-full h-[200px] bg-gradient-to-b from-zinc-800/30 to-transparent rounded-lg overflow-hidden">
        <CustomEquityChart data={chartData} width={800} height={200} />
      </div>
      
      {/* Stats Row */}
      <div className="flex justify-between items-center mt-3">
        <div className="flex gap-4 flex-wrap">
          <StatItem label="Trades" value={stats.totalTrades} />
          <StatItem 
            label="Win Rate" 
            value={`${stats.winRate.toFixed(0)}%`} 
            color={stats.winRate >= 50 ? 'emerald-400' : 'red-400'} 
          />
          {stats.openPositions > 0 && (
            <StatItem 
              label="Open" 
              value={stats.openPositions}
              color="cyan-400"
            />
          )}
          {stats.unrealizedPnl !== 0 && (
            <StatItem 
              label="Unrealized" 
              value={Math.abs(stats.unrealizedPnl).toFixed(0)} 
              prefix={stats.unrealizedPnl >= 0 ? '+$' : '-$'}
              color={stats.unrealizedPnl >= 0 ? 'emerald-400' : 'red-400'} 
            />
          )}
          {stats.realizedPnl !== 0 && (
            <StatItem 
              label="Realized" 
              value={Math.abs(stats.realizedPnl).toFixed(0)} 
              prefix={stats.realizedPnl >= 0 ? '+$' : '-$'}
              color={stats.realizedPnl >= 0 ? 'emerald-400' : 'red-400'} 
            />
          )}
          {stats.bestTrade > 0 && (
            <StatItem 
              label="Best" 
              value={stats.bestTrade.toFixed(0)} 
              prefix="+$" 
              color="emerald-400" 
            />
          )}
          {stats.worstTrade < 0 && (
            <StatItem 
              label="Worst" 
              value={Math.abs(stats.worstTrade).toFixed(0)} 
              prefix="-$" 
              color="red-400" 
            />
          )}
        </div>
        
        {onViewFullAnalytics && (
          <button 
            onClick={onViewFullAnalytics}
            className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
          >
            View Full Analytics
            <ChevronRight className="w-3 h-3" />
          </button>
        )}
      </div>
    </motion.div>
  );
};

export default BotPerformanceChart;
