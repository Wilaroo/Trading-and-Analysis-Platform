import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Target,
  X,
  Loader2,
  AlertTriangle,
  Sparkles,
  Bot,
  CheckCircle2,
  ExternalLink
} from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api from '../utils/api';
import { HelpTooltip } from './HelpTooltip';
import { formatPrice, formatPercent, formatVolume } from '../utils/tradingUtils';
import { TickerAwareText } from '../utils/tickerUtils';

const TickerDetailModal = ({ ticker, onClose, onTrade, onAskAI }) => {
  const [analysis, setAnalysis] = useState(null);
  const [historicalData, setHistoricalData] = useState(null);
  const [qualityData, setQualityData] = useState(null);
  const [earningsData, setEarningsData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [showTradingLines, setShowTradingLines] = useState(true);
  const [chartError, setChartError] = useState(null);
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);

  useEffect(() => {
    if (!ticker?.symbol) return;
    
    const fetchData = async () => {
      setLoading(true);
      setChartError(null);
      
      const fetchWithRetry = async (fetcher, retries = 2, delay = 1000) => {
        for (let i = 0; i <= retries; i++) {
          try {
            return await fetcher();
          } catch (err) {
            if (i === retries) throw err;
            await new Promise(r => setTimeout(r, delay));
          }
        }
      };
      
      try {
        const [analysisRes, histRes, qualityRes, earningsRes] = await Promise.all([
          fetchWithRetry(() => api.get(`/api/ib/analysis/${ticker.symbol}`)).catch(() => ({ data: null })),
          fetchWithRetry(() => api.get(`/api/ib/historical/${ticker.symbol}?duration=1 D&bar_size=5 mins`)).catch((err) => {
            const errorMsg = err.response?.data?.detail?.message || err.response?.data?.detail || 'Unable to load chart data';
            if (err.response?.data?.ib_busy || errorMsg.includes('busy')) {
              setChartError('IB Gateway is busy with a scan. Using cached/Alpaca data.');
            } else {
              setChartError(errorMsg);
            }
            return { data: { bars: [] } };
          }),
          fetchWithRetry(() => api.get(`/api/quality/score/${ticker.symbol}`)).catch(() => ({ data: null })),
          fetchWithRetry(() => api.get(`/api/newsletter/earnings/${ticker.symbol}`)).catch(() => ({ data: null }))
        ]);
        
        setAnalysis(analysisRes.data);
        setHistoricalData(histRes.data?.bars || []);
        setQualityData(qualityRes.data);
        setEarningsData(earningsRes.data);
      } catch (err) {
        setChartError('Failed to load data. Please try again.');
      }
      setLoading(false);
    };
    
    fetchData();
  }, [ticker?.symbol]);

  // Create chart when tab changes to chart
  useEffect(() => {
    if (activeTab !== 'chart' || !chartContainerRef.current) return;
    
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    }
    
    const timer = setTimeout(() => {
      if (!chartContainerRef.current) return;
      
      const container = chartContainerRef.current;
      const width = container.clientWidth || 700;
      const height = container.clientHeight || 300;
      
      try {
        const chart = LightweightCharts.createChart(container, {
          width,
          height,
          layout: { background: { type: 'solid', color: '#0A0A0A' }, textColor: '#9CA3AF' },
          grid: { vertLines: { color: '#1F2937' }, horzLines: { color: '#1F2937' } },
          timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#374151' },
          rightPriceScale: { borderColor: '#374151' },
          crosshair: { mode: 1, vertLine: { color: '#00E5FF', width: 1, style: 2 }, horzLine: { color: '#00E5FF', width: 1, style: 2 } },
        });
        
        chartRef.current = chart;
        
        const candleSeries = chart.addCandlestickSeries({
          upColor: '#00FF94', downColor: '#FF2E2E',
          borderUpColor: '#00FF94', borderDownColor: '#FF2E2E',
          wickUpColor: '#00FF94', wickDownColor: '#FF2E2E',
        });
        candleSeriesRef.current = candleSeries;
        
        const handleResize = () => {
          if (chartRef.current && container) {
            chartRef.current.applyOptions({ width: container.clientWidth, height: container.clientHeight || 300 });
          }
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
      } catch (err) {
        setChartError('Failed to initialize chart');
      }
    }, 150);
    
    return () => {
      clearTimeout(timer);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        candleSeriesRef.current = null;
      }
    };
  }, [activeTab]);

  // Set chart data
  useEffect(() => {
    if (!candleSeriesRef.current || !historicalData || historicalData.length === 0) return;
    
    try {
      const chartData = historicalData.map(bar => ({
        time: Math.floor(new Date(bar.time || bar.date || bar.timestamp).getTime() / 1000),
        open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close),
      })).sort((a, b) => a.time - b.time);
      
      candleSeriesRef.current.setData(chartData);
      if (chartRef.current) chartRef.current.timeScale().fitContent();
      
      if (showTradingLines && analysis?.trading_summary) {
        const ts = analysis.trading_summary;
        if (ts.entry) candleSeriesRef.current.createPriceLine({ price: ts.entry, color: '#00E5FF', lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'Entry' });
        if (ts.stop_loss) candleSeriesRef.current.createPriceLine({ price: ts.stop_loss, color: '#FF2E2E', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: 'Stop' });
        if (ts.target) candleSeriesRef.current.createPriceLine({ price: ts.target, color: '#00FF94', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: 'Target' });
      }
    } catch (err) {
      console.error('Error setting chart data:', err);
    }
  }, [historicalData, analysis, showTradingLines, activeTab]);

  if (!ticker) return null;

  const quote = analysis?.quote || ticker.quote || ticker;
  const tradingSummary = analysis?.trading_summary || {};
  const scores = analysis?.scores || {};
  const technicals = analysis?.technicals || {};
  const fundamentals = analysis?.fundamentals || {};
  const companyInfo = analysis?.company_info || {};
  const supportResistance = analysis?.support_resistance || {};
  const matchedStrategies = analysis?.matched_strategies || [];
  const news = analysis?.news || [];
  const quality = qualityData?.data || {};

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'chart', label: 'Chart' },
    { id: 'technicals', label: 'Technicals' },
    { id: 'fundamentals', label: 'Fundamentals' },
    { id: 'earnings', label: 'Earnings' },
    { id: 'strategies', label: 'Strategies' },
    { id: 'news', label: 'News' },
  ];

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className="bg-[#0A0A0A] border border-white/10 w-full max-w-4xl max-h-[90vh] overflow-hidden rounded-xl"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-white/10 bg-gradient-to-r from-zinc-900/50 to-transparent">
            <div className="flex items-center gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <span className="text-2xl font-bold text-white">{ticker.symbol}</span>
                  {scores.grade && (
                    <span className={`text-sm px-2 py-0.5 rounded font-bold ${
                      scores.grade === 'A' ? 'bg-green-500 text-black' :
                      scores.grade === 'B' ? 'bg-cyan-500 text-black' :
                      scores.grade === 'C' ? 'bg-yellow-500 text-black' :
                      'bg-red-500 text-white'
                    }`}>Grade {scores.grade}</span>
                  )}
                  {quality.grade && (
                    <span className={`text-xs px-2 py-0.5 rounded font-bold ${
                      quality.grade?.startsWith('A') ? 'bg-emerald-500 text-black' :
                      quality.grade?.startsWith('B') ? 'bg-blue-500 text-black' :
                      quality.grade?.startsWith('C') ? 'bg-yellow-500 text-black' :
                      'bg-red-500 text-white'
                    }`} title="Earnings Quality Grade">Q:{quality.grade}</span>
                  )}
                  {tradingSummary.bias && (
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      tradingSummary.bias === 'BULLISH' ? 'bg-green-500/20 text-green-400' :
                      tradingSummary.bias === 'BEARISH' ? 'bg-red-500/20 text-red-400' :
                      'bg-zinc-500/20 text-zinc-400'
                    }`}>{tradingSummary.bias_strength} {tradingSummary.bias}</span>
                  )}
                </div>
                <p className="text-xs text-zinc-500 mt-0.5">{companyInfo.name || ticker.symbol}</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="text-right">
                <span className="text-2xl font-mono font-bold text-white">${formatPrice(quote?.price)}</span>
                <span className={`ml-2 font-mono ${quote?.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {formatPercent(quote?.change_percent)}
                </span>
              </div>
              {onAskAI && (
                <button onClick={() => onAskAI(ticker.symbol)} className="p-2 rounded-lg hover:bg-amber-500/20 text-amber-400 transition-colors" title="Ask AI about this stock">
                  <Bot className="w-5 h-5" />
                </button>
              )}
              <button onClick={onClose} className="p-2 rounded-lg hover:bg-white/10 text-zinc-400">
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-white/10 px-4 overflow-x-auto">
            {tabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
                  activeTab === tab.id ? 'text-cyan-400 border-b-2 border-cyan-400' : 'text-zinc-400 hover:text-white'
                }`}
              >{tab.label}</button>
            ))}
          </div>

          {/* Content */}
          <div className="p-4 overflow-y-auto max-h-[60vh]">
            {loading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="w-10 h-10 animate-spin text-cyan-400" />
              </div>
            ) : !analysis && !historicalData?.length ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <AlertTriangle className="w-12 h-12 text-yellow-500 mb-4" />
                <p className="text-lg font-semibold text-white mb-2">Unable to Load Data</p>
                <p className="text-sm text-zinc-400 mb-4">{chartError || 'Could not fetch analysis data.'}</p>
                <div className="flex gap-3">
                  <button onClick={() => { setLoading(true); setChartError(null); api.get(`/api/ib/analysis/${ticker?.symbol}`).then(res => { setAnalysis(res.data); setLoading(false); }).catch(() => { setChartError('Still unable to load.'); setLoading(false); }); }} className="px-4 py-2 bg-cyan-600 text-white rounded hover:bg-cyan-500">Retry</button>
                  <button onClick={onClose} className="px-4 py-2 bg-zinc-800 text-white rounded hover:bg-zinc-700">Close</button>
                </div>
              </div>
            ) : (
              <>
                {/* OVERVIEW TAB */}
                {activeTab === 'overview' && (
                  <div className="space-y-4">
                    {tradingSummary.summary && (
                      <div className={`p-4 rounded-lg border ${tradingSummary.bias === 'BULLISH' ? 'border-green-500/30 bg-green-500/5' : tradingSummary.bias === 'BEARISH' ? 'border-red-500/30 bg-red-500/5' : 'border-zinc-700 bg-zinc-900/50'}`}>
                        <div className="flex items-center gap-2 mb-2">
                          <Target className="w-5 h-5 text-cyan-400" />
                          <span className="font-semibold text-white">Trading Analysis</span>
                        </div>
                        <p className="text-sm text-zinc-300 mb-3">{tradingSummary.summary}</p>
                        <div className="grid grid-cols-4 gap-3 text-center">
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 uppercase">Direction</span>
                            <p className={`text-sm font-bold ${tradingSummary.suggested_direction === 'LONG' ? 'text-green-400' : tradingSummary.suggested_direction === 'SHORT' ? 'text-red-400' : 'text-yellow-400'}`}>{tradingSummary.suggested_direction || 'WAIT'}</p>
                          </div>
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 uppercase">Entry</span>
                            <p className="text-sm font-mono text-white">${tradingSummary.entry?.toFixed(2) || '--'}</p>
                          </div>
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 uppercase">Stop</span>
                            <p className="text-sm font-mono text-red-400">${tradingSummary.stop_loss?.toFixed(2) || '--'}</p>
                          </div>
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 uppercase">Target</span>
                            <p className="text-sm font-mono text-green-400">${tradingSummary.target?.toFixed(2) || '--'}</p>
                          </div>
                        </div>
                        {tradingSummary.risk_reward > 0 && (
                          <div className="mt-2 text-xs text-zinc-500 text-center">Risk/Reward: <span className="text-cyan-400 font-mono">1:{tradingSummary.risk_reward}</span></div>
                        )}
                      </div>
                    )}

                    <div className="grid grid-cols-5 gap-2">
                      {[
                        { label: 'Overall', value: scores.overall, color: scores.overall >= 70 ? 'cyan' : scores.overall >= 50 ? 'yellow' : 'red', termId: 'overall-score' },
                        { label: 'Technical', value: scores.technical_score, color: 'blue', termId: 'technical-score' },
                        { label: 'Fundamental', value: scores.fundamental_score, color: 'purple', termId: 'fundamental-score' },
                        { label: 'Catalyst', value: scores.catalyst_score, color: 'orange', termId: 'catalyst-score' },
                        { label: 'Confidence', value: scores.confidence, color: 'green', termId: 'confidence-score' },
                      ].map((score, idx) => (
                        <div key={idx} className="bg-zinc-900 rounded-lg p-3 text-center">
                          <span className="text-[10px] text-zinc-500 uppercase block"><HelpTooltip termId={score.termId}>{score.label}</HelpTooltip></span>
                          <p className={`text-xl font-bold font-mono text-${score.color}-400`}>{score.value?.toFixed(0) || '--'}</p>
                        </div>
                      ))}
                    </div>

                    {companyInfo.name && (
                      <div className="bg-zinc-900/50 rounded-lg p-3">
                        <span className="text-[10px] text-zinc-500 uppercase">Company</span>
                        <p className="text-sm text-white font-medium">{companyInfo.name}</p>
                        <div className="flex gap-4 mt-1 text-xs text-zinc-400">
                          <span>{companyInfo.sector}</span>
                          <span>{companyInfo.industry}</span>
                          {companyInfo.market_cap > 0 && <span>MCap: ${(companyInfo.market_cap / 1e9).toFixed(1)}B</span>}
                        </div>
                      </div>
                    )}

                    {matchedStrategies.length > 0 && (
                      <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[10px] text-cyan-400 uppercase font-semibold">Top Strategy Match</span>
                          <span className="text-xs text-cyan-400">{matchedStrategies[0].match_score}% match</span>
                        </div>
                        <p className="text-sm font-bold text-white">{matchedStrategies[0].name}</p>
                        <p className="text-xs text-zinc-400 mt-1">{matchedStrategies[0].match_reasons?.join(' • ')}</p>
                        {matchedStrategies[0].entry_rules && <p className="text-[10px] text-zinc-500 mt-2">Entry: {matchedStrategies[0].entry_rules}</p>}
                      </div>
                    )}

                    <div className="bg-gradient-to-r from-amber-500/10 to-cyan-500/10 border border-amber-500/20 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <Sparkles className="w-5 h-5 text-amber-400" />
                          <span className="text-sm font-semibold text-white">AI Trading Recommendation</span>
                        </div>
                        <button onClick={() => onAskAI(ticker.symbol)} className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/20 text-amber-400 rounded text-xs hover:bg-amber-500/30 border border-amber-500/30">
                          <Bot className="w-3 h-3" />Ask AI for Deep Analysis
                        </button>
                      </div>
                      <div className="space-y-2">
                        <div className="flex items-start gap-2">
                          <span className={`text-xs px-2 py-0.5 rounded font-bold ${tradingSummary.bias === 'BULLISH' ? 'bg-green-500 text-black' : tradingSummary.bias === 'BEARISH' ? 'bg-red-500 text-white' : 'bg-zinc-600 text-white'}`}>{tradingSummary.bias || 'NEUTRAL'}</span>
                          <p className="text-xs text-zinc-300 flex-1">
                            {tradingSummary.bias === 'BULLISH' && scores.overall >= 60 ? `${ticker.symbol} shows strong bullish momentum. Consider LONG positions with tight risk management.` :
                             tradingSummary.bias === 'BEARISH' && scores.overall >= 60 ? `${ticker.symbol} shows bearish weakness. Consider SHORT positions or avoid longs.` :
                             `${ticker.symbol} is showing mixed signals. Wait for clearer direction before entering.`}
                          </p>
                        </div>
                        <div className="grid grid-cols-2 gap-2 mt-2">
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 block">Best Strategy</span>
                            <p className="text-xs text-white font-medium">{matchedStrategies[0]?.name || 'No match found'}</p>
                          </div>
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 block">Timeframe</span>
                            <p className="text-xs text-white font-medium">{matchedStrategies[0]?.timeframe || 'Intraday'}</p>
                          </div>
                        </div>
                        {scores.overall < 50 && (
                          <div className="flex items-center gap-2 mt-2 p-2 bg-red-500/10 border border-red-500/20 rounded">
                            <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
                            <p className="text-[10px] text-red-300">Low score ({scores.overall}/100) - Higher risk setup. Consider smaller position size or skip.</p>
                          </div>
                        )}
                        {scores.overall >= 70 && tradingSummary.bias && (
                          <div className="flex items-center gap-2 mt-2 p-2 bg-green-500/10 border border-green-500/20 rounded">
                            <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0" />
                            <p className="text-[10px] text-green-300">High conviction setup! Score: {scores.overall}/100 with clear {tradingSummary.bias.toLowerCase()} bias.</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* CHART TAB */}
                {activeTab === 'chart' && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs text-zinc-500">5-min Candles</span>
                      <button onClick={() => setShowTradingLines(!showTradingLines)} className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors ${showTradingLines ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' : 'bg-zinc-800 text-zinc-400 border border-zinc-700'}`}>
                        <Target className="w-3 h-3" />{showTradingLines ? 'Hide' : 'Show'} SL/TP Lines
                      </button>
                    </div>
                    {chartError && (
                      <div className="flex items-center justify-center h-[300px] bg-zinc-900/50 rounded border border-zinc-800">
                        <div className="text-center">
                          <AlertTriangle className="w-8 h-8 text-yellow-500 mx-auto mb-2" />
                          <p className="text-sm text-zinc-400">{chartError}</p>
                        </div>
                      </div>
                    )}
                    {!chartError && <div ref={chartContainerRef} className="w-full border border-zinc-800 rounded" style={{ height: '300px', minHeight: '300px', minWidth: '400px', background: '#0A0A0A' }} />}
                    {showTradingLines && tradingSummary.entry && (
                      <div className="flex items-center justify-center gap-4 mt-2 text-[10px]">
                        <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-cyan-400 rounded"></span>Entry ${tradingSummary.entry?.toFixed(2)}</span>
                        <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-red-400 rounded"></span>Stop ${tradingSummary.stop_loss?.toFixed(2)}</span>
                        <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-green-400 rounded"></span>Target ${tradingSummary.target?.toFixed(2)}</span>
                      </div>
                    )}
                    {supportResistance.resistance_1 && (
                      <div className="grid grid-cols-4 gap-2 mt-3">
                        <div className="bg-red-500/10 rounded p-2 text-center"><span className="text-[10px] text-zinc-500">R1</span><p className="text-sm font-mono text-red-400">${supportResistance.resistance_1?.toFixed(2)}</p></div>
                        <div className="bg-red-500/5 rounded p-2 text-center"><span className="text-[10px] text-zinc-500">R2</span><p className="text-sm font-mono text-red-300">${supportResistance.resistance_2?.toFixed(2)}</p></div>
                        <div className="bg-green-500/5 rounded p-2 text-center"><span className="text-[10px] text-zinc-500">S1</span><p className="text-sm font-mono text-green-300">${supportResistance.support_1?.toFixed(2)}</p></div>
                        <div className="bg-green-500/10 rounded p-2 text-center"><span className="text-[10px] text-zinc-500">S2</span><p className="text-sm font-mono text-green-400">${supportResistance.support_2?.toFixed(2)}</p></div>
                      </div>
                    )}
                  </div>
                )}

                {/* TECHNICALS TAB */}
                {activeTab === 'technicals' && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {[
                      { label: 'RSI (14)', value: technicals.rsi_14?.toFixed(1), color: technicals.rsi_14 > 70 ? 'red' : technicals.rsi_14 < 30 ? 'green' : 'zinc' },
                      { label: 'RVOL', value: technicals.rvol?.toFixed(1) + 'x', color: technicals.rvol > 2 ? 'cyan' : 'zinc' },
                      { label: 'VWAP', value: '$' + technicals.vwap?.toFixed(2), color: 'purple' },
                      { label: 'VWAP Dist', value: technicals.vwap_distance_pct?.toFixed(1) + '%', color: technicals.vwap_distance_pct > 0 ? 'green' : 'red' },
                      { label: 'EMA 9', value: '$' + technicals.ema_9?.toFixed(2), color: 'blue' },
                      { label: 'EMA 20', value: '$' + technicals.ema_20?.toFixed(2), color: 'blue' },
                      { label: 'SMA 50', value: '$' + technicals.sma_50?.toFixed(2), color: 'yellow' },
                      { label: 'ATR (14)', value: '$' + technicals.atr_14?.toFixed(2), color: 'orange' },
                    ].map((item, idx) => (
                      <div key={idx} className="bg-zinc-900 rounded-lg p-3">
                        <span className="text-[10px] text-zinc-500 uppercase block">{item.label}</span>
                        <p className={`text-lg font-mono text-${item.color}-400`}>{item.value || '--'}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* FUNDAMENTALS TAB */}
                {activeTab === 'fundamentals' && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {[
                      { label: 'Market Cap', value: fundamentals.market_cap ? `$${(fundamentals.market_cap / 1e9).toFixed(1)}B` : '--' },
                      { label: 'P/E Ratio', value: fundamentals.pe_ratio?.toFixed(1) || '--' },
                      { label: 'EPS', value: fundamentals.eps ? `$${fundamentals.eps.toFixed(2)}` : '--' },
                      { label: 'Dividend Yield', value: fundamentals.dividend_yield ? `${fundamentals.dividend_yield.toFixed(2)}%` : '--' },
                      { label: 'Beta', value: fundamentals.beta?.toFixed(2) || '--' },
                      { label: '52W High', value: fundamentals.high_52w ? `$${fundamentals.high_52w.toFixed(2)}` : '--' },
                      { label: '52W Low', value: fundamentals.low_52w ? `$${fundamentals.low_52w.toFixed(2)}` : '--' },
                      { label: 'Avg Volume', value: fundamentals.avg_volume ? formatVolume(fundamentals.avg_volume) : '--' },
                    ].map((item, idx) => (
                      <div key={idx} className="bg-zinc-900 rounded-lg p-3">
                        <span className="text-[10px] text-zinc-500 uppercase block">{item.label}</span>
                        <p className="text-lg font-mono text-white">{item.value}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* EARNINGS TAB */}
                {activeTab === 'earnings' && (
                  <div className="space-y-4">
                    {earningsData?.available ? (
                      <>
                        <div className={`p-4 rounded-lg border ${earningsData.summary?.overall_rating === 'strong' ? 'border-green-500/30 bg-green-500/5' : earningsData.summary?.overall_rating === 'good' ? 'border-cyan-500/30 bg-cyan-500/5' : earningsData.summary?.overall_rating === 'weak' ? 'border-red-500/30 bg-red-500/5' : 'border-zinc-700 bg-zinc-900/50'}`}>
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-3">
                              <span className={`text-2xl font-bold px-4 py-2 rounded-lg ${earningsData.summary?.overall_rating === 'strong' ? 'bg-green-500 text-black' : earningsData.summary?.overall_rating === 'good' ? 'bg-cyan-500 text-black' : earningsData.summary?.overall_rating === 'weak' ? 'bg-red-500 text-white' : 'bg-zinc-700 text-white'}`}>{earningsData.summary?.overall_rating?.toUpperCase() || 'NEUTRAL'}</span>
                              <div>
                                <p className="text-white font-semibold">Earnings Performance</p>
                                <p className="text-xs text-zinc-400">{earningsData.trends?.total_quarters || 0} quarters analyzed</p>
                              </div>
                            </div>
                            {earningsData.trends && (
                              <div className="text-right">
                                <p className="text-2xl font-mono font-bold text-white">{earningsData.trends.eps_beat_rate?.toFixed(0)}%</p>
                                <p className="text-xs text-zinc-500">EPS Beat Rate</p>
                              </div>
                            )}
                          </div>
                          {earningsData.summary?.key_points?.length > 0 && (
                            <div className="mt-3 space-y-1">
                              {earningsData.summary.key_points.map((point, idx) => (
                                <div key={idx} className="flex items-start gap-2 text-sm"><span className="text-green-400">✓</span><span className="text-zinc-300">{point}</span></div>
                              ))}
                            </div>
                          )}
                        </div>
                        {earningsData.trends && (
                          <div className="grid grid-cols-2 gap-3">
                            <div className="bg-zinc-900 rounded-lg p-3">
                              <p className="text-xs text-zinc-500 uppercase mb-2">EPS Performance</p>
                              <div className="flex items-center justify-between">
                                <div className="text-center"><p className="text-lg font-bold text-green-400">{earningsData.trends.eps_beats}</p><p className="text-[10px] text-zinc-500">Beats</p></div>
                                <div className="text-center"><p className="text-lg font-bold text-red-400">{earningsData.trends.eps_misses}</p><p className="text-[10px] text-zinc-500">Misses</p></div>
                                <div className="text-center"><p className="text-lg font-bold text-cyan-400">{earningsData.trends.eps_beat_rate?.toFixed(0)}%</p><p className="text-[10px] text-zinc-500">Beat Rate</p></div>
                              </div>
                            </div>
                            <div className="bg-zinc-900 rounded-lg p-3">
                              <p className="text-xs text-zinc-500 uppercase mb-2">Revenue Performance</p>
                              <div className="flex items-center justify-between">
                                <div className="text-center"><p className="text-lg font-bold text-green-400">{earningsData.trends.rev_beats}</p><p className="text-[10px] text-zinc-500">Beats</p></div>
                                <div className="text-center"><p className="text-lg font-bold text-red-400">{earningsData.trends.rev_misses}</p><p className="text-[10px] text-zinc-500">Misses</p></div>
                                <div className="text-center"><p className="text-lg font-bold text-cyan-400">{earningsData.trends.rev_beat_rate?.toFixed(0)}%</p><p className="text-[10px] text-zinc-500">Beat Rate</p></div>
                              </div>
                            </div>
                          </div>
                        )}
                        {earningsData.earnings_history?.length > 0 && (
                          <div className="bg-zinc-900 rounded-lg p-3">
                            <p className="text-sm font-semibold text-white mb-2">Earnings History</p>
                            <div className="overflow-x-auto">
                              <table className="w-full text-xs">
                                <thead><tr className="text-zinc-500 border-b border-zinc-800"><th className="text-left py-2">Date</th><th className="text-right py-2">EPS Est</th><th className="text-right py-2">EPS Act</th><th className="text-right py-2">Surprise</th><th className="text-right py-2">Result</th></tr></thead>
                                <tbody>
                                  {earningsData.earnings_history.slice(0, 4).map((q, idx) => (
                                    <tr key={idx} className="border-b border-zinc-800/50">
                                      <td className="py-2 text-zinc-300">{q.date}</td>
                                      <td className="py-2 text-right text-zinc-400">${q.eps_estimate?.toFixed(2)}</td>
                                      <td className="py-2 text-right text-white font-mono">${q.eps_actual?.toFixed(2)}</td>
                                      <td className={`py-2 text-right font-mono ${q.eps_surprise_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>{q.eps_surprise_pct >= 0 ? '+' : ''}{q.eps_surprise_pct?.toFixed(1)}%</td>
                                      <td className="py-2 text-right"><span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${q.eps_result === 'BEAT' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>{q.eps_result}</span></td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                        {earningsData.metrics && (
                          <div className="grid grid-cols-3 gap-2">
                            <div className="bg-zinc-900 rounded p-2 text-center"><span className="text-[10px] text-zinc-500">EPS Growth (YoY)</span><p className={`text-sm font-mono ${earningsData.metrics.eps_growth_quarterly_yoy >= 0 ? 'text-green-400' : 'text-red-400'}`}>{earningsData.metrics.eps_growth_quarterly_yoy?.toFixed(1)}%</p></div>
                            <div className="bg-zinc-900 rounded p-2 text-center"><span className="text-[10px] text-zinc-500">Revenue Growth (YoY)</span><p className={`text-sm font-mono ${earningsData.metrics.revenue_growth_quarterly_yoy >= 0 ? 'text-green-400' : 'text-red-400'}`}>{earningsData.metrics.revenue_growth_quarterly_yoy?.toFixed(1)}%</p></div>
                            <div className="bg-zinc-900 rounded p-2 text-center"><span className="text-[10px] text-zinc-500">Growth Trend</span><p className={`text-sm font-bold ${earningsData.growth_trend === 'accelerating' ? 'text-green-400' : earningsData.growth_trend === 'slowing' ? 'text-yellow-400' : 'text-red-400'}`}>{earningsData.growth_trend?.toUpperCase()}</p></div>
                          </div>
                        )}
                      </>
                    ) : <p className="text-center text-zinc-500 py-10">Earnings data unavailable</p>}
                  </div>
                )}

                {/* STRATEGIES TAB */}
                {activeTab === 'strategies' && (
                  <div className="space-y-2">
                    {matchedStrategies.length > 0 ? matchedStrategies.map((strategy, idx) => (
                      <div key={idx} className={`p-3 rounded-lg border ${idx === 0 ? 'border-cyan-500/30 bg-cyan-500/5' : 'border-zinc-800 bg-zinc-900/50'}`}>
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-white">{strategy.name}</span>
                          <span className={`text-xs ${idx === 0 ? 'text-cyan-400' : 'text-zinc-400'}`}>{strategy.match_score}% match</span>
                        </div>
                        <p className="text-xs text-zinc-400 mt-1">{strategy.match_reasons?.join(' • ')}</p>
                        {strategy.entry_rules && <p className="text-[10px] text-zinc-500 mt-2">Entry: {strategy.entry_rules}</p>}
                      </div>
                    )) : <p className="text-center text-zinc-500 py-10">No matching strategies found</p>}
                  </div>
                )}

                {/* NEWS TAB */}
                {activeTab === 'news' && (
                  <div className="space-y-2">
                    {news.length > 0 ? news.map((item, idx) => (
                      <div key={idx} className="p-3 rounded-lg bg-zinc-900/50 border border-zinc-800">
                        <p className="text-sm text-white">{item.headline}</p>
                        <div className="flex items-center gap-2 mt-1 text-xs text-zinc-500">
                          <span>{item.source}</span>
                          <span>•</span>
                          <span>{new Date(item.datetime).toLocaleString()}</span>
                        </div>
                      </div>
                    )) : <p className="text-center text-zinc-500 py-10">No recent news available</p>}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Footer */}
          <div className="flex gap-3 p-4 border-t border-white/10">
            <button onClick={() => onTrade(ticker, 'BUY')} className="flex-1 py-2.5 text-sm font-bold bg-green-500 text-black rounded-lg hover:bg-green-400 transition-colors">Buy {ticker.symbol}</button>
            <button onClick={() => onTrade(ticker, 'SELL')} className="flex-1 py-2.5 text-sm font-bold bg-red-500 text-white rounded-lg hover:bg-red-400 transition-colors">Short {ticker.symbol}</button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

export default TickerDetailModal;
