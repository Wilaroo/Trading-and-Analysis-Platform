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
      className="fixed left-0 top-0 h-full bg-paper border-r border-white/5 z-40 flex flex-col"
      initial={{ width: 64 }}
      animate={{ width: isExpanded ? 220 : 64 }}
      onMouseEnter={() => setIsExpanded(true)}
      onMouseLeave={() => setIsExpanded(false)}
    >
      <div className="p-4 border-b border-white/5">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-accent flex items-center justify-center">
            <Activity className="w-5 h-5 text-white" />
          </div>
          <AnimatePresence>
            {isExpanded && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="font-bold text-lg text-gradient whitespace-nowrap"
              >
                TradeCommand
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      </div>

      <nav className="flex-1 py-4">
        {navItems.map((item) => (
          <button
            key={item.id}
            data-testid={`nav-${item.id}`}
            onClick={() => setActiveTab(item.id)}
            className={`w-full flex items-center gap-3 px-4 py-3 transition-all ${
              activeTab === item.id
                ? 'bg-primary/10 text-primary border-r-2 border-primary'
                : item.highlight 
                  ? 'text-cyan-400 hover:text-cyan-300 hover:bg-cyan-500/10' 
                  : 'text-zinc-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <item.icon className={`w-5 h-5 flex-shrink-0 ${item.highlight && activeTab !== item.id ? 'text-cyan-400' : ''}`} />
            <AnimatePresence>
              {isExpanded && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="whitespace-nowrap flex items-center gap-2"
                >
                  {item.label}
                </motion.span>
              )}
            </AnimatePresence>
            {activeTab === item.id && isExpanded && (
              <ChevronRight className="w-4 h-4 ml-auto" />
            )}
          </button>
        ))}
      </nav>
      
      {/* Minimalist footer */}
      <div className="p-4 border-t border-white/5">
        <AnimatePresence>
          {isExpanded && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-[10px] text-zinc-600 text-center"
            >
              v2.0 • Command Center
            </motion.p>
          )}
        </AnimatePresence>
      </div>
    </motion.aside>
  );
};

export default Sidebar;
