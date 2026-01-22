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
  Calendar
} from 'lucide-react';

const navItems = [
  { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { id: 'chart', icon: LineChart, label: 'Charts' },
  { id: 'scanner', icon: Search, label: 'Scanner' },
  { id: 'strategies', icon: BookOpen, label: 'Strategies' },
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
        {navItems.map((item) => (
          <button
            key={item.id}
            data-testid={`nav-${item.id}`}
            onClick={() => setActiveTab(item.id)}
            className={`w-full flex items-center gap-3 px-4 py-3 transition-all ${
              activeTab === item.id
                ? 'bg-primary/10 text-primary border-r-2 border-primary'
                : 'text-zinc-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <item.icon className="w-5 h-5 flex-shrink-0" />
            <AnimatePresence>
              {isExpanded && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="whitespace-nowrap"
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
    </motion.aside>
  );
};

export default Sidebar;
