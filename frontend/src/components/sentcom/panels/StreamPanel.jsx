import React, { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Activity, AlertCircle, Brain, Flame, Gauge, Loader, Radio, Target } from 'lucide-react';
import ClickableTicker from '../../shared/ClickableTicker';
import { GlassCard } from '../primitives/GlassCard';

export const StreamPanel = ({ messages, loading }) => {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [messages]);

  if (loading && messages.length === 0) {
    return (
      <GlassCard className="p-4 h-full">
        <div className="flex items-center justify-center h-full">
          <Loader className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  const getMessageIcon = (type, actionType) => {
    if (type === 'thought' || actionType === 'scanning') return <Brain className="w-4 h-4 text-violet-400" />;
    if (type === 'alert') return <AlertCircle className="w-4 h-4 text-amber-400" />;
    if (type === 'filter') return <Target className="w-4 h-4 text-cyan-400" />;
    if (actionType === 'monitoring') return <Activity className="w-4 h-4 text-emerald-400" />;
    return <Radio className="w-4 h-4 text-zinc-400" />;
  };

  const getMessageLabel = (type, actionType) => {
    if (actionType === 'scanning') return 'SCANNER';
    if (actionType === 'monitoring') return 'MONITOR';
    if (type === 'filter') return 'FILTER';
    if (type === 'alert') return 'ALERT';
    if (type === 'chat') return 'CHAT';
    return 'SENTCOM';
  };

  return (
    <GlassCard gradient className="p-4 h-full flex flex-col">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
          <Flame className="w-3 h-3 text-violet-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Live Stream</span>
      </div>
      
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 pr-2 custom-scrollbar">
        {messages.length === 0 ? (
          <div className="text-center py-8">
            <Radio className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
            <p className="text-sm text-zinc-500">Waiting for activity...</p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <motion.div
              key={msg.id || i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="relative"
            >
              <div className="flex items-start gap-3 p-3 rounded-xl bg-black/30 border border-white/5">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500/30 to-purple-600/30 flex items-center justify-center flex-shrink-0">
                  {getMessageIcon(msg.type, msg.action_type)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-medium text-violet-400 uppercase">
                      {getMessageLabel(msg.type, msg.action_type)}
                    </span>
                    {msg.symbol && (
                      <ClickableTicker symbol={msg.symbol} variant="badge" />
                    )}
                    <span className="text-[10px] text-zinc-600">
                      {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-300 leading-relaxed">{msg.content}</p>
                  {msg.confidence && (
                    <div className="flex items-center gap-1 mt-2">
                      <Gauge className="w-3 h-3 text-violet-400" />
                      <span className="text-[10px] text-violet-400">Confidence: {msg.confidence}%</span>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          ))
        )}
      </div>
    </GlassCard>
  );
};
