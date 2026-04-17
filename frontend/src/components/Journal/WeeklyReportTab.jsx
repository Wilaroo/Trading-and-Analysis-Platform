import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Calendar,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Target,
  CheckCircle,
  XCircle,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Save,
  Star,
  Zap,
  BarChart3,
  BookOpen,
  Lightbulb,
  Award,
  Settings,
  Brain
} from 'lucide-react';
import api from '../../utils/api';

// Card component
const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

// Stat Badge
const StatBadge = ({ label, value, color = 'primary', icon: Icon }) => (
  <div className={`flex items-center gap-2 px-3 py-2 rounded-lg bg-${color}/10 border border-${color}/20`}>
    {Icon && <Icon className={`w-4 h-4 text-${color}`} />}
    <span className="text-xs text-zinc-400">{label}</span>
    <span className={`font-bold text-${color}`}>{value}</span>
  </div>
);

// Rating Stars
const RatingStars = ({ rating, onChange, label }) => (
  <div className="flex items-center gap-2">
    <span className="text-sm text-zinc-400 w-24">{label}</span>
    <div className="flex gap-1">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          onClick={() => onChange(star)}
          className={`p-0.5 transition-colors ${
            star <= rating ? 'text-yellow-400' : 'text-zinc-600 hover:text-zinc-400'
          }`}
        >
          <Star className={`w-5 h-5 ${star <= rating ? 'fill-yellow-400' : ''}`} />
        </button>
      ))}
    </div>
  </div>
);

// Performance Snapshot Section
const PerformanceSnapshot = ({ performance }) => {
  if (!performance) return null;
  
  const winRateColor = performance.win_rate >= 0.5 ? 'green-400' : 'red-400';
  const pnlColor = performance.total_pnl >= 0 ? 'green-400' : 'red-400';
  const changeArrow = performance.win_rate_change > 0 ? '↑' : performance.win_rate_change < 0 ? '↓' : '';
  
  return (
    <Card className="bg-gradient-to-br from-primary/5 to-transparent">
      <div className="flex items-center gap-2 mb-4">
        <BarChart3 className="w-5 h-5 text-primary" />
        <h3 className="font-semibold">Performance Snapshot</h3>
      </div>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="text-center p-3 bg-white/5 rounded-lg">
          <p className="text-2xl font-bold">{performance.total_trades}</p>
          <p className="text-xs text-zinc-400">Total Trades</p>
        </div>
        
        <div className="text-center p-3 bg-white/5 rounded-lg">
          <p className={`text-2xl font-bold text-${winRateColor}`}>
            {(performance.win_rate * 100).toFixed(0)}%
            {changeArrow && (
              <span className="text-sm ml-1">
                {changeArrow}{Math.abs(performance.win_rate_change).toFixed(0)}%
              </span>
            )}
          </p>
          <p className="text-xs text-zinc-400">{performance.wins}W / {performance.losses}L</p>
        </div>
        
        <div className="text-center p-3 bg-white/5 rounded-lg">
          <p className={`text-2xl font-bold text-${pnlColor}`}>
            ${performance.total_pnl?.toFixed(0) || 0}
          </p>
          <p className="text-xs text-zinc-400">Total P&L</p>
        </div>
        
        <div className="text-center p-3 bg-white/5 rounded-lg">
          <p className="text-2xl font-bold text-primary">
            {performance.profit_factor?.toFixed(2) || '0.00'}
          </p>
          <p className="text-xs text-zinc-400">Profit Factor</p>
        </div>
      </div>
      
      {(performance.best_day || performance.worst_day) && (
        <div className="grid grid-cols-2 gap-4 mt-4">
          {performance.best_day && (
            <div className="flex items-center gap-3 p-3 bg-green-500/10 rounded-lg border border-green-500/20">
              <TrendingUp className="w-5 h-5 text-green-400" />
              <div>
                <p className="text-xs text-zinc-400">Best Day</p>
                <p className="font-medium text-green-400">
                  {performance.best_day} (+${performance.best_day_pnl?.toFixed(0) || 0})
                </p>
              </div>
            </div>
          )}
          {performance.worst_day && (
            <div className="flex items-center gap-3 p-3 bg-red-500/10 rounded-lg border border-red-500/20">
              <TrendingDown className="w-5 h-5 text-red-400" />
              <div>
                <p className="text-xs text-zinc-400">Worst Day</p>
                <p className="font-medium text-red-400">
                  {performance.worst_day} (${performance.worst_day_pnl?.toFixed(0) || 0})
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};

// Context Insights Section
const ContextInsights = ({ topContexts, strugglingContexts }) => {
  const hasData = (topContexts?.length > 0) || (strugglingContexts?.length > 0);
  if (!hasData) return null;
  
  return (
    <div className="grid md:grid-cols-2 gap-4">
      {/* Top Performers */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <Target className="w-5 h-5 text-green-400" />
          <h3 className="font-semibold">Top Performing Contexts</h3>
        </div>
        {topContexts?.length > 0 ? (
          <div className="space-y-2">
            {topContexts.map((ctx, i) => (
              <div key={i} className="flex items-center justify-between p-2 bg-green-500/5 rounded border border-green-500/10">
                <div className="flex items-center gap-2">
                  <span className="text-green-400 font-mono text-sm">#{i+1}</span>
                  <span className="text-sm">{ctx.setup_type}</span>
                  <span className="text-xs text-zinc-500">+ {ctx.market_regime} + {ctx.time_of_day}</span>
                </div>
                <span className="text-green-400 font-bold">{(ctx.win_rate * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-zinc-500 text-sm">No context data yet</p>
        )}
      </Card>
      
      {/* Struggling Contexts */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle className="w-5 h-5 text-yellow-400" />
          <h3 className="font-semibold">Areas to Improve</h3>
        </div>
        {strugglingContexts?.length > 0 ? (
          <div className="space-y-2">
            {strugglingContexts.map((ctx, i) => (
              <div key={i} className="flex items-center justify-between p-2 bg-yellow-500/5 rounded border border-yellow-500/10">
                <div className="flex items-center gap-2">
                  <span className="text-yellow-400">!</span>
                  <span className="text-sm">{ctx.setup_type}</span>
                  <span className="text-xs text-zinc-500">+ {ctx.market_regime}</span>
                </div>
                <span className="text-yellow-400 font-bold">{(ctx.win_rate * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-zinc-500 text-sm">No struggling contexts identified</p>
        )}
      </Card>
    </div>
  );
};

// Edge Alerts Section
const EdgeAlerts = ({ alerts }) => {
  if (!alerts?.length) return null;
  
  return (
    <Card className="border-red-500/20">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle className="w-5 h-5 text-red-400" />
        <h3 className="font-semibold text-red-400">Edge Decay Alerts</h3>
      </div>
      <div className="space-y-2">
        {alerts.map((alert, i) => (
          <div key={i} className={`p-3 rounded-lg border ${
            alert.severity === 'severe' ? 'bg-red-500/10 border-red-500/30' :
            alert.severity === 'moderate' ? 'bg-yellow-500/10 border-yellow-500/30' :
            'bg-zinc-500/10 border-zinc-500/30'
          }`}>
            <div className="flex items-center justify-between">
              <span className="font-medium">{alert.edge_name}</span>
              <span className={`text-xs px-2 py-0.5 rounded ${
                alert.severity === 'severe' ? 'bg-red-500/20 text-red-400' :
                alert.severity === 'moderate' ? 'bg-yellow-500/20 text-yellow-400' :
                'bg-zinc-500/20 text-zinc-400'
              }`}>
                {alert.severity?.toUpperCase()}
              </span>
            </div>
            <p className="text-sm text-zinc-400 mt-1">{alert.message}</p>
            <p className="text-xs text-zinc-500 mt-1">
              {(alert.all_time_win_rate * 100).toFixed(0)}% → {(alert.recent_win_rate * 100).toFixed(0)}% 
              ({alert.drop_percent?.toFixed(0)}% drop)
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
};

// Calibration Suggestions Section
const CalibrationSuggestions = ({ suggestions }) => {
  if (!suggestions?.length) return null;
  
  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <Settings className="w-5 h-5 text-blue-400" />
        <h3 className="font-semibold">Calibration Suggestions</h3>
      </div>
      <div className="space-y-2">
        {suggestions.map((sug, i) => (
          <div key={i} className="p-3 bg-blue-500/5 rounded-lg border border-blue-500/10">
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm">{sug.parameter}</span>
              <span className={`text-xs px-2 py-0.5 rounded ${
                sug.confidence === 'high' ? 'bg-green-500/20 text-green-400' :
                sug.confidence === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                'bg-zinc-500/20 text-zinc-400'
              }`}>
                {sug.confidence}
              </span>
            </div>
            <p className="text-sm text-zinc-400 mt-1">{sug.reason}</p>
            <p className="text-xs text-blue-400 mt-1">
              {sug.current_value} → {sug.suggested_value}
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
};

// Confirmation Insights Section
const ConfirmationInsights = ({ insights }) => {
  if (!insights?.length) return null;
  
  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-5 h-5 text-purple-400" />
        <h3 className="font-semibold">Confirmation Signal Insights</h3>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {insights.map((insight, i) => (
          <div key={i} className={`p-2 rounded-lg ${
            insight.is_effective ? 'bg-green-500/5 border border-green-500/10' : 'bg-red-500/5 border border-red-500/10'
          }`}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{insight.confirmation_type}</span>
              <span className={insight.win_rate_lift > 0 ? 'text-green-400' : 'text-red-400'}>
                {insight.win_rate_lift > 0 ? '+' : ''}{insight.win_rate_lift?.toFixed(0)}%
              </span>
            </div>
            {insight.recommendation && (
              <p className="text-xs text-zinc-400 mt-1">{insight.recommendation}</p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
};

// Playbook Focus Section
const PlaybookFocus = ({ focus }) => {
  if (!focus?.length) return null;
  
  const focusItems = focus.filter(f => f.action === 'focus');
  const reviewItems = focus.filter(f => f.action === 'review');
  const avoidItems = focus.filter(f => f.action === 'avoid');
  
  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <BookOpen className="w-5 h-5 text-primary" />
        <h3 className="font-semibold">Playbook Focus</h3>
      </div>
      <div className="space-y-3">
        {focusItems.length > 0 && (
          <div>
            <p className="text-xs text-green-400 font-medium mb-1">FOCUS ON</p>
            {focusItems.map((item, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <CheckCircle className="w-4 h-4 text-green-400" />
                <span>{item.playbook_name}</span>
                <span className="text-zinc-500">({(item.win_rate * 100).toFixed(0)}% win)</span>
              </div>
            ))}
          </div>
        )}
        {reviewItems.length > 0 && (
          <div>
            <p className="text-xs text-yellow-400 font-medium mb-1">REVIEW</p>
            {reviewItems.map((item, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <AlertTriangle className="w-4 h-4 text-yellow-400" />
                <span>{item.playbook_name}</span>
                <span className="text-zinc-500">{item.reason}</span>
              </div>
            ))}
          </div>
        )}
        {avoidItems.length > 0 && (
          <div>
            <p className="text-xs text-red-400 font-medium mb-1">AVOID</p>
            {avoidItems.map((item, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <XCircle className="w-4 h-4 text-red-400" />
                <span>{item.playbook_name}</span>
                <span className="text-zinc-500">{item.reason}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
};

// Personal Reflection Section (Editable)
const PersonalReflection = ({ reflection, onChange, onSave, saving }) => {
  const [localReflection, setLocalReflection] = useState(reflection || {});
  
  useEffect(() => {
    setLocalReflection(reflection || {});
  }, [reflection]);
  
  const handleChange = (field, value) => {
    const updated = { ...localReflection, [field]: value };
    setLocalReflection(updated);
    onChange(updated);
  };
  
  return (
    <Card className="bg-gradient-to-br from-purple-500/5 to-transparent border-purple-500/20">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-purple-400" />
          <h3 className="font-semibold">Personal Reflection</h3>
        </div>
        <button
          onClick={onSave}
          disabled={saving}
          className="btn-primary text-sm flex items-center gap-2"
        >
          {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save
        </button>
      </div>
      
      <div className="space-y-4">
        {/* Ratings */}
        <div className="flex flex-wrap gap-6">
          <RatingStars
            label="Mood"
            rating={localReflection.mood_rating || 3}
            onChange={(val) => handleChange('mood_rating', val)}
          />
          <RatingStars
            label="Confidence"
            rating={localReflection.confidence_rating || 3}
            onChange={(val) => handleChange('confidence_rating', val)}
          />
        </div>
        
        {/* Text Fields */}
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-zinc-400 mb-1">What Went Well</label>
            <textarea
              value={localReflection.what_went_well || ''}
              onChange={(e) => handleChange('what_went_well', e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg p-3 text-sm resize-none focus:border-primary/50 focus:outline-none"
              rows={3}
              placeholder="Wins, good decisions, patterns that worked..."
            />
          </div>
          <div>
            <label className="block text-sm text-zinc-400 mb-1">What to Improve</label>
            <textarea
              value={localReflection.what_to_improve || ''}
              onChange={(e) => handleChange('what_to_improve', e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg p-3 text-sm resize-none focus:border-primary/50 focus:outline-none"
              rows={3}
              placeholder="Mistakes, missed opportunities, areas to work on..."
            />
          </div>
        </div>
        
        <div>
          <label className="block text-sm text-zinc-400 mb-1">Key Lessons</label>
          <textarea
            value={localReflection.key_lessons || ''}
            onChange={(e) => handleChange('key_lessons', e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg p-3 text-sm resize-none focus:border-primary/50 focus:outline-none"
            rows={2}
            placeholder="Most important takeaways from this week..."
          />
        </div>
        
        <div>
          <label className="block text-sm text-zinc-400 mb-1">Goals for Next Week</label>
          <textarea
            value={localReflection.goals_for_next_week || ''}
            onChange={(e) => handleChange('goals_for_next_week', e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg p-3 text-sm resize-none focus:border-primary/50 focus:outline-none"
            rows={2}
            placeholder="Focus areas, specific targets, rules to follow..."
          />
        </div>
        
        <div>
          <label className="block text-sm text-zinc-400 mb-1">Additional Notes</label>
          <textarea
            value={localReflection.notes || ''}
            onChange={(e) => handleChange('notes', e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg p-3 text-sm resize-none focus:border-primary/50 focus:outline-none"
            rows={2}
            placeholder="Any other thoughts..."
          />
        </div>
      </div>
    </Card>
  );
};

// Report Archive Sidebar
const ReportArchive = ({ reports, currentReportId, onSelect }) => {
  if (!reports?.length) return null;
  
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-zinc-400 mb-2">Report History</h4>
      {reports.map((report) => (
        <button
          key={report.id}
          onClick={() => onSelect(report.id)}
          className={`w-full text-left p-3 rounded-lg transition-all ${
            report.id === currentReportId
              ? 'bg-primary/20 border border-primary/30'
              : 'bg-white/5 border border-white/10 hover:border-white/20'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="font-medium">Week {report.week_number}</span>
            {report.is_complete && <CheckCircle className="w-4 h-4 text-green-400" />}
          </div>
          <p className="text-xs text-zinc-500 mt-1">
            {report.week_start} - {report.week_end}
          </p>
        </button>
      ))}
    </div>
  );
};

// Main Component
const WeeklyReportTab = () => {
  const [report, setReport] = useState(null);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reflection, setReflection] = useState({});
  
  // Load current report
  const loadCurrentReport = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/journal/weekly-report/current', { timeout: 15000 });
      if (res.data.success && res.data.report) {
        setReport(res.data.report);
        setReflection(res.data.report.reflection || {});
      }
    } catch (err) {
      console.error('Failed to load weekly report:', err);
    } finally {
      setLoading(false);
    }
  }, []);
  
  // Load report archive
  const loadArchive = useCallback(async () => {
    try {
      const res = await api.get('/api/journal/weekly-report?limit=12', { timeout: 10000 });
      if (res.data.success) {
        setReports(res.data.reports || []);
      }
    } catch (err) {
      console.error('Failed to load report archive:', err);
    }
  }, []);
  
  // Load specific report
  const loadReport = async (reportId) => {
    setLoading(true);
    try {
      const res = await api.get(`/api/journal/weekly-report/${reportId}`);
      if (res.data.success && res.data.report) {
        setReport(res.data.report);
        setReflection(res.data.report.reflection || {});
      }
    } catch (err) {
      console.error('Failed to load report:', err);
    } finally {
      setLoading(false);
    }
  };
  
  // Regenerate report
  const regenerateReport = async () => {
    setLoading(true);
    try {
      const res = await api.post('/api/journal/weekly-report/generate?force=true');
      if (res.data.success && res.data.report) {
        setReport(res.data.report);
        setReflection(res.data.report.reflection || {});
        loadArchive();
      }
    } catch (err) {
      console.error('Failed to regenerate report:', err);
    } finally {
      setLoading(false);
    }
  };
  
  // Save reflection
  const saveReflection = async () => {
    if (!report?.id) return;
    setSaving(true);
    try {
      await api.put(`/api/journal/weekly-report/${report.id}/reflection`, reflection);
    } catch (err) {
      console.error('Failed to save reflection:', err);
    } finally {
      setSaving(false);
    }
  };
  
  // Navigate weeks
  const navigateWeek = (direction) => {
    const currentIndex = reports.findIndex(r => r.id === report?.id);
    if (currentIndex === -1) return;
    
    const newIndex = direction === 'prev' ? currentIndex + 1 : currentIndex - 1;
    if (newIndex >= 0 && newIndex < reports.length) {
      loadReport(reports[newIndex].id);
    }
  };
  
  useEffect(() => {
    loadCurrentReport();
    loadArchive();
  }, [loadCurrentReport, loadArchive]);
  
  if (loading && !report) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }
  
  return (
    <div className="space-y-6" data-testid="weekly-report-tab">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigateWeek('prev')}
            disabled={!reports.length || reports.findIndex(r => r.id === report?.id) >= reports.length - 1}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          
          <div className="text-center">
            <h2 className="text-xl font-bold flex items-center gap-2">
              <Calendar className="w-5 h-5 text-primary" />
              Week {report?.week_number || '-'}, {report?.year || '-'}
            </h2>
            <p className="text-sm text-zinc-400">
              {report?.week_start} - {report?.week_end}
            </p>
          </div>
          
          <button
            onClick={() => navigateWeek('next')}
            disabled={!reports.length || reports.findIndex(r => r.id === report?.id) <= 0}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
        
        <button
          onClick={regenerateReport}
          disabled={loading}
          className="btn-secondary flex items-center gap-2 text-sm"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Regenerate
        </button>
      </div>
      
      {report ? (
        <div className="grid lg:grid-cols-4 gap-6">
          {/* Main Content */}
          <div className="lg:col-span-3 space-y-6">
            {/* Performance */}
            <PerformanceSnapshot performance={report.performance} />
            
            {/* Context Insights */}
            <ContextInsights
              topContexts={report.top_contexts}
              strugglingContexts={report.struggling_contexts}
            />
            
            {/* Edge Alerts */}
            <EdgeAlerts alerts={report.edge_alerts} />
            
            {/* Two Column Layout */}
            <div className="grid md:grid-cols-2 gap-4">
              <CalibrationSuggestions suggestions={report.calibration_suggestions} />
              <ConfirmationInsights insights={report.confirmation_insights} />
            </div>
            
            {/* Playbook Focus */}
            <PlaybookFocus focus={report.playbook_focus} />
            
            {/* Personal Reflection */}
            <PersonalReflection
              reflection={reflection}
              onChange={setReflection}
              onSave={saveReflection}
              saving={saving}
            />
          </div>
          
          {/* Sidebar */}
          <div className="lg:col-span-1">
            <div className="sticky top-4">
              <ReportArchive
                reports={reports}
                currentReportId={report?.id}
                onSelect={loadReport}
              />
            </div>
          </div>
        </div>
      ) : (
        <Card className="text-center py-12">
          <Lightbulb className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium mb-2">No Weekly Report Yet</h3>
          <p className="text-zinc-400 mb-4">Generate your first weekly intelligence report</p>
          <button
            onClick={regenerateReport}
            className="btn-primary"
          >
            Generate Report
          </button>
        </Card>
      )}
    </div>
  );
};

export default WeeklyReportTab;
