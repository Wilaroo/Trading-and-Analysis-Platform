import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { formatFullTime, formatRelativeTime } from '../utils/time';

export const HoverTimestamp = ({ timestamp, children, position = 'left' }) => {
  const [showFull, setShowFull] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div
      className="relative group"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => { setIsHovered(false); setShowFull(false); }}
    >
      {children}

      <AnimatePresence>
        {isHovered && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            className={`absolute ${position === 'right' ? 'right-0' : 'left-0'} -top-6 z-50`}
          >
            <button
              onClick={() => setShowFull(!showFull)}
              className="px-2 py-0.5 rounded bg-zinc-800/95 border border-white/10 text-[12px] text-zinc-400 hover:text-zinc-300 whitespace-nowrap shadow-lg backdrop-blur-sm transition-colors"
            >
              {showFull ? formatFullTime(timestamp) : formatRelativeTime(timestamp)}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
