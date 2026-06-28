import React from 'react';
import {
  Activity, LineChart, Target, Brain, Gauge, ShieldCheck, Bell, Search,
  TrendingUp, TrendingDown, Settings, Layers, Zap, Eye, BookOpen, Cpu,
} from 'lucide-react';
import {
  Pulse, ChartLine, Target as PhTarget, Brain as PhBrain, Gauge as PhGauge,
  ShieldCheck as PhShield, Bell as PhBell, MagnifyingGlass, TrendUp, TrendDown,
  GearSix, StackSimple, Lightning, Eye as PhEye, BookOpen as PhBook, Cpu as PhCpu,
} from '@phosphor-icons/react';

const ROWS = [
  { label: 'heartbeat', L: Activity, P: Pulse },
  { label: 'chart', L: LineChart, P: ChartLine },
  { label: 'verdict / target', L: Target, P: PhTarget },
  { label: 'AI brain', L: Brain, P: PhBrain },
  { label: 'risk gauge', L: Gauge, P: PhGauge },
  { label: 'safety / shield', L: ShieldCheck, P: PhShield },
  { label: 'alert', L: Bell, P: PhBell },
  { label: 'scan / search', L: Search, P: MagnifyingGlass },
  { label: 'trend up', L: TrendingUp, P: TrendUp },
  { label: 'trend down', L: TrendingDown, P: TrendDown },
  { label: 'settings', L: Settings, P: GearSix },
  { label: 'pipeline / stack', L: Layers, P: StackSimple },
  { label: 'trigger', L: Zap, P: Lightning },
  { label: 'watch', L: Eye, P: PhEye },
  { label: 'journal', L: BookOpen, P: PhBook },
  { label: 'cpu / engine', L: Cpu, P: PhCpu },
];

const CYAN = '#00E5FF';
const cell = {
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  width: 56, height: 56, borderRadius: 10,
  background: 'rgba(15,18,25,0.6)', border: '1px solid rgba(255,255,255,0.08)',
};
const head = { color: CYAN, fontSize: 12, textAlign: 'center', fontWeight: 700, letterSpacing: '0.04em' };

const IconComparePreview = () => (
  <div data-testid="icon-compare" style={{ minHeight: '100vh', background: '#07090E', color: '#fff', fontFamily: 'monospace', padding: 32 }}>
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <h1 style={{ fontSize: 24, letterSpacing: '-0.02em', margin: '0 0 4px' }}>Icon comparison — Lucide vs Phosphor</h1>
      <p style={{ color: '#8B92A5', fontSize: 13, margin: '0 0 28px' }}>
        V6 dark-glass background · cyan accent {CYAN} · 28px · same cockpit concepts both ways. Tell me which set you prefer (or mix).
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '150px 1fr 1fr 1fr', gap: 12, alignItems: 'center' }}>
        <div />
        <div style={head}>LUCIDE<br /><span style={{ color: '#4B5162', fontWeight: 400 }}>(already installed)</span></div>
        <div style={head}>PHOSPHOR<br /><span style={{ color: '#4B5162', fontWeight: 400 }}>regular</span></div>
        <div style={head}>PHOSPHOR<br /><span style={{ color: '#4B5162', fontWeight: 400 }}>duotone</span></div>
        {ROWS.map(({ label, L, P }) => (
          <React.Fragment key={label}>
            <div style={{ color: '#8B92A5', fontSize: 12 }}>{label}</div>
            <div style={{ display: 'flex', justifyContent: 'center' }}><div style={cell}><L size={28} strokeWidth={1.5} color={CYAN} /></div></div>
            <div style={{ display: 'flex', justifyContent: 'center' }}><div style={cell}><P size={28} weight="regular" color={CYAN} /></div></div>
            <div style={{ display: 'flex', justifyContent: 'center' }}><div style={cell}><P size={28} weight="duotone" color={CYAN} /></div></div>
          </React.Fragment>
        ))}
      </div>
      <p style={{ color: '#4B5162', fontSize: 12, marginTop: 28 }}>
        Note: Phosphor also offers thin / light / bold / fill weights — duotone (right column) is its signature "engineered" look.
        Lucide is a single clean stroke set (strokeWidth tunable).
      </p>
    </div>
  </div>
);

export default IconComparePreview;
