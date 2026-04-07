import React, { useMemo, memo } from 'react';
import {
  Download, FlaskConical, Rocket, Database,
  Brain, Activity, Radio
} from 'lucide-react';

const QuickStatsBar = memo(({ data }) => {
  const stats = useMemo(() => {
    const runningJobs = (data.simulationJobs || []).filter(j => j.status === 'running');
    const pendingCollections = data.collectionQueue?.overall?.pending || data.collectionQueue?.pending || 0;
    const completedCollections = data.collectionQueue?.overall?.completed || data.collectionQueue?.completed || 0;
    const collectionActive = pendingCollections > 0;
    const readyPromotions = (data.candidates || []).filter(c => c.meets_requirements).length;
    const totalBars = data.historicalBars || 0;

    // Setup model stats
    const setupStatus = data.setupModelsStatus || {};
    const profilesTrained = setupStatus.models_trained || 0;
    const totalProfiles = setupStatus.total_profiles || 17;

    // Training status detail
    const trainingStatus = setupStatus.training_status || {};
    const activeTraining = Object.entries(trainingStatus).filter(([, v]) => v?.status === 'running');

    // Data source
    const ibConnected = data.connectorSummary?.healthy > 0;
    const dataSource = data.dataSource || (ibConnected ? 'IB Gateway' : 'IB Cache');

    return [
      {
        id: 'source',
        icon: Radio,
        label: 'Data Source',
        value: dataSource,
        sub: ibConnected ? 'primary' : 'fallback',
        active: true,
        color: ibConnected ? 'emerald' : 'amber',
        pulse: false
      },
      {
        id: 'data',
        icon: Database,
        label: 'Data',
        value: totalBars > 0 ? (totalBars > 1000000 ? `${(totalBars / 1000000).toFixed(1)}M` : totalBars > 1000 ? `${(totalBars / 1000).toFixed(0)}K` : totalBars) : '0',
        sub: 'bars stored',
        active: totalBars > 0,
        color: totalBars > 100000 ? 'emerald' : totalBars > 0 ? 'blue' : 'zinc'
      },
      {
        id: 'collections',
        icon: Download,
        label: 'Collections',
        value: collectionActive ? pendingCollections.toLocaleString() : 'Idle',
        sub: collectionActive ? 'pending symbols' : `${completedCollections.toLocaleString()} done`,
        active: collectionActive,
        color: collectionActive ? 'amber' : 'zinc',
        pulse: collectionActive
      },
      {
        id: 'models',
        icon: Brain,
        label: 'AI Models',
        value: `${profilesTrained}/${totalProfiles}`,
        sub: activeTraining.length > 0
          ? activeTraining[0][1].message?.slice(0, 30) || 'Training...'
          : profilesTrained === totalProfiles ? 'all trained' : 'profiles trained',
        active: profilesTrained > 0,
        color: activeTraining.length > 0 ? 'cyan' : profilesTrained === totalProfiles ? 'emerald' : profilesTrained > 0 ? 'yellow' : 'zinc',
        pulse: activeTraining.length > 0
      },
      {
        id: 'backtests',
        icon: FlaskConical,
        label: 'Backtests',
        value: runningJobs.length > 0 ? runningJobs.length : 'None',
        sub: runningJobs.length > 0
          ? `running (${runningJobs[0]?.symbols_processed || 0}/${runningJobs[0]?.symbols_total || '?'} sym)`
          : `${(data.simulationJobs || []).filter(j => j.status === 'completed').length} completed`,
        active: runningJobs.length > 0,
        color: runningJobs.length > 0 ? 'cyan' : 'zinc',
        pulse: runningJobs.length > 0
      },
      {
        id: 'promotions',
        icon: Rocket,
        label: 'Promotions',
        value: readyPromotions > 0 ? readyPromotions : 'None',
        sub: readyPromotions > 0 ? 'ready to promote' : 'pending',
        active: readyPromotions > 0,
        color: readyPromotions > 0 ? 'green' : 'zinc',
        pulse: readyPromotions > 0
      },
      {
        id: 'health',
        icon: Activity,
        label: 'Health',
        value: data.connectorSummary ? `${data.connectorSummary.healthy}/${data.connectorSummary.total}` : '--',
        sub: 'connectors',
        active: data.connectorSummary?.healthy > 0,
        color: data.connectorSummary?.healthy === data.connectorSummary?.total ? 'emerald' :
               data.connectorSummary?.healthy > 0 ? 'yellow' : 'zinc'
      }
    ];
  }, [
    data.simulationJobs, data.collectionQueue, data.candidates,
    data.historicalBars, data.connectorSummary, data.setupModelsStatus,
    data.dataSource
  ]);

  const activeCount = stats.filter(s => s.active && s.pulse).length;

  const colorMap = {
    amber: { bg: 'bg-amber-500/10', border: 'border-amber-500/20', text: 'text-amber-400', icon: 'text-amber-400', dot: 'bg-amber-400' },
    cyan: { bg: 'bg-cyan-500/10', border: 'border-cyan-500/20', text: 'text-cyan-400', icon: 'text-cyan-400', dot: 'bg-cyan-400' },
    green: { bg: 'bg-green-500/10', border: 'border-green-500/20', text: 'text-green-400', icon: 'text-green-400', dot: 'bg-green-400' },
    emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', text: 'text-emerald-400', icon: 'text-emerald-400', dot: 'bg-emerald-400' },
    blue: { bg: 'bg-blue-500/10', border: 'border-blue-500/20', text: 'text-blue-400', icon: 'text-blue-400', dot: 'bg-blue-400' },
    yellow: { bg: 'bg-yellow-500/10', border: 'border-yellow-500/20', text: 'text-yellow-400', icon: 'text-yellow-400', dot: 'bg-yellow-400' },
    zinc: { bg: 'bg-white/[0.02]', border: 'border-white/5', text: 'text-zinc-400', icon: 'text-zinc-500', dot: 'bg-zinc-500' }
  };

  return (
    <div className="mb-4" data-testid="quick-stats-bar">
      <div className="flex items-center gap-2 mb-2">
        <div className="flex items-center gap-1.5">
          <div className={`w-1.5 h-1.5 rounded-full ${activeCount > 0 ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'}`} />
          <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
            {activeCount > 0 ? `${activeCount} active` : 'System idle'}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-4 lg:grid-cols-7 gap-2">
        {stats.map((stat) => {
          const colors = colorMap[stat.color] || colorMap.zinc;
          return (
            <div
              key={stat.id}
              className={`relative flex items-center gap-2.5 px-3 py-2.5 rounded-lg border transition-all ${colors.bg} ${colors.border}`}
              data-testid={`quick-stat-${stat.id}`}
            >
              {stat.pulse && (
                <div className={`absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full ${colors.dot} animate-pulse`} />
              )}
              <stat.icon className={`w-4 h-4 flex-shrink-0 ${colors.icon}`} />
              <div className="min-w-0">
                <div className={`text-sm font-bold leading-tight ${stat.active ? colors.text : 'text-zinc-400'}`}>
                  {stat.value}
                </div>
                <div className="text-[9px] text-zinc-500 leading-tight truncate">
                  {stat.sub}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
});

export default QuickStatsBar;
