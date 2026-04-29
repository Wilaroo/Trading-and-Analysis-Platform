import React from 'react';
import { motion } from 'framer-motion';
import { Brain } from 'lucide-react';

export const TypingIndicator = ({ agentName = 'SENTCOM' }) => (
  <motion.div
    initial={{ opacity: 0, y: 10, scale: 0.98 }}
    animate={{ opacity: 1, y: 0, scale: 1 }}
    exit={{ opacity: 0, y: -10, scale: 0.98 }}
    className="flex items-start gap-3"
  >
    <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center flex-shrink-0 shadow-lg">
      <Brain className="w-4 h-4 text-white" />
    </div>
    <div className="flex-1 min-w-0 max-w-[85%]">
      <div className="relative overflow-hidden rounded-2xl rounded-tl-sm p-4 bg-gradient-to-br from-violet-500/10 via-purple-500/5 to-transparent border border-violet-500/20 backdrop-blur-xl bg-white/[0.02] shadow-lg shadow-black/5">
        <div className="absolute inset-0 bg-gradient-to-br from-white/[0.03] via-transparent to-transparent pointer-events-none" />
        <div className="relative flex items-center gap-2 mb-2">
          <span className="text-[12px] font-bold uppercase tracking-wider text-violet-400">
            {agentName}
          </span>
        </div>
        <div className="relative flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <motion.span
              className="w-2 h-2 rounded-full bg-violet-400"
              animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
              transition={{ duration: 1.2, repeat: Infinity, delay: 0 }}
            />
            <motion.span
              className="w-2 h-2 rounded-full bg-violet-400"
              animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
              transition={{ duration: 1.2, repeat: Infinity, delay: 0.2 }}
            />
            <motion.span
              className="w-2 h-2 rounded-full bg-violet-400"
              animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
              transition={{ duration: 1.2, repeat: Infinity, delay: 0.4 }}
            />
          </div>
          <span className="text-xs text-violet-300/70 ml-1">thinking...</span>
        </div>
      </div>
    </div>
  </motion.div>
);
