import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity,
  ClipboardList,
  LineChart,
  Zap,
  Target,
  ChevronRight,
  BookOpen
} from 'lucide-react';

const navItems = [
  { id: 'command-center', icon: Target, label: 'Command Center', highlight: true },
  { id: 'trade-journal', icon: ClipboardList, label: 'Trade Journal' },
  { id: 'chart', icon: LineChart, label: 'Charts' },
  { id: 'ib-trading', icon: Zap, label: 'IB Trading' },
  { id: 'glossary', icon: BookOpen, label: 'Glossary & Logic' },
];

export const Sidebar = ({ activeTab, setActiveTab }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <motion.aside
      className="fixed left-0 top-0 h-full z-40 flex flex-col"
      style={{ 
        background: 'rgba(21, 28, 36, 0.95)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        borderRight: '1px solid rgba(255, 255, 255, 0.08)',
        boxShadow: '4px 0 20px rgba(0, 0, 0, 0.3)'
      }}
      initial={{ width: 52 }}
      animate={{ width: isExpanded ? 180 : 52 }}
      onMouseEnter={() => setIsExpanded(true)}
      onMouseLeave={() => setIsExpanded(false)}
    >
      {/* Animated gradient border on right edge */}
      <div className="absolute inset-y-0 right-0 w-[1.5px] overflow-hidden">
        <div 
          className="h-full w-full"
          style={{
            background: 'linear-gradient(180deg, var(--primary-main), var(--secondary-main), var(--accent-main), var(--primary-main))',
            backgroundSize: '100% 200%',
            animation: 'gradient-shift 4s linear infinite'
          }}
        />
      </div>

      {/* Logo */}
      <div className="p-2.5 border-b border-white/[0.08]">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center"
               style={{ 
                 background: 'linear-gradient(135deg, var(--primary-main), var(--secondary-main))',
                 boxShadow: '0 2px 12px var(--primary-glow-strong)'
               }}>
            <Activity className="w-3.5 h-3.5 text-white" />
          </div>
          <AnimatePresence>
            {isExpanded && (
              <motion.span
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="font-bold text-sm whitespace-nowrap text-white"
              >
                Trade<span className="neon-text">Cmd</span>
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-2 px-1.5">
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              data-testid={`nav-${item.id}`}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-2 px-2 py-1.5 mb-0.5 rounded-lg transition-all duration-200 border ${
                isActive
                  ? 'text-white'
                  : item.highlight 
                    ? 'text-cyan-400/80 hover:text-cyan-400 hover:bg-cyan-400/10 border-transparent' 
                    : 'text-zinc-400 hover:text-white hover:bg-white/5 border-transparent'
              }`}
              style={isActive ? {
                background: 'linear-gradient(135deg, rgba(0, 212, 255, 0.2), rgba(168, 85, 247, 0.1))',
                borderColor: 'var(--primary-main)',
                boxShadow: '0 0 15px var(--primary-glow), inset 0 0 12px var(--primary-glow)'
              } : {}}
            >
              <item.icon className={`w-4 h-4 flex-shrink-0 ${isActive ? 'text-cyan-400' : ''}`} />
              <AnimatePresence>
                {isExpanded && (
                  <motion.span
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="whitespace-nowrap flex items-center gap-1.5 text-[11px] font-medium"
                  >
                    {item.label}
                  </motion.span>
                )}
              </AnimatePresence>
              {isActive && isExpanded && (
                <ChevronRight className="w-3 h-3 ml-auto text-cyan-400" />
              )}
            </button>
          );
        })}
      </nav>
      
      {/* Footer */}
      <div className="p-2 border-t border-white/[0.08]">
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-center"
            >
              <p className="text-[9px] font-mono text-zinc-500">
                v2.0 • <span className="text-cyan-400">Compact</span>
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.aside>
  );
};

export default Sidebar;
