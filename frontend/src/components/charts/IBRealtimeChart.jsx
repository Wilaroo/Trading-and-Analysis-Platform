import React, { useState, useEffect, useRef, useCallback } from 'react';
import { LineChart, Loader2, Wifi, WifiOff } from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api from '../../utils/api';

const IBRealtimeChart = ({ symbol, isConnected, isBusy, busyOperation, height = '100%' }) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const chartVersionRef = useRef(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hasData, setHasData] = useState(false);
  const [timeframe, setTimeframe] = useState('5 mins');
  const [duration, setDuration] = useState('1 D');
  const [lastUpdate, setLastUpdate] = useState(null);
  const [dataSource, setDataSource] = useState(null);
  const [chartReady, setChartReady] = useState(false);

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

  // Create chart on mount - use explicit dimensions
  useEffect(() => {
    if (!chartContainerRef.current || !symbol) return;

    setChartReady(false);
    setHasData(false);
    const currentVersion = ++chartVersionRef.current;

    // Cleanup previous chart
    if (chartRef.current) {
      try {
        chartRef.current.remove();
      } catch (e) {}
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    }

    const createChart = () => {
      if (chartVersionRef.current !== currentVersion) return;
      if (!chartContainerRef.current) return;
      
      try {
        // Get dimensions - use getBoundingClientRect for accurate measurements
        const rect = chartContainerRef.current.getBoundingClientRect();
        const containerWidth = Math.floor(rect.width) || 800;
        const containerHeight = Math.floor(rect.height) || 400;
        
        console.log('[Chart] Creating chart with dimensions:', containerWidth, 'x', containerHeight);
        
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

        // Configure price scale first
        chart.priceScale('right').applyOptions({
          autoScale: true,
          borderVisible: true,
          scaleMargins: { top: 0.1, bottom: 0.2 },
        });

        const candleSeries = chart.addCandlestickSeries({
          upColor: '#00FF94',
          downColor: '#FF2E2E',
          borderUpColor: '#00FF94',
          borderDownColor: '#FF2E2E',
          wickUpColor: '#00FF94',
          wickDownColor: '#FF2E2E',
          priceScaleId: 'right',
        });
        candleSeriesRef.current = candleSeries;

        // Also add volume
        const volumeSeries = chart.addHistogramSeries({
          color: '#26a69a',
          priceFormat: { type: 'volume' },
          priceScaleId: 'volume',
        });
        chart.priceScale('volume').applyOptions({
          scaleMargins: { top: 0.85, bottom: 0 },
        });
        volumeSeriesRef.current = volumeSeries;

        console.log('[Chart] Chart created with CANDLESTICK series');
        setChartReady(true);
      } catch (err) {
        console.error('[Chart] Error creating chart:', err);
      }
    };

    // Small delay to ensure container has dimensions
    const timer = setTimeout(createChart, 150);

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        const rect = chartContainerRef.current.getBoundingClientRect();
        chartRef.current.applyOptions({ 
          width: Math.floor(rect.width),
          height: Math.floor(rect.height)
        });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        try {
          chartRef.current.remove();
        } catch (e) {}
        chartRef.current = null;
      }
    };
  }, [symbol]);

  // Fetch data - only when chart is ready
  const fetchData = useCallback(async () => {
    if (!symbol || !chartReady || !candleSeriesRef.current || !chartRef.current) {
      console.log('[Chart] Skipping fetch - not ready:', { symbol, chartReady, hasSeries: !!candleSeriesRef.current });
      return;
    }
    
    if (!hasData) {
      setLoading(true);
    }
    setError(null);
    
    try {
      console.log('[Chart] Fetching data for:', symbol, timeframe, duration);
      const response = await api.get(`/api/ib/historical/${symbol}?duration=${encodeURIComponent(duration)}&bar_size=${encodeURIComponent(timeframe)}`);
      
      if (response.data.bars && response.data.bars.length > 0) {
        console.log('[Chart] Received', response.data.bars.length, 'bars');
        
        // For line series, use close price
        const lineData = response.data.bars.map(bar => ({
          time: Math.floor(new Date(bar.time || bar.date || bar.timestamp).getTime() / 1000),
          value: bar.close,
        }));
        
        // Sort data by time ascending (required by lightweight-charts)
        lineData.sort((a, b) => a.time - b.time);
        
        // Set data on chart
        if (candleSeriesRef.current && chartRef.current) {
          console.log('[Chart] Setting line data...', {
            firstBar: lineData[0],
            lastBar: lineData[lineData.length - 1],
            total: lineData.length
          });
          
          // Ensure data is valid
          const validData = lineData.filter(d => 
            d.time && !isNaN(d.value)
          );
          
          if (validData.length > 0) {
            candleSeriesRef.current.setData(validData);
            
            // Set the visible range to include ALL data
            const firstTime = validData[0].time;
            const lastTime = validData[validData.length - 1].time;
            console.log('[Chart] Setting time range:', firstTime, 'to', lastTime);
            
            chartRef.current.timeScale().setVisibleRange({
              from: firstTime,
              to: lastTime
            });
            
            // Force price scale to auto-fit
            chartRef.current.priceScale('right').applyOptions({ autoScale: true });
            
            // Trigger resize to force redraw
            const rect = chartContainerRef.current?.getBoundingClientRect();
            if (rect) {
              chartRef.current.resize(Math.floor(rect.width), Math.floor(rect.height));
            }
            
            // Get visible range after setting data
            const range = chartRef.current.timeScale().getVisibleRange();
            console.log('[Chart] Data set successfully, visible range:', range);
          } else {
            console.error('[Chart] No valid data after filtering');
          }
        }
        
        setHasData(true);
        setLastUpdate(new Date());
        setDataSource(response.data.source || (response.data.is_cached ? 'cached' : 'unknown'));
        setError(null);
      } else {
        if (!hasData) {
          setError('No data available for this symbol');
        }
      }
    } catch (err) {
      console.error('[Chart] Error fetching data:', err);
      if (!hasData) {
        if (err.response?.status === 503) {
          const detail = err.response?.data?.detail;
          if (detail?.ib_busy) {
            setError(`IB Gateway is busy (${detail.busy_operation}). Waiting...`);
          } else {
            setError('IB Gateway disconnected. Using Alpaca data.');
          }
        } else {
          setError('Failed to load chart data');
        }
      }
    }
    
    setLoading(false);
  }, [symbol, timeframe, duration, chartReady, hasData]);

  // Fetch data when chart becomes ready or params change
  useEffect(() => {
    if (!chartReady) return;
    
    fetchData();
    
    const refreshInterval = isBusy ? 30000 : isConnected ? 10000 : 60000;
    const interval = setInterval(fetchData, refreshInterval);
    
    return () => clearInterval(interval);
  }, [chartReady, fetchData, isBusy, isConnected]);

  const displayError = (!hasData && !isConnected) ? 'Loading from Alpaca...' : error;
  const showLoading = loading && !hasData;

  return (
    <div className="h-full flex flex-col bg-[#0A0A0A] rounded-lg border border-white/10 overflow-hidden" style={{ height }}>
      {/* Chart Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/10 bg-[#0A0A0A] flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-white">{symbol}</span>
          <div className="flex items-center gap-2">
            {isConnected ? (
              isBusy ? (
                <span className="flex items-center gap-1 text-[10px] text-amber-400">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Busy
                </span>
              ) : (
                <span className="flex items-center gap-1 text-[10px] text-green-400">
                  <Wifi className="w-3 h-3" />
                  Live
                </span>
              )
            ) : (
              <span className="flex items-center gap-1 text-[10px] text-yellow-400">
                <WifiOff className="w-3 h-3" />
                Offline
              </span>
            )}
            {dataSource && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                dataSource === 'alpaca' ? 'bg-blue-500/20 text-blue-400' :
                dataSource === 'ib' ? 'bg-green-500/20 text-green-400' :
                'bg-zinc-500/20 text-zinc-400'
              }`}>
                {dataSource === 'alpaca' ? 'Alpaca' : dataSource === 'ib' ? 'IB' : 'Cached'}
              </span>
            )}
          </div>
          {lastUpdate && (
            <span className="text-[10px] text-zinc-500">
              {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>
        
        <div className="flex items-center gap-1">
          {timeframes.map(tf => (
            <button
              key={tf.value}
              onClick={() => { setTimeframe(tf.value); setDuration(tf.dur); setHasData(false); }}
              className={`px-2 py-1 text-[10px] rounded transition-all
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
      
      {/* Chart Container - Use flex-1 with explicit min-height */}
      <div className="flex-1 relative min-h-[300px]" style={{ position: 'relative' }}>
        {showLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#0A0A0A] z-10">
            <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
          </div>
        )}
        {displayError && !hasData && !showLoading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0A0A0A] z-10 p-4">
            <LineChart className="w-12 h-12 text-zinc-700 mb-3" />
            <span className="text-zinc-400 text-sm text-center mb-2">{displayError}</span>
          </div>
        )}
        {/* Chart container - must have explicit width/height for lightweight-charts */}
        <div 
          ref={chartContainerRef} 
          className="absolute inset-0" 
          style={{ width: '100%', height: '100%' }}
          data-testid="chart-canvas"
        />
      </div>
    </div>
  );
};

export default IBRealtimeChart;
