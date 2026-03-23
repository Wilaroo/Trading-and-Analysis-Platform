import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { PriceDisplay } from './shared';
import { useTickerModal } from '../hooks/useTickerModal';
import StatusDot from './StatusDot';

export const TickerTape = ({ indices = [], isConnected, lastUpdate }) => {
  const { openTickerModal } = useTickerModal();
  
  return (
    <div className="bg-paper/80 backdrop-blur-md border-b border-white/5 py-2 px-4 sticky top-0 z-30">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-6 overflow-x-auto">
          <AnimatePresence mode="popLayout">
            {indices?.map((idx, i) => (
              <motion.div
                key={idx.symbol}
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 10 }}
                transition={{ delay: i * 0.05 }}
                className="flex items-center gap-2 whitespace-nowrap cursor-pointer hover:bg-white/5 px-2 py-1 rounded-md transition-colors"
                onClick={() => openTickerModal(idx.symbol)}
                data-testid={`ticker-tape-${idx.symbol}`}
              >
                <span className="text-zinc-500 text-sm hover:text-cyan-400 transition-colors">{idx.symbol}</span>
                <span className="font-mono text-sm">${idx.price?.toFixed(2) || '--'}</span>
                <PriceDisplay value={idx.change_percent} className="text-sm" />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
        {/* Minimal status - just dot and time */}
        <div className="flex items-center gap-2 text-xs">
          <StatusDot service="quotesStream" size="sm" tooltip="Quotes Stream" />
          {lastUpdate && (
            <span className="text-zinc-500">
              {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export default TickerTape;
