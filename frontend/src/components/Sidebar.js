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
        background: 'rgba(255, 255, 255, 0.85)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        borderRight: '1px solid rgba(0, 0, 0, 0.08)',
        boxShadow: '4px 0 30px rgba(0, 0, 0, 0.06)'
      }}
      initial={{ width: 64 }}
      animate={{ width: isExpanded ? 220 : 64 }}
      onMouseEnter={() => setIsExpanded(true)}
      onMouseLeave={() => setIsExpanded(false)}
    >
      {/* Animated gradient border */}
      <div className="absolute inset-y-0 right-0 w-[2px] overflow-hidden">
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
      <div className="p-4 border-b border-black/[0.06]">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center"
               style={{ 
                 background: 'linear-gradient(135deg, var(--primary-main), var(--accent-main))',
                 boxShadow: '0 4px 15px var(--primary-glow)'
               }}>
            <Activity className="w-5 h-5 text-white" />
          </div>
          <AnimatePresence>
            {isExpanded && (
              <motion.span
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="font-bold text-lg whitespace-nowrap"
                style={{ color: 'var(--text-primary)' }}
              >
                Trade<span style={{ color: 'var(--primary-dark)' }}>Command</span>
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
                  ? 'border'
                  : item.highlight 
                    ? 'hover:bg-cyan-50 border border-transparent' 
                    : 'hover:bg-gray-50 border border-transparent'
              }`}
              style={isActive ? {
                background: 'linear-gradient(135deg, rgba(0, 184, 217, 0.12), rgba(124, 77, 255, 0.08))',
                borderColor: 'var(--primary-main)',
                color: 'var(--primary-dark)',
                boxShadow: '0 4px 15px var(--primary-glow)'
              } : {
                color: item.highlight ? 'var(--primary-dark)' : 'var(--text-secondary)'
              }}
            >
              <item.icon className={`w-5 h-5 flex-shrink-0`} />
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
      <div className="p-4 border-t border-black/[0.06]">
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-center"
            >
              <p className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                v2.0 • <span style={{ color: 'var(--primary-dark)' }}>Light Glass</span>
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.aside>
  );
};

export default Sidebar;
