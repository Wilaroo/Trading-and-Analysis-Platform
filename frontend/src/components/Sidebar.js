import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  Search,
  BookOpen,
  Bell,
  Briefcase,
  Newspaper,
  Activity,
  Eye,
  Users,
  PieChart,
  LineChart,
  ChevronRight,
  Calendar,
  BarChart3,
  ClipboardList,
  ScrollText,
  Zap,
  Target
} from 'lucide-react';

const navItems = [
  { id: 'opportunities', icon: Target, label: 'Trade Opportunities', highlight: true, isNew: true },
  { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { id: 'trade-journal', icon: ClipboardList, label: 'Trade Journal' },
  { id: 'chart', icon: LineChart, label: 'Charts' },
  { id: 'ib-trading', icon: Zap, label: 'IB Trading' },
  // Legacy pages (can be accessed but not primary)
  { id: 'divider1', divider: true, label: 'Legacy' },
  { id: 'market-context', icon: BarChart3, label: 'Market Context' },
  { id: 'scanner', icon: Search, label: 'Scanner' },
  { id: 'strategies', icon: BookOpen, label: 'Strategies' },
  { id: 'trading-rules', icon: ScrollText, label: 'Trading Rules' },
  { id: 'earnings', icon: Calendar, label: 'Earnings' },
  { id: 'watchlist', icon: Eye, label: 'Watchlist' },
  { id: 'portfolio', icon: Briefcase, label: 'Portfolio' },
  { id: 'fundamentals', icon: PieChart, label: 'Fundamentals' },
  { id: 'insider', icon: Users, label: 'Insider' },
  { id: 'cot', icon: Activity, label: 'COT Data' },
  { id: 'alerts', icon: Bell, label: 'Alerts' },
  { id: 'newsletter', icon: Newspaper, label: 'Newsletter' },
];

export const Sidebar = ({ activeTab, setActiveTab }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <motion.aside
      className="fixed left-0 top-0 h-full bg-paper border-r border-white/5 z-40 flex flex-col"
      initial={{ width: 64 }}
      animate={{ width: isExpanded ? 256 : 64 }}
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

      <nav className="flex-1 py-4 overflow-y-auto">
        {navItems.map((item) => {
          // Render divider
          if (item.divider) {
            return (
              <div key={item.id} className="px-4 py-2 mt-2">
                <AnimatePresence>
                  {isExpanded && (
                    <motion.span
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="text-[10px] uppercase tracking-wider text-zinc-600"
                    >
                      {item.label}
                    </motion.span>
                  )}
                </AnimatePresence>
                {!isExpanded && <div className="h-px bg-zinc-800 mt-1" />}
              </div>
            );
          }
          
          return (
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
                    {item.isNew && activeTab !== item.id && (
                      <span className="px-1.5 py-0.5 text-[10px] bg-cyan-500/20 text-cyan-400 rounded font-medium">NEW</span>
                    )}
                  </motion.span>
                )}
              </AnimatePresence>
              {activeTab === item.id && isExpanded && (
                <ChevronRight className="w-4 h-4 ml-auto" />
              )}
            </button>
          );
        })}
      </nav>
    </motion.aside>
  );
};

export default Sidebar;
