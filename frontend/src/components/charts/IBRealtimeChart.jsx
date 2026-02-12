import React, { useState, useEffect, useRef } from 'react';
import { LineChart, Loader2, Wifi, WifiOff } from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api from '../../utils/api';

const IBRealtimeChart = ({ symbol, isConnected, isBusy, busyOperation, height = '100%' }) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const chartVersionRef = useRef(0);
  const chartReadyRef = useRef(false);
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

    chartReadyRef.current = false;
    const currentVersion = ++chartVersionRef.current;

    const timer = setTimeout(() => {
      if (chartVersionRef.current !== currentVersion) return;
      if (!chartContainerRef.current) return;
      
      try {
        const containerWidth = chartContainerRef.current.clientWidth || 800;
        const containerHeight = chartContainerRef.current.clientHeight || 400;
        
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
          priceScaleId: 'right',
        });
        candleSeriesRef.current = candleSeries;
        chartReadyRef.current = true;
        
        chart.priceScale('right').applyOptions({
          autoScale: true,
          scaleMargins: { top: 0.1, bottom: 0.2 },
        });

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

        return () => window.removeEventListener('resize', handleResize);
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
    
    const currentVersion = chartVersionRef.current;

    const fetchData = async () => {
      if (!chartReadyRef.current || !candleSeriesRef.current) {
        setTimeout(fetchData, 200);
        return;
      }
      if (!hasData) {
        setLoading(true);
      }
      setError(null);
      
      try {
        const response = await api.get(`/api/ib/historical/${symbol}?duration=${encodeURIComponent(duration)}&bar_size=${encodeURIComponent(timeframe)}`);
        
        if (chartVersionRef.current !== currentVersion) return;
        
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
          
          if (candleSeriesRef.current && chartRef.current) {
            try {
              candleData.sort((a, b) => a.time - b.time);
              volumeData.sort((a, b) => a.time - b.time);
              
              candleSeriesRef.current.setData(candleData);
              
              if (volumeSeriesRef.current) {
                volumeSeriesRef.current.setData(volumeData);
              }
              
              chartRef.current.timeScale().fitContent();
            } catch (setDataErr) {
              console.error('Error setting candle data:', setDataErr);
            }
          }
          
          if (chartRef.current && chartContainerRef.current) {
            chartRef.current.timeScale().fitContent();
            const w = chartContainerRef.current.clientWidth;
            const h = chartContainerRef.current.clientHeight;
            chartRef.current.applyOptions({ width: w, height: h });
            chartRef.current.timeScale().scrollToPosition(0, false);
          }
          
          setHasData(true);
          setLastUpdate(new Date());
          setDataSource(response.data.source || (response.data.is_cached ? 'cached' : 'unknown'));
          setError(null);
        } else {
          if (!hasData) {
            setHasData(false);
            setError('No data available for this symbol');
          }
        }
      } catch (err) {
        console.error('Error fetching chart data:', err);
        if (!hasData) {
          setHasData(false);
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
    };

    fetchData();
    
    const refreshInterval = isBusy ? 30000 : isConnected ? 10000 : 60000;
    const interval = setInterval(fetchData, refreshInterval);
    
    return () => clearInterval(interval);
  }, [symbol, timeframe, duration, isConnected, isBusy, hasData]);

  const displayError = (!hasData && !isConnected) ? 'Loading from Alpaca...' : error;
  const showLoading = loading && !hasData;

  return (
    <div className="h-full flex flex-col bg-[#0A0A0A] rounded-lg border border-white/10 overflow-hidden" style={{ height }}>
      {/* Chart Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/10 bg-[#0A0A0A]">
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
              onClick={() => { setTimeframe(tf.value); setDuration(tf.dur); }}
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
      
      {/* Chart Container */}
      <div className="flex-1 relative" style={{ minHeight: '300px' }}>
        {showLoading && !hasData && (
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
        <div ref={chartContainerRef} className="absolute inset-0" />
      </div>
    </div>
  );
};

export default IBRealtimeChart;
