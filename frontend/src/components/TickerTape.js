import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Wifi, WifiOff } from 'lucide-react';
import { PriceDisplay } from './shared';

export const TickerTape = ({ indices = [], isConnected, lastUpdate }) => {
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
                className="flex items-center gap-2 whitespace-nowrap"
              >
                <span className="text-zinc-500 text-sm">{idx.symbol}</span>
                <span className="font-mono text-sm">${idx.price?.toFixed(2) || '--'}</span>
                <PriceDisplay value={idx.change_percent} className="text-sm" />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {isConnected ? (
            <span className="flex items-center gap-1 text-green-400">
              <Wifi className="w-3 h-3" /> LIVE
            </span>
          ) : (
            <span className="flex items-center gap-1 text-zinc-500">
              <WifiOff className="w-3 h-3" /> OFFLINE
            </span>
          )}
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
