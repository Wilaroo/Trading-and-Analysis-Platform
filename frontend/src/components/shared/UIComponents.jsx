import React from 'react';

export const Card = ({ children, className = '', onClick, glow = false }) => (
  <div 
    onClick={onClick}
    className={`bg-[#0A0A0A] border border-white/10 rounded-lg p-4 transition-all duration-200 
      ${onClick ? 'cursor-pointer hover:border-cyan-500/30' : ''} 
      ${glow ? 'shadow-[0_0_15px_rgba(0,229,255,0.15)] border-cyan-500/30' : ''}
      ${className}`}
  >
    {children}
  </div>
);

export const Badge = ({ children, variant = 'info', className = '' }) => {
  const variants = {
    success: 'text-green-400 bg-green-400/10 border-green-400/30',
    warning: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
    error: 'text-red-400 bg-red-400/10 border-red-400/30',
    info: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
    neutral: 'text-zinc-400 bg-zinc-400/10 border-zinc-400/30'
  };
  
  return (
    <span className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-wide border rounded-sm ${variants[variant]} ${className}`}>
      {children}
    </span>
  );
};

export const SectionHeader = ({ icon: Icon, title, action, count }) => (
  <div className="flex items-center justify-between mb-3">
    <div className="flex items-center gap-2">
      <Icon className="w-5 h-5 text-cyan-400" />
      <h3 className="text-sm font-semibold uppercase tracking-wider text-white">{title}</h3>
      {count !== undefined && (
        <span className="text-xs text-zinc-500">({count})</span>
      )}
    </div>
    {action}
  </div>
);
