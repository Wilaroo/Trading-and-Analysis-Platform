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
        background: 'rgba(8, 8, 18, 0.75)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        borderRight: '1px solid rgba(255, 255, 255, 0.08)',
        boxShadow: '4px 0 30px rgba(0, 0, 0, 0.3), inset -1px 0 0 rgba(255, 255, 255, 0.05)'
      }}
      initial={{ width: 64 }}
      animate={{ width: isExpanded ? 220 : 64 }}
      onMouseEnter={() => setIsExpanded(true)}
      onMouseLeave={() => setIsExpanded(false)}
    >
      {/* Logo */}
      <div className="p-4 border-b border-white/[0.08]">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-cyan-400/15 border border-cyan-400/40 flex items-center justify-center"
               style={{ boxShadow: '0 0 20px rgba(0, 229, 255, 0.3), inset 0 0 15px rgba(0, 229, 255, 0.1)' }}>
            <Activity className="w-5 h-5 text-cyan-400 drop-shadow-[0_0_8px_rgba(0,229,255,0.8)]" />
          </div>
          <AnimatePresence>
            {isExpanded && (
              <motion.span
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="font-bold text-lg text-white whitespace-nowrap"
              >
                Trade<span className="text-cyan-400 drop-shadow-[0_0_10px_rgba(0,229,255,0.5)]">Command</span>
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-2">
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              data-testid={`nav-${item.id}`}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 mb-1 rounded-xl transition-all duration-200 ${
                isActive
                  ? 'text-cyan-400 border border-cyan-400/40'
                  : item.highlight 
                    ? 'text-cyan-400/70 hover:text-cyan-400 hover:bg-cyan-400/5 border border-transparent' 
                    : 'text-zinc-500 hover:text-white hover:bg-white/5 border border-transparent'
              }`}
              style={isActive ? {
                background: 'rgba(0, 229, 255, 0.12)',
                boxShadow: '0 0 25px rgba(0, 229, 255, 0.2), inset 0 0 20px rgba(0, 229, 255, 0.08)'
              } : {}}
            >
              <item.icon className={`w-5 h-5 flex-shrink-0 ${isActive ? 'drop-shadow-[0_0_10px_rgba(0,229,255,0.8)]' : ''}`} />
              <AnimatePresence>
                {isExpanded && (
                  <motion.span
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="whitespace-nowrap flex items-center gap-2 text-sm font-medium"
                  >
                    {item.label}
                  </motion.span>
                )}
              </AnimatePresence>
              {isActive && isExpanded && (
                <ChevronRight className="w-4 h-4 ml-auto" />
              )}
            </button>
          );
        })}
      </nav>
      
      {/* Footer */}
      <div className="p-4 border-t border-white/[0.08]">
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-center"
            >
              <p className="text-[10px] text-zinc-600 font-mono">
                v2.0 • <span className="text-cyan-400/60 drop-shadow-[0_0_5px_rgba(0,229,255,0.3)]">Glass Neon</span>
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.aside>
  );
};

export default Sidebar;
