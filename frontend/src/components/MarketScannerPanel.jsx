import React, { useState, useEffect, useCallback } from 'react';
import { Search, Filter, Play, Square, Clock, TrendingUp, BarChart3, Zap, RefreshCw, ChevronRight, Target, AlertTriangle, Brain, CheckCircle } from 'lucide-react';
import { Tip, CustomTip } from './shared/Tooltip';

const API_URL = process.env.REACT_APP_BACKEND_URL;

// Trade style presets
const TRADE_STYLES = {
  intraday: {
    label: 'Intraday',
    description: 'Fast-moving stocks for day trading',
    tip: 'Scan for scalp and intraday setups. High momentum, tight stops. Hold minutes to hours.',
    icon: Zap,
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-400/10',
    strategies: 47,
    holdTime: 'Minutes to hours'
  },
  swing: {
    label: 'Swing',
    description: 'Multi-day momentum and pattern trades',
    tip: 'Scan for swing trade setups. Hold 2-10 days. Focus on daily chart breakouts and pullbacks.',
    icon: TrendingUp,
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-400/10',
    strategies: 15,
    holdTime: 'Days to weeks'
  },
  investment: {
    label: 'Investment',
    description: 'Long-term value and growth opportunities',
    tip: 'Scan for position trades. Hold weeks to months. Focus on fundamentals and major trends.',
    icon: Target,
    color: 'text-green-400',
    bgColor: 'bg-green-400/10',
    strategies: 15,
    holdTime: 'Weeks to years'
  },
  all: {
    label: 'All Strategies',
    description: 'Scan with all 77 strategies',
    tip: 'Use all available strategies. Most comprehensive scan. Takes longer to complete.',
    icon: BarChart3,
    color: 'text-purple-400',
    bgColor: 'bg-purple-400/10',
    strategies: 77,
    holdTime: 'Various'
  }
};

export default function MarketScannerPanel() {
  const [selectedStyle, setSelectedStyle] = useState('swing');
  const [scanName, setScanName] = useState('');
  const [isScanning, setIsScanning] = useState(false);
  const [activeScan, setActiveScan] = useState(null);
  const [recentScans, setRecentScans] = useState([]);
  const [symbolCount, setSymbolCount] = useState(0);
  const [selectedScan, setSelectedScan] = useState(null);
  const [scanSignals, setScanSignals] = useState([]);
  
  // Filters
  const [filters, setFilters] = useState({
    minPrice: 5,
    maxPrice: 500,
    excludeOTC: true,
    excludePenny: true,
    aiAgreesOnly: false,      // NEW: Only show AI-confirmed signals
    minAiConfidence: 0,       // NEW: Minimum AI confidence (0-100)
    sortByAi: false           // NEW: Sort by AI confidence
  });

  // Fetch symbol count on mount
  useEffect(() => {
    fetch(`${API_URL}/api/scanner/symbols`)
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          setSymbolCount(data.total_symbols);
        }
      })
      .catch(console.error);
    
    // Load recent scans
    loadRecentScans();
  }, []);

  // Poll active scan status
  useEffect(() => {
    if (!activeScan || activeScan.status === 'completed' || activeScan.status === 'failed') {
      return;
    }

    const interval = setInterval(() => {
      fetch(`${API_URL}/api/scanner/scan/${activeScan.id}`)
        .then(res => res.json())
        .then(data => {
          if (data.success && data.scan) {
            setActiveScan(data.scan);
            if (data.scan.status === 'completed' || data.scan.status === 'failed') {
              setIsScanning(false);
              loadRecentScans();
            }
          }
        })
        .catch(console.error);
    }, 2000);

    return () => clearInterval(interval);
  }, [activeScan]);

  const loadRecentScans = useCallback(() => {
    fetch(`${API_URL}/api/scanner/scans?limit=10`)
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          setRecentScans(data.scans || []);
        }
      })
      .catch(console.error);
  }, []);

  const startScan = async () => {
    setIsScanning(true);
    
    try {
      const response = await fetch(`${API_URL}/api/scanner/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: scanName || `${TRADE_STYLES[selectedStyle].label} Market Scan`,
          trade_style: selectedStyle,
          filters: {
            trade_style: selectedStyle,
            min_price: filters.minPrice,
            max_price: filters.maxPrice,
            exclude_otc: filters.excludeOTC,
            exclude_penny_stocks: filters.excludePenny
          },
          run_in_background: true
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        setActiveScan({
          id: data.scan_id,
          status: 'pending',
          progress_pct: 0
        });
      }
    } catch (error) {
      console.error('Error starting scan:', error);
      setIsScanning(false);
    }
  };

  const cancelScan = async () => {
    if (!activeScan) return;
    
    try {
      await fetch(`${API_URL}/api/scanner/scan/${activeScan.id}`, {
        method: 'DELETE'
      });
      setIsScanning(false);
      setActiveScan(null);
    } catch (error) {
      console.error('Error cancelling scan:', error);
    }
  };

  const viewScanDetails = async (scan) => {
    setSelectedScan(scan);
    
    // Fetch signals for this scan
    try {
      const response = await fetch(`${API_URL}/api/scanner/scan/${scan.id}/signals?limit=50`);
      const data = await response.json();
      if (data.success) {
        setScanSignals(data.signals || []);
      }
    } catch (error) {
      console.error('Error fetching signals:', error);
    }
  };

  return (
    <div className="space-y-6" data-testid="market-scanner-panel">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <Search className="w-5 h-5 text-cyan-400" />
            Market Scanner
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Scan {symbolCount.toLocaleString()} US stocks for strategy signals
          </p>
        </div>
        
        <div className="flex items-center gap-2">
          <button
            onClick={loadRecentScans}
            className="flex items-center gap-1 px-3 py-2 text-sm border border-gray-700 rounded-lg hover:bg-gray-700 text-gray-300"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Trade Style Selection */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Object.entries(TRADE_STYLES).map(([key, style]) => {
          const Icon = style.icon;
          const isSelected = selectedStyle === key;
          
          return (
            <button
              key={key}
              onClick={() => setSelectedStyle(key)}
              className={`p-4 rounded-lg border transition-all text-left ${
                isSelected 
                  ? `border-cyan-500 ${style.bgColor}` 
                  : 'border-gray-700 hover:border-gray-600 bg-gray-800/50'
              }`}
              data-testid={`style-${key}`}
            >
              <div className="flex items-center gap-2 mb-2">
                <Icon className={`w-5 h-5 ${style.color}`} />
                <span className="font-medium text-white">{style.label}</span>
              </div>
              <p className="text-xs text-gray-400 mb-2">{style.description}</p>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">{style.strategies} strategies</span>
                <span className="text-gray-500">{style.holdTime}</span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Filters Row */}
      <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-4 h-4 text-gray-400" />
          <span className="text-sm font-medium text-gray-300">Pre-Filters</span>
        </div>
        
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Min Price</label>
            <input
              type="number"
              value={filters.minPrice}
              onChange={(e) => setFilters(f => ({ ...f, minPrice: parseFloat(e.target.value) || 0 }))}
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
            />
          </div>
          
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Max Price</label>
            <input
              type="number"
              value={filters.maxPrice}
              onChange={(e) => setFilters(f => ({ ...f, maxPrice: parseFloat(e.target.value) || 1000 }))}
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
            />
          </div>
          
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="excludeOTC"
              checked={filters.excludeOTC}
              onChange={(e) => setFilters(f => ({ ...f, excludeOTC: e.target.checked }))}
              className="rounded bg-gray-900 border-gray-700"
            />
            <label htmlFor="excludeOTC" className="text-sm text-gray-300">Exclude OTC</label>
          </div>
          
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="excludePenny"
              checked={filters.excludePenny}
              onChange={(e) => setFilters(f => ({ ...f, excludePenny: e.target.checked }))}
              className="rounded bg-gray-900 border-gray-700"
            />
            <label htmlFor="excludePenny" className="text-sm text-gray-300">Exclude Penny</label>
          </div>
        </div>
      </div>

      {/* Scan Name & Start Button */}
      <div className="flex items-center gap-4">
        <input
          type="text"
          placeholder="Scan name (optional)"
          value={scanName}
          onChange={(e) => setScanName(e.target.value)}
          className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-500"
        />
        
        {isScanning ? (
          <button
            onClick={cancelScan}
            className="flex items-center gap-2 px-6 py-3 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium"
            data-testid="cancel-scan-btn"
          >
            <Square className="w-4 h-4" />
            Cancel Scan
          </button>
        ) : (
          <button
            onClick={startScan}
            className="flex items-center gap-2 px-6 py-3 bg-cyan-600 hover:bg-cyan-700 text-white rounded-lg font-medium"
            data-testid="start-scan-btn"
          >
            <Play className="w-4 h-4" />
            Start Scan
          </button>
        )}
      </div>

      {/* Active Scan Progress */}
      {activeScan && activeScan.status === 'running' && (
        <div className="bg-gray-800/50 rounded-lg p-4 border border-cyan-500/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-white">Scanning...</span>
            <span className="text-sm text-cyan-400">{activeScan.progress_pct?.toFixed(1)}%</span>
          </div>
          
          <div className="w-full bg-gray-700 rounded-full h-2 mb-2">
            <div 
              className="bg-cyan-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${activeScan.progress_pct || 0}%` }}
            />
          </div>
          
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>
              {activeScan.symbols_scanned?.toLocaleString()} / {activeScan.symbols_passed_filter?.toLocaleString()} symbols
            </span>
            <span>{activeScan.total_signals || 0} signals found</span>
          </div>
        </div>
      )}

      {/* Results Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Scans */}
        <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
          <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
            <Clock className="w-4 h-4" />
            Recent Scans
          </h3>
          
          {recentScans.length === 0 ? (
            <p className="text-sm text-gray-500 text-center py-4">No scans yet</p>
          ) : (
            <div className="space-y-2">
              {recentScans.map((scan) => (
                <button
                  key={scan.id}
                  onClick={() => viewScanDetails(scan)}
                  className={`w-full p-3 rounded-lg text-left transition-all ${
                    selectedScan?.id === scan.id 
                      ? 'bg-cyan-500/10 border border-cyan-500/50' 
                      : 'bg-gray-900/50 hover:bg-gray-900 border border-transparent'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-white">{scan.name}</span>
                    <ChevronRight className="w-4 h-4 text-gray-500" />
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-400">
                    <span className={`px-2 py-0.5 rounded ${
                      scan.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                      scan.status === 'running' ? 'bg-yellow-500/20 text-yellow-400' :
                      scan.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                      'bg-gray-500/20 text-gray-400'
                    }`}>
                      {scan.status}
                    </span>
                    <span>{scan.total_signals || 0} signals</span>
                    <span>{new Date(scan.created_at).toLocaleDateString()}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Selected Scan Details */}
        <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
          <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            Scan Results
          </h3>
          
          {!selectedScan ? (
            <p className="text-sm text-gray-500 text-center py-4">Select a scan to view results</p>
          ) : (
            <div className="space-y-4">
              {/* Summary Stats */}
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-gray-900/50 rounded p-2 text-center">
                  <div className="text-lg font-bold text-white">{selectedScan.total_signals || 0}</div>
                  <div className="text-xs text-gray-400">Signals</div>
                </div>
                <div className="bg-gray-900/50 rounded p-2 text-center">
                  <div className="text-lg font-bold text-white">{selectedScan.symbols_scanned?.toLocaleString() || 0}</div>
                  <div className="text-xs text-gray-400">Scanned</div>
                </div>
                <div className="bg-gray-900/50 rounded p-2 text-center">
                  <div className="text-lg font-bold text-white">{selectedScan.duration_seconds?.toFixed(0) || 0}s</div>
                  <div className="text-xs text-gray-400">Duration</div>
                </div>
              </div>

              {/* Top Setups */}
              {selectedScan.top_setups && selectedScan.top_setups.length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-gray-400 mb-2">Top Setups by Expected R</h4>
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {selectedScan.top_setups.slice(0, 10).map((setup, idx) => (
                      <div key={idx} className="flex items-center justify-between p-2 bg-gray-900/50 rounded text-sm">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-cyan-400">{setup.symbol}</span>
                          <span className="text-gray-400">{setup.strategy_name}</span>
                        </div>
                        <span className="text-green-400">{setup.expected_r?.toFixed(2)}R</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Signals by Strategy */}
              {selectedScan.signals_by_strategy && Object.keys(selectedScan.signals_by_strategy).length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-gray-400 mb-2">Signals by Strategy</h4>
                  <div className="space-y-1 max-h-32 overflow-y-auto">
                    {Object.entries(selectedScan.signals_by_strategy)
                      .sort(([,a], [,b]) => b - a)
                      .slice(0, 5)
                      .map(([strategy, count]) => (
                        <div key={strategy} className="flex items-center justify-between text-sm">
                          <span className="text-gray-300">{strategy}</span>
                          <span className="text-cyan-400">{count}</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Full Signals List */}
      {scanSignals.length > 0 && (
        <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-300">All Signals ({scanSignals.length})</h3>
            
            {/* AI Filters */}
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={filters.aiAgreesOnly}
                  onChange={(e) => setFilters({...filters, aiAgreesOnly: e.target.checked})}
                  className="w-3 h-3 rounded border-gray-600 bg-gray-800 text-cyan-500"
                />
                <span className="text-xs text-gray-400 flex items-center gap-1">
                  <Brain className="w-3 h-3" />
                  AI Agrees Only
                </span>
              </label>
              
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={filters.sortByAi}
                  onChange={(e) => setFilters({...filters, sortByAi: e.target.checked})}
                  className="w-3 h-3 rounded border-gray-600 bg-gray-800 text-cyan-500"
                />
                <span className="text-xs text-gray-400">Sort by AI</span>
              </label>
            </div>
          </div>
          
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-700">
                  <th className="pb-2">Symbol</th>
                  <th className="pb-2">Strategy</th>
                  <th className="pb-2">Entry</th>
                  <th className="pb-2">Stop</th>
                  <th className="pb-2">Target</th>
                  <th className="pb-2">Exp R</th>
                  <th className="pb-2">Strength</th>
                  <th className="pb-2">
                    <span className="flex items-center gap-1">
                      <Brain className="w-3 h-3" /> AI
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {scanSignals
                  .filter(signal => !filters.aiAgreesOnly || signal.ai_agrees_with_direction)
                  .sort((a, b) => filters.sortByAi ? (b.ai_confidence || 0) - (a.ai_confidence || 0) : 0)
                  .map((signal, idx) => (
                  <tr key={idx} className="border-b border-gray-700/50 hover:bg-gray-700/20">
                    <td className="py-2 font-mono text-cyan-400">{signal.symbol}</td>
                    <td className="py-2 text-gray-300">{signal.strategy_name}</td>
                    <td className="py-2 text-white">${signal.entry_price?.toFixed(2)}</td>
                    <td className="py-2 text-red-400">${signal.stop_price?.toFixed(2)}</td>
                    <td className="py-2 text-green-400">${signal.target_price?.toFixed(2)}</td>
                    <td className="py-2 text-yellow-400">{signal.expected_r?.toFixed(2)}R</td>
                    <td className="py-2">
                      <div className="w-16 bg-gray-700 rounded-full h-1.5">
                        <div 
                          className="bg-cyan-500 h-1.5 rounded-full"
                          style={{ width: `${signal.signal_strength || 0}%` }}
                        />
                      </div>
                    </td>
                    <td className="py-2">
                      {signal.ai_confidence > 0 ? (
                        <div className="flex items-center gap-1">
                          {signal.ai_agrees_with_direction ? (
                            <CheckCircle className="w-3 h-3 text-green-400" />
                          ) : (
                            <AlertTriangle className="w-3 h-3 text-amber-400" />
                          )}
                          <span className={`text-xs font-mono ${
                            signal.ai_confidence >= 70 ? 'text-green-400' :
                            signal.ai_confidence >= 50 ? 'text-yellow-400' :
                            'text-gray-400'
                          }`}>
                            {signal.ai_confidence?.toFixed(0)}%
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-500">--</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Info Box */}
      <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm text-yellow-200/80">
            <strong>Note:</strong> Full market scans of 12,000+ stocks may take several minutes due to API rate limits. 
            For faster results, connect your IB Gateway for unlimited data access, or run scans during off-hours 
            when data will be pre-cached. Nightly auto-scans can be enabled to have fresh signals ready each morning.
          </div>
        </div>
      </div>
    </div>
  );
}
