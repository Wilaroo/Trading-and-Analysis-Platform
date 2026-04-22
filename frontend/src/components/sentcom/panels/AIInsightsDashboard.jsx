import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { Brain, Loader, RefreshCw, X, Zap } from 'lucide-react';
import { toast } from 'sonner';
import api from '../../../utils/api';
import ClickableTicker from '../../shared/ClickableTicker';
import { useAIInsights } from '../hooks/useAIInsights';

// ============================================================================
// AI INSIGHTS DASHBOARD - Phase 4 Implementation
// ============================================================================

// AI Insights Dashboard Panel
export const AIInsightsDashboard = ({ onClose }) => {
  const { shadowDecisions, shadowPerformance, timeseriesStatus, predictionAccuracy, recentPredictions, loading, refresh } = useAIInsights();
  const [activeTab, setActiveTab] = useState('decisions');
  const [forecastSymbol, setForecastSymbol] = useState('');
  const [forecastResult, setForecastResult] = useState(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);

  const runForecast = async () => {
    if (!forecastSymbol.trim()) return;
    setForecastLoading(true);
    try {
      // Call forecast API - it will fetch bars from MongoDB if not provided
      const { data: forecastData } = await api.post('/api/ai-modules/timeseries/forecast', { symbol: forecastSymbol.toUpperCase() });
      
      if (forecastData.success) {
        setForecastResult(forecastData.forecast);
      } else {
        toast.error('Forecast failed: ' + (forecastData.error || forecastData.forecast?.signal || 'Unknown error'));
      }
    } catch (err) {
      console.error('Forecast error:', err);
      toast.error('Failed to run forecast');
    } finally {
      setForecastLoading(false);
    }
  };

  // Use portal to render modal at document root
  return ReactDOM.createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      data-testid="ai-insights-modal-backdrop"
    >
      <div
        className="relative w-full max-w-4xl max-h-[85vh] overflow-hidden rounded-2xl bg-gradient-to-br from-zinc-900 to-black border border-white/10"
        onClick={e => e.stopPropagation()}
        data-testid="ai-insights-modal"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500/20 to-cyan-500/20 flex items-center justify-center">
              <Brain className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">AI Insights Dashboard</h2>
              <p className="text-xs text-zinc-400">View AI decisions, forecasts, and performance</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
          >
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex gap-2 p-4 border-b border-white/5">
          {[
            { id: 'decisions', label: 'Shadow Decisions', icon: '👻' },
            { id: 'forecast', label: 'Time-Series Forecast', icon: '📈' },
            { id: 'predictions', label: 'Prediction Tracking', icon: '🎯' },
            { id: 'performance', label: 'Module Performance', icon: '📊' }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${
                activeTab === tab.id
                  ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30'
                  : 'bg-zinc-800/50 text-zinc-400 border border-white/5 hover:border-white/10'
              }`}
              data-testid={`ai-insights-tab-${tab.id}`}
            >
              <span>{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div className="p-4 overflow-y-auto max-h-[calc(85vh-160px)]">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader className="w-8 h-8 text-violet-400 animate-spin" />
            </div>
          ) : activeTab === 'decisions' ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-white">Recent AI Decisions</h3>
                <button
                  onClick={refresh}
                  className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                  data-testid="refresh-decisions"
                >
                  <RefreshCw className="w-4 h-4 text-zinc-400" />
                </button>
              </div>
              
              {shadowDecisions.length === 0 ? (
                <div className="text-center py-8" data-testid="no-decisions">
                  <div className="text-4xl mb-2">👻</div>
                  <p className="text-zinc-400">No shadow decisions yet</p>
                  <p className="text-xs text-zinc-500 mt-1">AI decisions will appear here when Shadow Mode is active</p>
                </div>
              ) : (
                shadowDecisions.map((decision, i) => (
                  <div
                    key={decision.id || i}
                    className="p-4 rounded-xl bg-black/40 border border-white/5 hover:border-white/10 transition-all"
                    data-testid={`decision-${i}`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <ClickableTicker symbol={decision.symbol} variant="inline" className="text-lg font-bold" />
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          decision.combined_recommendation === 'proceed' 
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : decision.combined_recommendation === 'reduce_size'
                            ? 'bg-amber-500/20 text-amber-400'
                            : 'bg-rose-500/20 text-rose-400'
                        }`}>
                          {decision.combined_recommendation?.toUpperCase() || 'UNKNOWN'}
                        </span>
                        {decision.was_executed && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400">
                            EXECUTED
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-zinc-500">
                        {new Date(decision.timestamp).toLocaleString()}
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-3 gap-4 mb-3">
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase">Price</p>
                        <p className="text-sm font-medium text-white">
                          ${decision.price_at_decision?.toFixed(2) || 'N/A'}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase">Confidence</p>
                        <p className="text-sm font-medium text-cyan-400">
                          {(decision.confidence_score || 0).toFixed(0)}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase">Regime</p>
                        <p className="text-sm font-medium text-violet-400">
                          {decision.market_regime || 'N/A'}
                        </p>
                      </div>
                    </div>
                    
                    {decision.reasoning && (
                      <p className="text-xs text-zinc-400 border-t border-white/5 pt-2 mt-2">
                        {decision.reasoning}
                      </p>
                    )}
                  </div>
                ))
              )}
            </div>
          ) : activeTab === 'forecast' ? (
            <div className="space-y-4">
              {/* Time-Series Model Status */}
              <div className="p-4 rounded-xl bg-gradient-to-br from-amber-500/10 to-orange-500/5 border border-amber-500/20">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <span>📈</span> Time-Series AI Model
                  </h3>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    timeseriesStatus?.model?.trained
                      ? 'bg-emerald-500/20 text-emerald-400'
                      : 'bg-amber-500/20 text-amber-400'
                  }`} data-testid="model-status">
                    {timeseriesStatus?.model?.trained ? 'TRAINED' : 'UNTRAINED'}
                  </span>
                </div>
                
                {timeseriesStatus?.model && (
                  <div className="grid grid-cols-4 gap-4 text-center">
                    <div>
                      <p className="text-lg font-bold text-white">{timeseriesStatus.model.version}</p>
                      <p className="text-[9px] text-zinc-500">Version</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-cyan-400" data-testid="model-accuracy">
                        {((timeseriesStatus.model.metrics?.accuracy || 0) * 100).toFixed(1)}%
                      </p>
                      <p className="text-[9px] text-zinc-500">Accuracy</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-amber-400">{timeseriesStatus.model.feature_count}</p>
                      <p className="text-[9px] text-zinc-500">Features</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-violet-400">
                        {(timeseriesStatus.model.metrics?.training_samples || 0).toLocaleString()}
                      </p>
                      <p className="text-[9px] text-zinc-500">Samples</p>
                    </div>
                  </div>
                )}
                
                {timeseriesStatus?.model?.metrics?.top_features && (
                  <div className="mt-3 pt-3 border-t border-white/5">
                    <p className="text-[10px] text-zinc-500 uppercase mb-2">Top Features</p>
                    <div className="flex flex-wrap gap-1">
                      {timeseriesStatus.model.metrics.top_features.slice(0, 6).map((f, i) => (
                        <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-black/40 text-zinc-400">
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Run Forecast */}
              <div className="p-4 rounded-xl bg-black/40 border border-white/5">
                <h3 className="text-sm font-bold text-white mb-3">Run Price Forecast</h3>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={forecastSymbol}
                    onChange={(e) => setForecastSymbol(e.target.value.toUpperCase())}
                    placeholder="Enter symbol (e.g., AAPL)"
                    className="flex-1 px-3 py-2 rounded-lg bg-black/60 border border-white/10 text-white text-sm focus:border-cyan-500/50 focus:outline-none"
                    onKeyPress={(e) => e.key === 'Enter' && runForecast()}
                    data-testid="forecast-symbol-input"
                  />
                  <button
                    onClick={runForecast}
                    disabled={forecastLoading || !forecastSymbol.trim()}
                    className="px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-sm font-medium disabled:opacity-50 flex items-center gap-2"
                    data-testid="run-forecast-btn"
                  >
                    {forecastLoading ? (
                      <Loader className="w-4 h-4 animate-spin" />
                    ) : (
                      <>
                        <Zap className="w-4 h-4" />
                        Forecast
                      </>
                    )}
                  </button>
                </div>
                
                {forecastResult && (
                  <div className="mt-4 p-4 rounded-xl bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10" data-testid="forecast-result">
                    <div className="flex items-center justify-between mb-3">
                      <ClickableTicker symbol={forecastResult.symbol} variant="inline" className="text-lg font-bold" />
                      <span className={`text-sm font-bold px-3 py-1 rounded-full ${
                        forecastResult.direction === 'up'
                          ? 'bg-emerald-500/20 text-emerald-400'
                          : forecastResult.direction === 'down'
                          ? 'bg-rose-500/20 text-rose-400'
                          : 'bg-zinc-500/20 text-zinc-400'
                      }`} data-testid="forecast-direction">
                        {forecastResult.direction?.toUpperCase() || 'FLAT'}
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-3 gap-4 text-center mb-3">
                      <div>
                        <p className="text-2xl font-bold text-emerald-400">
                          {(forecastResult.probability_up * 100).toFixed(1)}%
                        </p>
                        <p className="text-[10px] text-zinc-500">Prob. UP</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-rose-400">
                          {(forecastResult.probability_down * 100).toFixed(1)}%
                        </p>
                        <p className="text-[10px] text-zinc-500">Prob. DOWN</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-cyan-400">
                          {(forecastResult.confidence * 100).toFixed(0)}%
                        </p>
                        <p className="text-[10px] text-zinc-500">Confidence</p>
                      </div>
                    </div>
                    
                    <p className="text-sm text-zinc-300 text-center border-t border-white/5 pt-3">
                      {forecastResult.signal}
                    </p>
                    
                    <p className="text-[10px] text-zinc-500 text-center mt-2">
                      Model: {forecastResult.model_version} | {forecastResult.usable ? '✅ Usable' : '⚠️ Low confidence'}
                    </p>
                  </div>
                )}
              </div>
            </div>
          ) : activeTab === 'predictions' ? (
            /* Predictions Tracking Tab */
            <div className="space-y-4">
              {/* Prediction Accuracy Summary */}
              <div className="p-4 rounded-xl bg-gradient-to-br from-cyan-500/10 to-violet-500/5 border border-cyan-500/20">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <span>🎯</span> Prediction Accuracy (30 Days)
                  </h3>
                  <button
                    onClick={async () => {
                      setVerifying(true);
                      try {
                        const { data } = await api.post('/api/ai-modules/timeseries/verify-predictions');
                        if (data?.success) {
                          toast.success(`Verified ${data.result.verified} predictions`);
                          refresh();
                        }
                      } catch (e) {
                        toast.error('Verification failed');
                      } finally {
                        setVerifying(false);
                      }
                    }}
                    disabled={verifying}
                    className="px-3 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-400 text-xs font-medium hover:bg-cyan-500/30 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                    data-testid="verify-predictions-btn"
                  >
                    {verifying ? <Loader className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                    Verify Outcomes
                  </button>
                </div>
                
                {predictionAccuracy ? (
                  <div className="grid grid-cols-4 gap-4 text-center">
                    <div>
                      <p className="text-2xl font-bold text-white">{predictionAccuracy.total_predictions}</p>
                      <p className="text-[9px] text-zinc-500">Total Predictions</p>
                    </div>
                    <div>
                      <p className="text-2xl font-bold text-emerald-400">{predictionAccuracy.correct_predictions || 0}</p>
                      <p className="text-[9px] text-zinc-500">Correct</p>
                    </div>
                    <div>
                      <p className="text-2xl font-bold text-cyan-400">
                        {(predictionAccuracy.accuracy * 100).toFixed(1)}%
                      </p>
                      <p className="text-[9px] text-zinc-500">Accuracy</p>
                    </div>
                    <div>
                      <p className={`text-2xl font-bold ${(predictionAccuracy.avg_return_when_correct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {((predictionAccuracy.avg_return_when_correct || 0) * 100).toFixed(2)}%
                      </p>
                      <p className="text-[9px] text-zinc-500">Avg Return (Correct)</p>
                    </div>
                  </div>
                ) : (
                  <p className="text-zinc-400 text-center py-4">No accuracy data available yet</p>
                )}
                
                {/* Accuracy by Direction */}
                {predictionAccuracy?.by_direction && Object.keys(predictionAccuracy.by_direction).length > 0 && (
                  <div className="mt-4 pt-4 border-t border-white/5">
                    <p className="text-[10px] text-zinc-500 uppercase mb-2">Accuracy by Direction</p>
                    <div className="flex gap-3">
                      {Object.entries(predictionAccuracy.by_direction).map(([dir, stats]) => (
                        <div key={dir} className="flex-1 p-2 rounded-lg bg-black/30 text-center">
                          <span className={`text-xs font-bold ${
                            dir === 'up' ? 'text-emerald-400' : dir === 'down' ? 'text-rose-400' : 'text-zinc-400'
                          }`}>
                            {dir.toUpperCase()}
                          </span>
                          <p className="text-lg font-bold text-white mt-1">{(stats.accuracy * 100).toFixed(0)}%</p>
                          <p className="text-[8px] text-zinc-500">{stats.correct}/{stats.total}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              
              {/* Recent Predictions List */}
              <div>
                <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                  <span>📋</span> Recent Predictions
                </h3>
                
                {recentPredictions.length === 0 ? (
                  <div className="text-center py-8">
                    <div className="text-4xl mb-2">🎯</div>
                    <p className="text-zinc-400">No predictions yet</p>
                    <p className="text-xs text-zinc-500 mt-1">Run forecasts to track prediction accuracy</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {recentPredictions.map((pred, i) => (
                      <div 
                        key={i}
                        className="p-3 rounded-xl bg-black/40 border border-white/5 flex items-center justify-between"
                        data-testid={`prediction-${i}`}
                      >
                        <div className="flex items-center gap-3">
                          <ClickableTicker symbol={pred.symbol} variant="inline" className="text-sm font-bold" />
                          <span className={`text-xs px-2 py-0.5 rounded-full ${
                            pred.prediction?.direction === 'up' ? 'bg-emerald-500/20 text-emerald-400'
                            : pred.prediction?.direction === 'down' ? 'bg-rose-500/20 text-rose-400'
                            : 'bg-zinc-500/20 text-zinc-400'
                          }`}>
                            {pred.prediction?.direction?.toUpperCase() || 'FLAT'}
                          </span>
                          <span className="text-xs text-zinc-500">
                            {(pred.prediction?.probability_up * 100).toFixed(1)}% UP
                          </span>
                        </div>
                        
                        <div className="flex items-center gap-3">
                          {pred.price_at_prediction && (
                            <span className="text-xs text-zinc-400">${pred.price_at_prediction.toFixed(2)}</span>
                          )}
                          
                          {pred.outcome_verified ? (
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              pred.prediction_correct ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                            }`}>
                              {pred.prediction_correct ? '✓ CORRECT' : '✗ WRONG'}
                            </span>
                          ) : (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
                              PENDING
                            </span>
                          )}
                          
                          <span className="text-[10px] text-zinc-500">
                            {new Date(pred.timestamp).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            /* Performance Tab */
            <div className="space-y-4">
              <h3 className="text-sm font-bold text-white mb-4">Module Performance (7 Days)</h3>
              
              {!shadowPerformance || Object.keys(shadowPerformance).length === 0 ? (
                <div className="text-center py-8" data-testid="no-performance">
                  <div className="text-4xl mb-2">📊</div>
                  <p className="text-zinc-400">No performance data yet</p>
                  <p className="text-xs text-zinc-500 mt-1">Performance metrics will appear after AI modules make decisions</p>
                </div>
              ) : (
                Object.entries(shadowPerformance).map(([moduleName, perf]) => (
                  <div
                    key={moduleName}
                    className="p-4 rounded-xl bg-black/40 border border-white/5"
                    data-testid={`performance-${moduleName}`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-sm font-bold text-white capitalize">
                        {moduleName.replace(/_/g, ' ')}
                      </h4>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        perf.accuracy > 0.6 ? 'bg-emerald-500/20 text-emerald-400'
                        : perf.accuracy > 0.4 ? 'bg-amber-500/20 text-amber-400'
                        : 'bg-rose-500/20 text-rose-400'
                      }`}>
                        {(perf.accuracy * 100).toFixed(0)}% Accuracy
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-4 gap-4 text-center">
                      <div>
                        <p className="text-lg font-bold text-white">{perf.total_decisions}</p>
                        <p className="text-[9px] text-zinc-500">Total</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold text-emerald-400">{perf.correct_decisions}</p>
                        <p className="text-[9px] text-zinc-500">Correct</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold text-rose-400">{perf.incorrect_decisions}</p>
                        <p className="text-[9px] text-zinc-500">Incorrect</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold text-amber-400">{perf.pending_outcomes}</p>
                        <p className="text-[9px] text-zinc-500">Pending</p>
                      </div>
                    </div>
                    
                    {perf.avg_pnl_correct !== undefined && (
                      <div className="grid grid-cols-2 gap-4 text-center mt-3 pt-3 border-t border-white/5">
                        <div>
                          <p className={`text-sm font-bold ${perf.avg_pnl_correct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {perf.avg_pnl_correct >= 0 ? '+' : ''}{perf.avg_pnl_correct?.toFixed(2) || 0}%
                          </p>
                          <p className="text-[9px] text-zinc-500">Avg P&L (Correct)</p>
                        </div>
                        <div>
                          <p className={`text-sm font-bold ${perf.avg_pnl_incorrect >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {perf.avg_pnl_incorrect >= 0 ? '+' : ''}{perf.avg_pnl_incorrect?.toFixed(2) || 0}%
                          </p>
                          <p className="text-[9px] text-zinc-500">Avg P&L (Incorrect)</p>
                        </div>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
};
