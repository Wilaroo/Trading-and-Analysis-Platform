import React, { useMemo, memo } from 'react';
import {
  Brain, Rocket, Activity, Zap,
  ArrowUpRight, ArrowDownRight,
  CheckCircle2, AlertTriangle, XCircle
} from 'lucide-react';

const IntelOverview = memo(({ data }) => {
  const metrics = useMemo(() => [
    {
      label: 'AI Accuracy',
      value: data.aiAccuracy ? `${(data.aiAccuracy * 100).toFixed(1)}%` : '--',
      trend: data.aiAccuracyTrend,
      icon: Brain,
      color: 'cyan'
    },
    {
      label: 'Strategies Live',
      value: data.liveStrategies || 0,
      subtext: `${data.paperStrategies || 0} in paper`,
      icon: Rocket,
      color: 'green'
    },
    {
      label: 'Learning Health',
      value: data.learningHealth || '--',
      icon: Activity,
      color: data.learningHealth === 'Healthy' ? 'green' : data.learningHealth === 'Warning' ? 'yellow' : 'red',
      connectorSummary: data.connectorSummary
    },
    {
      label: 'Calibrations Today',
      value: data.calibrationsToday || 0,
      icon: Zap,
      color: 'violet'
    }
  ], [data.aiAccuracy, data.aiAccuracyTrend, data.liveStrategies, data.paperStrategies, data.learningHealth, data.calibrationsToday, data.connectorSummary]);

  const ConnectorDot = ({ summary }) => {
    if (!summary) return null;
    const { healthy, total } = summary;
    const allHealthy = healthy === total;
    const someHealthy = healthy >= Math.ceil(total / 2);
    return (
      <div className="flex items-center gap-1 mt-1" data-testid="connector-health-dots">
        {allHealthy ? (
          <CheckCircle2 className="w-3 h-3 text-green-400" />
        ) : someHealthy ? (
          <AlertTriangle className="w-3 h-3 text-yellow-400" />
        ) : (
          <XCircle className="w-3 h-3 text-red-400" />
        )}
        <span className="text-[12px] text-zinc-500">
          {healthy}/{total} connectors
        </span>
      </div>
    );
  };

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6" data-testid="intel-overview">
      {metrics.map((metric) => (
        <div
          key={metric.label}
          className="relative p-4 rounded-xl border border-white/10 overflow-hidden"
          style={{
            background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.9), rgba(30, 41, 59, 0.8))'
          }}
          data-testid={`intel-metric-${metric.label.toLowerCase().replace(/\s+/g, '-')}`}
        >
          <div
            className="absolute inset-0 opacity-20"
            style={{
              background: `radial-gradient(circle at top right, var(--${metric.color === 'cyan' ? 'primary' : metric.color === 'green' ? 'success' : metric.color === 'violet' ? 'secondary' : 'warning'}-main), transparent 70%)`
            }}
          />
          <div className="relative">
            <div className="flex items-center justify-between mb-2">
              <metric.icon className={`w-4 h-4 text-${metric.color}-400`} />
              {metric.trend !== undefined && (
                <span className={`text-xs flex items-center gap-0.5 ${metric.trend >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {metric.trend >= 0 ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                  {Math.abs(metric.trend).toFixed(1)}%
                </span>
              )}
            </div>
            <div className="text-2xl font-bold text-white mb-0.5">
              {metric.value}
            </div>
            <div className="text-xs text-zinc-400">{metric.label}</div>
            {metric.subtext && (
              <div className="text-[12px] text-zinc-500 mt-1">{metric.subtext}</div>
            )}
            {metric.connectorSummary && (
              <ConnectorDot summary={metric.connectorSummary} />
            )}
          </div>
        </div>
      ))}
    </div>
  );
});

export default IntelOverview;
