import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, Wifi, Brain, Server } from 'lucide-react';
import { PriceDisplay } from './shared';
import { useTickerModal } from '../hooks/useTickerModal';
import { useSystemStatus } from '../contexts/SystemStatusContext';

// Service icon mapping
const SERVICE_ICONS = {
  quotesStream: Activity,
  ibGateway: Wifi,
  ollama: Brain,
  backend: Server,
};

// Compact inline status indicator
const InlineStatus = ({ serviceId, label }) => {
  const { getServiceStatus, STATUS } = useSystemStatus();
  const status = getServiceStatus(serviceId);
  const isConnected = status.status === STATUS.CONNECTED;
  const isConnecting = status.status === STATUS.CONNECTING;
  const Icon = SERVICE_ICONS[serviceId] || Server;
  
  return (
    <div 
      className={`flex items-center gap-1.5 px-2 py-1 rounded transition-colors ${
        isConnected 
          ? 'text-green-400' 
          : isConnecting 
            ? 'text-yellow-400' 
            : 'text-red-400'
      }`}
      title={`${label}: ${isConnected ? 'Connected' : isConnecting ? 'Connecting...' : 'Disconnected'}`}
    >
      <Icon className="w-3 h-3" />
      <span className="text-[10px] font-medium uppercase">{label}</span>
      <div className={`w-1.5 h-1.5 rounded-full ${
        isConnected 
          ? 'bg-green-400 shadow-[0_0_4px_rgba(74,222,128,0.6)]' 
          : isConnecting 
            ? 'bg-yellow-400 animate-pulse shadow-[0_0_4px_rgba(250,204,21,0.6)]' 
            : 'bg-red-400 shadow-[0_0_4px_rgba(248,113,113,0.6)]'
      }`} />
    </div>
  );
};

export const TickerTape = ({ indices = [], isConnected, lastUpdate }) => {
  const { openTickerModal } = useTickerModal();
  
  // Hide entirely when no index data
  if (!indices || indices.length === 0) return null;
  
  return (
    <div className="bg-paper/80 backdrop-blur-md border-b border-white/5 py-2 px-4">
      <div className="flex items-center justify-between">
        {/* Left: Market Indices */}
        <div className="flex items-center gap-4 overflow-x-auto flex-shrink">
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
        
        {/* Right: System Status + Time */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {/* Divider */}
          <div className="w-px h-5 bg-zinc-700 mx-2" />
          
          {/* Inline System Status - All services visible */}
          <div className="flex items-center gap-0.5 bg-black/30 rounded-lg px-1 py-0.5 border border-white/5">
            <InlineStatus serviceId="quotesStream" label="Data" />
            <div className="w-px h-4 bg-zinc-700/50" />
            <InlineStatus serviceId="ibGateway" label="IB" />
            <div className="w-px h-4 bg-zinc-700/50" />
            <InlineStatus serviceId="ollama" label="AI" />
            <div className="w-px h-4 bg-zinc-700/50" />
            <InlineStatus serviceId="backend" label="API" />
          </div>
          
          {/* Time */}
          <div className="w-px h-5 bg-zinc-700 mx-2" />
          <span className="text-zinc-400 text-xs font-mono whitespace-nowrap">
            {lastUpdate ? lastUpdate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '--:--:--'}
          </span>
        </div>
      </div>
    </div>
  );
};

export default TickerTape;
