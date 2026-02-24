import React, { useEffect, useRef, useState, memo, useCallback } from 'react';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';
import { Loader2, RefreshCw, Clock, Wifi, WifiOff } from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

const RealtimeChart = memo(({ symbol = 'SPY', height = 400 }) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const wsRef = useRef(null);
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [isLive, setIsLive] = useState(false);
  const [currentPrice, setCurrentPrice] = useState(null);

  // Fetch historical bars from Alpaca
  const fetchHistoricalData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Fetch 5-minute bars for intraday chart - force refresh to get latest data
      const response = await fetch(`${API_URL}/api/alpaca/bars/${symbol}?timeframe=5Min&limit=78&force_refresh=true`);
      if (!response.ok) throw new Error('Failed to fetch historical data');
      
      const data = await response.json();
      
      if (!data.data || data.data.length === 0) {
        throw new Error('No data available');
      }
      
      // Transform to lightweight-charts format
      const candles = data.data.map(bar => ({
        time: Math.floor(new Date(bar.timestamp).getTime() / 1000),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }));
      
      const volumes = data.data.map(bar => ({
        time: Math.floor(new Date(bar.timestamp).getTime() / 1000),
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
      }));
      
      if (candleSeriesRef.current) {
        console.log('Setting candle data:', candles.length, 'candles', candles.slice(0, 2));
        candleSeriesRef.current.setData(candles);
      }
      if (volumeSeriesRef.current) {
        volumeSeriesRef.current.setData(volumes);
      }
      
      // Set current price from latest bar
      if (candles.length > 0) {
        setCurrentPrice(candles[candles.length - 1].close);
      }
      
      setLastUpdate(new Date());
      setLoading(false);
      
      return candles;
    } catch (err) {
      console.error('Error fetching historical data:', err);
      setError(err.message);
      setLoading(false);
      return [];
    }
  }, [symbol]);

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Create chart
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: 'rgba(10, 10, 10, 1)' },
        textColor: 'rgba(255, 255, 255, 0.7)',
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
      },
      grid: {
        vertLines: { color: 'rgba(42, 46, 57, 0.5)' },
        horzLines: { color: 'rgba(42, 46, 57, 0.5)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(0, 212, 255, 0.4)',
          width: 1,
          style: 2,
          labelBackgroundColor: 'rgba(0, 212, 255, 0.9)',
        },
        horzLine: {
          color: 'rgba(0, 212, 255, 0.4)',
          width: 1,
          style: 2,
          labelBackgroundColor: 'rgba(0, 212, 255, 0.9)',
        },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: 'rgba(42, 46, 57, 0.8)',
        rightOffset: 5,
        barSpacing: 8,
      },
      rightPriceScale: {
        borderColor: 'rgba(42, 46, 57, 0.8)',
        scaleMargins: {
          top: 0.1,
          bottom: 0.2,
        },
      },
    });

    // Add candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#10B981',
      downColor: '#EF4444',
      borderUpColor: '#10B981',
      borderDownColor: '#EF4444',
      wickUpColor: '#10B981',
      wickDownColor: '#EF4444',
    });

    // Add volume series
    const volumeSeries = chart.addHistogramSeries({
      color: 'rgba(0, 212, 255, 0.3)',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
      scaleMargins: {
        top: 0.85,
        bottom: 0,
      },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    // Fetch initial data
    fetchHistoricalData();

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [height]);

  // Handle symbol change
  useEffect(() => {
    if (chartRef.current) {
      fetchHistoricalData();
    }
  }, [symbol, fetchHistoricalData]);

  // Real-time updates via polling (Alpaca rate limits prevent true streaming for all symbols)
  useEffect(() => {
    let intervalId;
    
    const updateRealtime = async () => {
      try {
        const response = await fetch(`${API_URL}/api/alpaca/quote/${symbol}`);
        if (!response.ok) return;
        
        const quote = await response.json();
        if (quote && quote.price) {
          setCurrentPrice(quote.price);
          setIsLive(true);
          setLastUpdate(new Date());
          
          // Update the last candle with current price
          if (candleSeriesRef.current) {
            const now = Math.floor(Date.now() / 1000);
            // Round to nearest 5-minute interval
            const barTime = now - (now % 300);
            
            candleSeriesRef.current.update({
              time: barTime,
              open: quote.price,
              high: quote.price,
              low: quote.price,
              close: quote.price,
            });
          }
        }
      } catch (err) {
        console.error('Real-time update error:', err);
        setIsLive(false);
      }
    };

    // Update every 5 seconds
    updateRealtime();
    intervalId = setInterval(updateRealtime, 5000);

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [symbol]);

  // Format time for display
  const formatTime = (date) => {
    if (!date) return '--:--:--';
    return date.toLocaleTimeString('en-US', { 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit',
      hour12: false 
    });
  };

  return (
    <div className="relative rounded-lg overflow-hidden" style={{ background: 'rgba(10, 10, 10, 1)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/10">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-white">{symbol}</span>
          {currentPrice && (
            <span className="text-sm font-mono text-cyan-400">${currentPrice.toFixed(2)}</span>
          )}
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-medium">
            REAL-TIME
          </span>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Live indicator */}
          <div className="flex items-center gap-1.5">
            {isLive ? (
              <Wifi className="w-3 h-3 text-emerald-400" />
            ) : (
              <WifiOff className="w-3 h-3 text-zinc-500" />
            )}
            <span className={`text-[10px] ${isLive ? 'text-emerald-400' : 'text-zinc-500'}`}>
              {isLive ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
          
          {/* Last update */}
          <div className="flex items-center gap-1 text-[10px] text-zinc-500">
            <Clock className="w-3 h-3" />
            <span>{formatTime(lastUpdate)}</span>
          </div>
          
          {/* Refresh button */}
          <button
            onClick={fetchHistoricalData}
            disabled={loading}
            className="p-1 rounded hover:bg-white/10 transition-colors"
            title="Refresh data"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-zinc-400 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>
      
      {/* Chart container */}
      <div ref={chartContainerRef} style={{ height: height }} data-testid="realtime-chart">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 z-10">
            <div className="flex items-center gap-2 text-cyan-400">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-sm">Loading {symbol}...</span>
            </div>
          </div>
        )}
        
        {error && !loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/80 z-10">
            <div className="text-center">
              <p className="text-red-400 text-sm mb-2">{error}</p>
              <button
                onClick={fetchHistoricalData}
                className="px-3 py-1.5 bg-cyan-500/20 text-cyan-400 rounded text-xs hover:bg-cyan-500/30"
              >
                Retry
              </button>
            </div>
          </div>
        )}
      </div>
      
      {/* Footer info */}
      <div className="flex items-center justify-between px-3 py-1.5 border-t border-white/10 text-[9px] text-zinc-500">
        <span>5-minute bars • Alpaca Market Data</span>
        <span>Eastern Time (ET)</span>
      </div>
    </div>
  );
});

RealtimeChart.displayName = 'RealtimeChart';

export default RealtimeChart;
