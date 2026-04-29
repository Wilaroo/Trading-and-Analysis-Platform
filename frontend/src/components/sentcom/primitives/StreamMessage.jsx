import React from 'react';
import { motion } from 'framer-motion';
import {
  MessageSquare, Brain, Search, AlertCircle, Target, Activity, Radio, Gauge,
} from 'lucide-react';
import ClickableTicker from '../../shared/ClickableTicker';
import { HoverTimestamp } from './HoverTimestamp';

export const StreamMessage = React.memo(({ msg, index }) => {
  const isUser = msg.metadata?.role === 'user';

  // Determine message type for styling
  const getMessageType = () => {
    if (isUser) return 'user';
    if (msg.action_type === 'chat_response') return 'sentcom';
    if (msg.action_type === 'scanning' || msg.type === 'thought') return 'scanner';
    if (msg.type === 'alert' || msg.action_type === 'stop_warning') return 'alert';
    if (msg.type === 'filter') return 'filter';
    if (msg.action_type === 'monitoring') return 'monitor';
    return 'system';
  };

  const messageType = getMessageType();

  // Color schemes for different message types - more transparent/glass-like
  const colorSchemes = {
    user: {
      gradient: 'from-cyan-500/10 via-blue-500/5 to-transparent',
      border: 'border-cyan-500/20',
      icon: 'from-cyan-500 to-blue-500',
      iconColor: 'text-white',
      label: 'text-cyan-400',
      text: 'text-cyan-100',
      badge: 'bg-cyan-500/15 text-cyan-300',
    },
    sentcom: {
      gradient: 'from-violet-500/10 via-purple-500/5 to-transparent',
      border: 'border-violet-500/20',
      icon: 'from-violet-500 to-purple-600',
      iconColor: 'text-white',
      label: 'text-violet-400',
      text: 'text-zinc-200',
      badge: 'bg-violet-500/15 text-violet-300',
    },
    scanner: {
      gradient: 'from-emerald-500/10 via-teal-500/5 to-transparent',
      border: 'border-emerald-500/20',
      icon: 'from-emerald-500 to-teal-500',
      iconColor: 'text-white',
      label: 'text-emerald-400',
      text: 'text-zinc-200',
      badge: 'bg-emerald-500/15 text-emerald-300',
    },
    alert: {
      gradient: 'from-amber-500/10 via-orange-500/5 to-transparent',
      border: 'border-amber-500/20',
      icon: 'from-amber-500 to-orange-500',
      iconColor: 'text-white',
      label: 'text-amber-400',
      text: 'text-zinc-200',
      badge: 'bg-amber-500/15 text-amber-300',
    },
    filter: {
      gradient: 'from-pink-500/10 via-rose-500/5 to-transparent',
      border: 'border-pink-500/20',
      icon: 'from-pink-500 to-rose-500',
      iconColor: 'text-white',
      label: 'text-pink-400',
      text: 'text-zinc-200',
      badge: 'bg-pink-500/15 text-pink-300',
    },
    monitor: {
      gradient: 'from-blue-500/10 via-indigo-500/5 to-transparent',
      border: 'border-blue-500/20',
      icon: 'from-blue-500 to-indigo-500',
      iconColor: 'text-white',
      label: 'text-blue-400',
      text: 'text-zinc-200',
      badge: 'bg-blue-500/15 text-blue-300',
    },
    system: {
      gradient: 'from-zinc-500/10 via-zinc-600/5 to-transparent',
      border: 'border-zinc-500/20',
      icon: 'from-zinc-500 to-zinc-600',
      iconColor: 'text-white',
      label: 'text-zinc-400',
      text: 'text-zinc-300',
      badge: 'bg-zinc-500/15 text-zinc-300',
    },
  };

  const colors = colorSchemes[messageType];

  // Get icon based on message type
  const getIcon = () => {
    switch (messageType) {
      case 'user': return <MessageSquare className="w-4 h-4" />;
      case 'sentcom': return <Brain className="w-4 h-4" />;
      case 'scanner': return <Search className="w-4 h-4" />;
      case 'alert': return <AlertCircle className="w-4 h-4" />;
      case 'filter': return <Target className="w-4 h-4" />;
      case 'monitor': return <Activity className="w-4 h-4" />;
      default: return <Radio className="w-4 h-4" />;
    }
  };

  // Get label based on message type
  const getLabel = () => {
    switch (messageType) {
      case 'user': return 'YOU';
      case 'sentcom': return 'SENTCOM';
      case 'scanner': return 'SCANNER';
      case 'alert': return 'ALERT';
      case 'filter': return 'SMART FILTER';
      case 'monitor': return 'MONITOR';
      default: return 'SYSTEM';
    }
  };

  return (
    <HoverTimestamp
      timestamp={msg.timestamp}
      position={isUser ? 'right' : 'left'}
    >
      <motion.div
        initial={{ opacity: 0, y: 10, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ delay: Math.min(index * 0.05, 0.3), type: 'spring', stiffness: 200 }}
        className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
      >
        {/* Icon with gradient background */}
        <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${colors.icon} flex items-center justify-center flex-shrink-0 shadow-lg ${colors.iconColor}`}>
          {getIcon()}
        </div>

        {/* Message bubble with glassmorphism */}
        <div className={`flex-1 min-w-0 max-w-[85%] ${isUser ? 'text-right' : ''}`}>
          <div
            className={`
              relative overflow-hidden rounded-2xl p-4
              bg-gradient-to-br ${colors.gradient}
              border ${colors.border}
              backdrop-blur-xl bg-white/[0.02]
              shadow-lg shadow-black/5
              ${isUser ? 'rounded-tr-sm' : 'rounded-tl-sm'}
            `}
          >
            {/* Subtle glass reflection */}
            <div className="absolute inset-0 bg-gradient-to-br from-white/[0.03] via-transparent to-transparent pointer-events-none" />

            {/* Header with label and symbol */}
            <div className={`relative flex items-center gap-2 mb-2 ${isUser ? 'justify-end' : ''}`}>
              <span className={`text-[12px] font-bold uppercase tracking-wider ${colors.label}`}>
                {getLabel()}
              </span>
              {msg.symbol && (
                <ClickableTicker symbol={msg.symbol} variant="badge" className={`text-[12px] ${colors.badge}`} />
              )}
            </div>

            {/* Message content */}
            <p className={`relative text-sm leading-relaxed ${colors.text}`}>
              {msg.content}
            </p>

            {/* Confidence indicator */}
            {msg.confidence && (
              <div className={`relative flex items-center gap-1.5 mt-3 pt-2 border-t border-white/10 ${isUser ? 'justify-end' : ''}`}>
                <Gauge className={`w-3 h-3 ${colors.label}`} />
                <span className={`text-[12px] ${colors.label}`}>
                  Confidence: {msg.confidence}%
                </span>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </HoverTimestamp>
  );
}, (prevProps, nextProps) => {
  // Custom comparison - only re-render if ID or content changed
  return prevProps.msg.id === nextProps.msg.id &&
         prevProps.msg.content === nextProps.msg.content;
});

StreamMessage.displayName = 'StreamMessage';
