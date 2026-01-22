import React from 'react';
import { motion } from 'framer-motion';
import { TrendingUp, TrendingDown } from 'lucide-react';

// ===================== SHARED UI COMPONENTS =====================

// Card component
export const Card = ({ children, className = '', hover = true }) => (
  <motion.div
    className={`glass-card rounded-xl p-6 ${className}`}
    whileHover={hover ? { scale: 1.01, y: -2 } : {}}
    transition={{ duration: 0.2 }}
  >
    {children}
  </motion.div>
);

// Stats Card
export const StatsCard = ({ icon: Icon, title, value, subtitle, trend, color = 'primary' }) => (
  <Card>
    <div className="flex items-start justify-between">
      <div className={`p-3 rounded-xl bg-${color}/10`}>
        <Icon className={`w-6 h-6 text-${color}`} />
      </div>
      {trend !== undefined && (
        <span className={`flex items-center gap-1 text-sm ${trend >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {trend >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          {Math.abs(trend).toFixed(2)}%
        </span>
      )}
    </div>
    <div className="mt-4">
      <p className="text-zinc-500 text-sm">{title}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
      {subtitle && <p className="text-xs text-zinc-500 mt-1">{subtitle}</p>}
    </div>
  </Card>
);

// Price Display with color based on value
export const PriceDisplay = ({ value, className = '' }) => {
  if (value === null || value === undefined) return <span className="text-zinc-500">--</span>;
  const isPositive = value >= 0;
  return (
    <span className={`font-mono ${isPositive ? 'text-green-400' : 'text-red-400'} ${className}`}>
      {isPositive ? '+' : ''}{typeof value === 'number' ? value.toFixed(2) : value}%
    </span>
  );
};

// Loading Skeleton
export const Skeleton = ({ className = '' }) => (
  <div className={`animate-pulse bg-white/5 rounded ${className}`} />
);

// Badge component
export const Badge = ({ children, variant = 'default', className = '' }) => {
  const variants = {
    default: 'bg-white/10 text-zinc-400 border-white/10',
    primary: 'bg-primary/20 text-primary border-primary/30',
    success: 'bg-green-500/20 text-green-400 border-green-500/30',
    warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    danger: 'bg-red-500/20 text-red-400 border-red-500/30',
    info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    purple: 'bg-purple-500/20 text-purple-400 border-purple-500/30'
  };
  
  return (
    <span className={`badge ${variants[variant] || variants.default} ${className}`}>
      {children}
    </span>
  );
};

// Empty State
export const EmptyState = ({ icon: Icon, title, description }) => (
  <div className="text-center py-12">
    {Icon && <Icon className="w-12 h-12 text-zinc-600 mx-auto mb-4" />}
    <h3 className="text-lg font-semibold text-zinc-400">{title}</h3>
    {description && <p className="text-zinc-500 text-sm mt-2">{description}</p>}
  </div>
);

export default Card;
