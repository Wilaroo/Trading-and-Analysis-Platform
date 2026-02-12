import React, { useState, useEffect, useCallback } from 'react';
import {
  Sunrise,
  TrendingUp,
  Sun,
  Zap,
  Moon,
  RefreshCw,
  Loader2,
  Clock,
  ChevronDown,
  ChevronRight,
  FileText,
  Sparkles,
  CheckCircle2,
  Circle,
  AlertCircle
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';
import { renderTickerAwareContent } from '../utils/tickerUtils';

const REPORT_ICONS = {
  sunrise: Sunrise,
  'trending-up': TrendingUp,
  sun: Sun,
  zap: Zap,
  moon: Moon,
  'file-text': FileText,
};

const REPORT_COLORS = {
  premarket: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', dot: 'bg-amber-400' },
  early_market: { bg: 'bg-cyan-500/10', border: 'border-cyan-500/30', text: 'text-cyan-400', dot: 'bg-cyan-400' },
  midday: { bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', text: 'text-yellow-400', dot: 'bg-yellow-400' },
  power_hour: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', dot: 'bg-orange-400' },
  post_market: { bg: 'bg-purple-500/10', border: 'border-purple-500/30', text: 'text-purple-400', dot: 'bg-purple-400' },
};

const MarketIntelPanel = ({ onTickerSelect }) => {
  const [schedule, setSchedule] = useState([]);
  const [reports, setReports] = useState([]);
  const [activeReport, setActiveReport] = useState(null);
  const [generating, setGenerating] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [autoTriggered, setAutoTriggered] = useState(false);

  const handleTickerClick = (symbol) => {
    if (onTickerSelect) {
      onTickerSelect(symbol);
    }
  };

  const fetchData = useCallback(async () => {
    try {
      const [schedRes, reportsRes, currentRes] = await Promise.all([
        api.get('/api/market-intel/schedule'),
        api.get('/api/market-intel/reports'),
        api.get('/api/market-intel/current'),
      ]);

      setSchedule(schedRes.data?.schedule || []);
      setReports(reportsRes.data?.reports || []);

      if (currentRes.data?.has_report) {
        setActiveReport(currentRes.data.report);
      } else if (reportsRes.data?.reports?.length > 0) {
        setActiveReport(reportsRes.data.reports[reportsRes.data.reports.length - 1]);
      }
    } catch (err) {
      console.log('Market intel fetch error:', err.message);
    }
    setLoading(false);
  }, []);

  // Auto-trigger: on first load, check if we should generate a report
  useEffect(() => {
    const checkAutoTrigger = async () => {
      if (autoTriggered) return;
      try {
        const res = await api.get('/api/market-intel/auto-trigger');
        if (res.data?.should_generate && res.data?.report_type) {
          setAutoTriggered(true);
          setGenerating(res.data.report_type);
          toast.info('Preparing your morning briefing...', { duration: 8000, id: 'auto-trigger' });
          try {
            const genRes = await api.post(`/api/market-intel/generate/${res.data.report_type}?force=false`);
            if (genRes.data?.success) {
              setActiveReport(genRes.data.report);
              toast.success(`${genRes.data.report.label} ready`, { id: 'auto-trigger' });
              fetchData();
            }
          } catch (genErr) {
            console.log('Auto-trigger generation failed:', genErr.message);
          }
          setGenerating(null);
        }
      } catch (err) {
        console.log('Auto-trigger check failed:', err.message);
      }
    };

    fetchData().then(checkAutoTrigger);
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData, autoTriggered]);

  const handleGenerate = async (reportType) => {
    setGenerating(reportType);
    try {
      const res = await api.post(`/api/market-intel/generate/${reportType}?force=true`);
      if (res.data?.success) {
        const report = res.data.report;
        setActiveReport(report);
        toast.success(`${report.label} generated`);
        fetchData();
      }
    } catch (err) {
      toast.error('Failed to generate report');
    }
    setGenerating(null);
  };

  const selectReport = (report) => {
    setActiveReport(report);
  };

  const renderMarkdown = (text) => {
    if (!text) return null;
    return renderTickerAwareContent(text, handleTickerClick);
  };

  if (loading) {
    return (
      <div className="rounded-xl p-2.5" 
           style={{
             background: 'rgba(21, 28, 36, 0.9)',
             backdropFilter: 'blur(20px)',
             WebkitBackdropFilter: 'blur(20px)',
             border: '1px solid rgba(255, 255, 255, 0.1)'
           }}
           data-testid="market-intel-panel">
        <div className="flex items-center gap-1.5 mb-2">
          <Sparkles className="w-4 h-4 text-cyan-400" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-white">Market <span className="neon-text">Intel</span></h3>
        </div>
        <div className="flex items-center justify-center py-4">
          <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl overflow-hidden relative" 
         style={{
           background: 'rgba(21, 28, 36, 0.9)',
           backdropFilter: 'blur(20px)',
           WebkitBackdropFilter: 'blur(20px)',
           border: '1px solid rgba(255, 255, 255, 0.1)',
           boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)'
         }}
         data-testid="market-intel-panel">
      {/* Animated gradient border */}
      <div 
        className="absolute inset-0 rounded-xl pointer-events-none"
        style={{
          padding: '1px',
          background: 'linear-gradient(var(--gradient-angle, 135deg), var(--primary-main), var(--secondary-main), var(--accent-main), var(--primary-main))',
          WebkitMask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
          mask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
          WebkitMaskComposite: 'xor',
          maskComposite: 'exclude',
          opacity: 0.5,
          animation: 'gradient-rotate 6s linear infinite'
        }}
      />
      
      {/* Header - COMPACT */}
      <div className="px-2.5 py-2" style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <div className="w-5 h-5 rounded flex items-center justify-center"
                 style={{
                   background: 'linear-gradient(135deg, var(--primary-main), var(--secondary-main))',
                   boxShadow: '0 2px 8px var(--primary-glow)'
                 }}>
              <Sparkles className="w-3 h-3 text-white" />
            </div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white">Market <span className="neon-text">Intel</span></h3>
          </div>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-zinc-400 hover:text-cyan-400 transition-colors p-0.5"
            data-testid="toggle-intel-panel"
          >
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {expanded && (
        <>
          {/* Report Timeline - Compact schedule */}
          <div className="px-3 py-2 border-b border-white/5" data-testid="report-timeline">
            <div className="flex items-center gap-1 overflow-x-auto pb-1">
              {schedule.map((item) => {
                const colors = REPORT_COLORS[item.type] || REPORT_COLORS.premarket;
                const IconComp = REPORT_ICONS[item.icon] || FileText;
                const isActive = activeReport?.type === item.type;
                const report = reports.find(r => r.type === item.type);

                return (
                  <button
                    key={item.type}
                    onClick={() => report ? selectReport(report) : handleGenerate(item.type)}
                    disabled={generating === item.type}
                    className={`flex items-center gap-1.5 px-2 py-1.5 rounded-md text-[10px] font-medium transition-all whitespace-nowrap ${
                      isActive
                        ? `${colors.bg} ${colors.border} ${colors.text} border`
                        : item.generated
                          ? `bg-zinc-900 text-zinc-400 border border-zinc-800 hover:${colors.text} hover:${colors.border}`
                          : 'bg-zinc-900/50 text-zinc-600 border border-zinc-800/50'
                    } ${!item.is_past && !item.generated ? 'opacity-50' : ''}`}
                    data-testid={`report-btn-${item.type}`}
                    title={item.generated ? `View ${item.label}` : item.is_past ? `Generate ${item.label}` : `Scheduled at ${item.scheduled_time} ET`}
                  >
                    {generating === item.type ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <IconComp className="w-3 h-3" />
                    )}
                    <span className="hidden lg:inline">{item.label.split(' ')[0]}</span>
                    {item.generated ? (
                      <CheckCircle2 className="w-3 h-3 text-green-400" />
                    ) : item.is_past ? (
                      <AlertCircle className="w-3 h-3 text-zinc-600" />
                    ) : (
                      <Circle className="w-3 h-3 text-zinc-700" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Active Report Content */}
          <div className="p-3" data-testid="report-content">
            {activeReport ? (
              <div>
                {/* Report header */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${REPORT_COLORS[activeReport.type]?.dot || 'bg-cyan-400'}`} />
                    <span className="text-xs font-bold text-white">{activeReport.label}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-zinc-500 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {activeReport.generated_at_et}
                    </span>
                    <button
                      onClick={() => handleGenerate(activeReport.type)}
                      disabled={generating === activeReport.type}
                      className="text-zinc-500 hover:text-cyan-400 transition-colors"
                      title="Regenerate"
                      data-testid="regenerate-btn"
                    >
                      {generating === activeReport.type ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <RefreshCw className="w-3 h-3" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Report body */}
                <div className="max-h-[calc(100vh-420px)] overflow-y-auto pr-1 space-y-0" data-testid="report-body">
                  {renderMarkdown(activeReport.content)}
                </div>
              </div>
            ) : (
              <div className="text-center py-6" data-testid="no-report-placeholder">
                <Sparkles className="w-8 h-8 text-zinc-700 mx-auto mb-2" />
                <p className="text-xs text-zinc-500 mb-2">No reports generated yet</p>
                <p className="text-[10px] text-zinc-600 mb-3">
                  Reports auto-generate at scheduled times. Click a report type above to generate now.
                </p>
                <button
                  onClick={() => handleGenerate('premarket')}
                  disabled={generating !== null}
                  className="px-3 py-1.5 bg-cyan-500/15 text-cyan-400 rounded text-xs font-medium hover:bg-cyan-500/25 border border-cyan-500/30 disabled:opacity-50"
                  data-testid="generate-first-report-btn"
                >
                  {generating ? (
                    <span className="flex items-center gap-1.5">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      Generating...
                    </span>
                  ) : (
                    'Generate Pre-Market Briefing'
                  )}
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default MarketIntelPanel;
