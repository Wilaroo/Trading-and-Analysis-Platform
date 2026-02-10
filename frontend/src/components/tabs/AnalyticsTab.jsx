import React from 'react';
import { Target, RefreshCw, Loader2 } from 'lucide-react';
import LearningDashboard from '../LearningDashboard';
import { Card, SectionHeader } from '../shared/UIComponents';
import { formatPercent, formatPrice } from '../../utils/tradingUtils';
import { toast } from 'sonner';

const AnalyticsTab = ({
  isConnected,
  isScanning,
  runScanner,
  selectedScanType,
  setSelectedScanType,
  scanTypes,
  opportunities,
  setSelectedTicker,
}) => {
  return (
    <div className="space-y-4 mt-2" data-testid="analytics-tab-content">
      {/* Learning Dashboard */}
      <Card>
        <LearningDashboard />
      </Card>

      {/* Scanner */}
      <Card>
        <SectionHeader icon={Target} title="Scanner" action={
          <button
            onClick={() => !isConnected ? toast.error('Connect to IB Gateway first') : runScanner()}
            disabled={isScanning || !isConnected}
            className="flex items-center gap-1.5 text-xs text-cyan-400 hover:text-cyan-300 disabled:text-zinc-600"
            data-testid="run-scanner-btn"
          >
            {isScanning ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            {isScanning ? 'Scanning...' : 'Scan'}
          </button>
        } />
        <div className="flex flex-wrap gap-1 mb-3">
          {scanTypes.slice(0, 6).map(scan => (
            <button
              key={scan.id}
              onClick={() => setSelectedScanType(scan.id)}
              className={`px-2 py-1 text-[10px] rounded-full transition-colors ${
                selectedScanType === scan.id
                  ? 'bg-cyan-500 text-black font-medium'
                  : 'bg-zinc-800 text-zinc-400 hover:text-white'
              }`}
              data-testid={`scan-type-${scan.id}`}
            >
              {scan.label}
            </button>
          ))}
        </div>
        <div className="space-y-1 max-h-[300px] overflow-y-auto">
          {opportunities.length > 0 ? opportunities.slice(0, 10).map((result, idx) => (
            <div 
              key={idx}
              onClick={() => setSelectedTicker({ symbol: result.symbol, quote: result })}
              className="flex items-center justify-between p-2 bg-zinc-900/50 rounded hover:bg-zinc-800/50 cursor-pointer"
              data-testid={`scan-result-${result.symbol}`}
            >
              <div>
                <span className="text-sm font-bold text-white">{result.symbol}</span>
                <span className={`text-xs ml-2 ${result.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {formatPercent(result.change_percent)}
                </span>
              </div>
              <span className="text-xs text-zinc-500">${formatPrice(result.price)}</span>
            </div>
          )) : (
            <p className="text-center text-zinc-500 text-xs py-4" data-testid="scanner-empty">
              {isConnected ? 'Run a scan to find opportunities' : 'Connect to IB to scan'}
            </p>
          )}
        </div>
      </Card>
    </div>
  );
};

export default AnalyticsTab;
