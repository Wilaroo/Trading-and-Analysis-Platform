import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HelpCircle, ExternalLink } from 'lucide-react';
import { tooltipDefinitions as comprehensiveDefinitions } from './shared/Tooltip';

// Use the comprehensive tooltip definitions from Tooltip.jsx
const tooltipDefinitions = comprehensiveDefinitions;

// HelpTooltip component - wrap any text to add hover tooltip
export const HelpTooltip = ({ 
  termId, 
  children, 
  className = '',
  showIcon = false,
  position = 'top' 
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [tooltipPosition, setTooltipPosition] = useState({ top: 0, left: 0 });
  const triggerRef = useRef(null);
  const tooltipRef = useRef(null);
  
  const definition = tooltipDefinitions[termId];
  
  useEffect(() => {
    if (isVisible && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const tooltipWidth = 280;
      
      let top, left;
      
      switch (position) {
        case 'bottom':
          top = rect.bottom + 8;
          left = rect.left + (rect.width / 2) - (tooltipWidth / 2);
          break;
        case 'left':
          top = rect.top + (rect.height / 2);
          left = rect.left - tooltipWidth - 8;
          break;
        case 'right':
          top = rect.top + (rect.height / 2);
          left = rect.right + 8;
          break;
        default: // top
          top = rect.top - 8;
          left = rect.left + (rect.width / 2) - (tooltipWidth / 2);
      }
      
      // Keep tooltip in viewport
      left = Math.max(10, Math.min(left, window.innerWidth - tooltipWidth - 10));
      
      setTooltipPosition({ top, left });
    }
  }, [isVisible, position]);
  
  if (!definition) {
    return <span className={className}>{children}</span>;
  }
  
  return (
    <>
      <span
        ref={triggerRef}
        className={`inline-flex items-center gap-1 cursor-help border-b border-dotted border-zinc-600 hover:border-cyan-400 transition-colors ${className}`}
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
      >
        {children}
        {showIcon && <HelpCircle className="w-3 h-3 text-zinc-500" />}
      </span>
      
      <AnimatePresence>
        {isVisible && (
          <motion.div
            ref={tooltipRef}
            initial={{ opacity: 0, y: position === 'bottom' ? -5 : 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: position === 'bottom' ? -5 : 5 }}
            transition={{ duration: 0.15 }}
            className="fixed z-[100] w-[280px] p-3 bg-zinc-900 border border-cyan-500/30 rounded-lg shadow-xl"
            style={{ 
              top: tooltipPosition.top,
              left: tooltipPosition.left,
              transform: position === 'top' ? 'translateY(-100%)' : undefined
            }}
          >
            <div className="flex items-start justify-between mb-1">
              <span className="font-semibold text-cyan-400 text-sm">{definition.term}</span>
              <a 
                href={`#glossary-${termId}`}
                className="text-zinc-500 hover:text-cyan-400 transition-colors"
                onClick={(e) => {
                  e.preventDefault();
                  // Could navigate to glossary page with this term selected
                  window.location.href = `/glossary?search=${encodeURIComponent(definition.term)}`;
                }}
              >
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <p className="text-xs text-zinc-300 leading-relaxed">{definition.def}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

// Helper component for quick inline tooltips
export const HelpIcon = ({ termId, size = 'sm' }) => {
  const [isVisible, setIsVisible] = useState(false);
  const triggerRef = useRef(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  
  const definition = tooltipDefinitions[termId];
  
  useEffect(() => {
    if (isVisible && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPosition({
        top: rect.top - 8,
        left: rect.left + rect.width / 2 - 140
      });
    }
  }, [isVisible]);
  
  if (!definition) return null;
  
  const sizeClasses = {
    sm: 'w-3 h-3',
    md: 'w-4 h-4',
    lg: 'w-5 h-5'
  };
  
  return (
    <>
      <span
        ref={triggerRef}
        className="inline-flex cursor-help text-zinc-500 hover:text-cyan-400 transition-colors"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
      >
        <HelpCircle className={sizeClasses[size]} />
      </span>
      
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            className="fixed z-[100] w-[280px] p-3 bg-zinc-900 border border-cyan-500/30 rounded-lg shadow-xl"
            style={{ 
              top: position.top,
              left: Math.max(10, position.left),
              transform: 'translateY(-100%)'
            }}
          >
            <span className="font-semibold text-cyan-400 text-sm block mb-1">{definition.term}</span>
            <p className="text-xs text-zinc-300 leading-relaxed">{definition.def}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

// Export definitions for use elsewhere
export const getTooltipDefinition = (termId) => tooltipDefinitions[termId];
export const hasTooltip = (termId) => !!tooltipDefinitions[termId];

export default HelpTooltip;
