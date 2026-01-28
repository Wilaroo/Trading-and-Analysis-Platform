import React, { useState, useEffect, useRef } from 'react';
import { LineChart, Loader2, Wifi, WifiOff } from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api from '../utils/api';

// ===================== IB REAL-TIME CHART =====================
const IBRealtimeChart = ({ symbol, isConnected, isBusy, busyOperation }) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hasData, setHasData] = useState(false);
  const [timeframe, setTimeframe] = useState('5 mins');
  const [duration, setDuration] = useState('1 D');
  const [lastUpdate, setLastUpdate] = useState(null);
  const [dataSource, setDataSource] = useState(null);

  const timeframes = [
    { label: '1m', value: '1 min', dur: '1 D' },
    { label: '5m', value: '5 mins', dur: '1 D' },
    { label: '15m', value: '15 mins', dur: '2 D' },
    { label: '30m', value: '30 mins', dur: '1 W' },
    { label: '1H', value: '1 hour', dur: '1 W' },
    { label: '4H', value: '4 hours', dur: '1 M' },
    { label: 'D', value: '1 day', dur: '6 M' },
    { label: 'W', value: '1 week', dur: '1 Y' },
  ];

  // Create chart on mount
  useEffect(() => {
    if (!chartContainerRef.current || !symbol) return;

    // Small delay to ensure container has dimensions
    const timer = setTimeout(() => {
      if (!chartContainerRef.current) return;
      
      try {
        const containerWidth = chartContainerRef.current.clientWidth || 800;
        const containerHeight = chartContainerRef.current.clientHeight || 500;
        
        const chart = LightweightCharts.createChart(chartContainerRef.current, {
          layout: {
            background: { type: 'solid', color: '#0A0A0A' },
            textColor: '#9CA3AF',
          },
          grid: {
            vertLines: { color: '#1F2937' },
            horzLines: { color: '#1F2937' },
          },
          width: containerWidth,
          height: containerHeight,
          timeScale: {
            timeVisible: true,
            secondsVisible: false,
            borderColor: '#374151',
          },
          rightPriceScale: {
            borderColor: '#374151',
          },
          crosshair: {
            mode: 1,
            vertLine: { color: '#00E5FF', width: 1, style: 2 },
            horzLine: { color: '#00E5FF', width: 1, style: 2 },
          },
        });

        chartRef.current = chart;

        const candleSeries = chart.addCandlestickSeries({
          upColor: '#00FF94',
          downColor: '#FF2E2E',
          borderUpColor: '#00FF94',
          borderDownColor: '#FF2E2E',
          wickUpColor: '#00FF94',
          wickDownColor: '#FF2E2E',
        });
        candleSeriesRef.current = candleSeries;

        const volumeSeries = chart.addHistogramSeries({
          color: '#26a69a',
          priceFormat: { type: 'volume' },
          priceScaleId: '',
          scaleMargins: { top: 0.85, bottom: 0 },
        });
        volumeSeriesRef.current = volumeSeries;

        const handleResize = () => {
          if (chartContainerRef.current && chartRef.current) {
            chartRef.current.applyOptions({ 
              width: chartContainerRef.current.clientWidth,
              height: chartContainerRef.current.clientHeight
            });
          }
        };
        window.addEventListener('resize', handleResize);

      } catch (err) {
        console.error('Error creating chart:', err);
      }
    }, 100);

    return () => {
      clearTimeout(timer);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [symbol]);

  // Fetch data
  useEffect(() => {
    if (!symbol) return;
    
    // Don't try to fetch if not connected - handle in a separate effect
    if (!isConnected) {
      return;
    }

    const fetchData = async () => {
      setLoading(true);
      setError(null);
      
      try {
        const response = await api.get(`/api/ib/historical/${symbol}?duration=${encodeURIComponent(duration)}&bar_size=${encodeURIComponent(timeframe)}`);
        
        if (response.data.bars && response.data.bars.length > 0) {
          const candleData = response.data.bars.map(bar => ({
            time: new Date(bar.time || bar.date || bar.timestamp).getTime() / 1000,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
          }));
          
          const volumeData = response.data.bars.map(bar => ({
            time: new Date(bar.time || bar.date || bar.timestamp).getTime() / 1000,
            value: bar.volume,
            color: bar.close >= bar.open ? '#00FF9433' : '#FF2E2E33',
          }));

          if (candleSeriesRef.current) candleSeriesRef.current.setData(candleData);
          if (volumeSeriesRef.current) volumeSeriesRef.current.setData(volumeData);
          if (chartRef.current) chartRef.current.timeScale().fitContent();
          
          setHasData(true);
          setLastUpdate(new Date());
          setError(null);
        } else {
          setHasData(false);
          setError('No data available for this symbol');
        }
      } catch (err) {
        console.error('Error fetching chart data:', err);
        setHasData(false);
        if (err.response?.status === 503) {
          setError('IB Gateway disconnected. Connect from Command Center.');
        } else {
          setError('Failed to load chart data');
        }
      }
      
      setLoading(false);
    };

    fetchData();
    
    // Auto-refresh every 10 seconds when connected
    const interval = setInterval(() => {
      if (isConnected) fetchData();
    }, 10000);
    
    return () => clearInterval(interval);
  }, [symbol, timeframe, duration, isConnected]);

  // Handle disconnected state
  const displayError = !isConnected ? 'Connect to IB Gateway for real-time charts' : error;
  const showLoading = loading && isConnected;

  return (
    <div className="h-full flex flex-col bg-[#0A0A0A] rounded-lg border border-white/10 overflow-hidden">
      {/* Chart Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-[#0A0A0A]">
        <div className="flex items-center gap-4">
          <span className="text-xl font-bold text-white">{symbol}</span>
          <div className="flex items-center gap-2">
            {isConnected ? (
              <span className="flex items-center gap-1.5 text-xs text-green-400">
                <Wifi className="w-3 h-3" />
                IB Real-time
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs text-yellow-400">
                <WifiOff className="w-3 h-3" />
                Disconnected
              </span>
            )}
          </div>
          {lastUpdate && (
            <span className="text-[10px] text-zinc-500">
              Updated: {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>
        
        <div className="flex items-center gap-2">
          {timeframes.map(tf => (
            <button
              key={tf.value}
              onClick={() => { setTimeframe(tf.value); setDuration(tf.dur); }}
              className={`px-2 py-1 text-xs rounded transition-all
                ${timeframe === tf.value 
                  ? 'bg-cyan-400 text-black font-medium' 
                  : 'text-zinc-400 hover:text-white hover:bg-white/10'
                }
              `}
            >
              {tf.label}
            </button>
          ))}
        </div>
      </div>
      
      {/* Chart Container */}
      <div className="flex-1 relative" style={{ minHeight: '400px' }}>
        {showLoading && !hasData && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#0A0A0A] z-10">
            <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
          </div>
        )}
        {displayError && !hasData && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0A0A0A] z-10 p-4">
            <LineChart className="w-16 h-16 text-zinc-700 mb-4" />
            <span className="text-zinc-400 text-sm text-center mb-2">{displayError}</span>
            {!isConnected && (
              <span className="text-zinc-500 text-xs">Connect to IB from Command Center to view charts</span>
            )}
          </div>
        )}
        <div ref={chartContainerRef} className="absolute inset-0" />
      </div>
    </div>
  );
};

// ===================== CHARTS PAGE =====================
const ChartsPage = ({ ibConnected, ibConnectionChecked, connectToIb, ibBusy, ibBusyOperation }) => {
  const [symbol, setSymbol] = useState('AAPL');
  const [inputSymbol, setInputSymbol] = useState('AAPL');
  // Use shared connection state from App
  const isConnected = ibConnected;
  const connectionChecked = ibConnectionChecked;
  const isBusy = ibBusy;
  const popularSymbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'SPY', 'QQQ', 'IWM'];

  const handleConnect = async () => {
    try {
      await connectToIb();
    } catch (err) {
      console.error('Failed to connect:', err);
    }
  };

  const handleSymbolChange = () => {
    setSymbol(inputSymbol.toUpperCase());
  };

  return (
    <div className="space-y-4 animate-fade-in h-full" data-testid="charts-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <LineChart className="w-6 h-6 text-primary" />
            Real-Time Charts
          </h1>
          <p className="text-zinc-500 text-sm">IB Gateway powered real-time charting</p>
        </div>
        
        {/* Connection Status */}
        <div className="flex items-center gap-3">
          {!ibConnectionChecked ? (
            <>
              <div className="w-2 h-2 rounded-full bg-zinc-400 animate-pulse" />
              <span className="text-xs text-zinc-400">Checking...</span>
            </>
          ) : (
            <>
              <div className={`w-2 h-2 rounded-full ${isConnected ? (isBusy ? 'bg-amber-400 animate-pulse' : 'bg-green-400 animate-pulse') : 'bg-red-400'}`} />
              <span className="text-xs text-zinc-400">
                {isConnected ? (isBusy ? 'IB Busy (Scanning)' : 'IB Connected') : 'Disconnected'}
              </span>
              {!isConnected && (
                <button
                  onClick={handleConnect}
                  className="text-xs px-3 py-1.5 bg-cyan-400 text-black font-medium rounded hover:bg-cyan-300 transition-colors"
                >
                  Connect
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Symbol Input */}
      <div className="bg-paper rounded-lg p-4 border border-white/10">
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Symbol</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={inputSymbol}
                onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
                onKeyPress={(e) => e.key === 'Enter' && handleSymbolChange()}
                placeholder="Enter symbol..."
                className="flex-1 bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                data-testid="chart-symbol-input"
              />
              <button 
                onClick={handleSymbolChange}
                className="btn-primary"
                data-testid="load-chart-btn"
              >
                Load Chart
              </button>
            </div>
          </div>
        </div>
        
        {/* Popular Symbols */}
        <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-white/5">
          {popularSymbols.map((sym) => (
            <button
              key={sym}
              onClick={() => { setInputSymbol(sym); setSymbol(sym); }}
              className={`text-xs px-3 py-1.5 rounded-full transition-colors ${
                symbol === sym 
                  ? 'bg-primary/20 text-primary border border-primary/30' 
                  : 'bg-white/5 text-zinc-400 hover:bg-white/10 hover:text-white'
              }`}
            >
              {sym}
            </button>
          ))}
        </div>
      </div>

      {/* Chart Container */}
      <div className="bg-paper rounded-lg border border-white/10 overflow-hidden" style={{ height: 'calc(100vh - 320px)', minHeight: '500px' }}>
        <IBRealtimeChart symbol={symbol} isConnected={isConnected} />
      </div>
    </div>
  );
};

export default ChartsPage;
