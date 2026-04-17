/**
 * ClickableTicker - A ticker symbol that opens the chart modal when clicked
 * 
 * Usage:
 *   <ClickableTicker symbol="AAPL" />
 *   <ClickableTicker symbol="NVDA" showPrice price={122.50} change={1.5} />
 */
import React from 'react';
import { useTickerModal } from '../../hooks/useTickerModal';

const ClickableTicker = ({ 
  symbol, 
  showPrice = false,
  price = null,
  change = null,
  className = '',
  variant = 'default', // 'default' | 'chip' | 'badge' | 'inline'
  children
}) => {
  const { openTickerModal } = useTickerModal();
  
  const handleClick = (e) => {
    e.stopPropagation();
    openTickerModal(symbol);
  };
  
  const baseStyles = "cursor-pointer transition-all duration-150";
  
  const variants = {
    default: `${baseStyles} hover:text-cyan-400`,
    chip: `${baseStyles} px-2 py-1 rounded-md bg-cyan-400/10 text-cyan-400 text-xs font-mono hover:bg-cyan-400/20 border border-cyan-400/30`,
    badge: `${baseStyles} px-1.5 py-0.5 rounded bg-cyan-400/20 text-cyan-400 text-xs font-mono hover:bg-cyan-400/30`,
    inline: `${baseStyles} text-cyan-400 hover:text-cyan-300 hover:underline font-mono`,
  };
  
  if (children) {
    return (
      <span onClick={handleClick} className={`${variants[variant]} ${className}`}>
        {children}
      </span>
    );
  }
  
  if (showPrice && price !== null) {
    const isPositive = change >= 0;
    return (
      <span 
        onClick={handleClick} 
        className={`${variants[variant]} ${className} inline-flex items-center gap-2`}
      >
        <span className="font-bold">{symbol}</span>
        <span className="font-mono">${price.toFixed(2)}</span>
        {change !== null && (
          <span className={isPositive ? 'text-emerald-400' : 'text-red-400'}>
            {isPositive ? '+' : ''}{change.toFixed(2)}%
          </span>
        )}
      </span>
    );
  }
  
  return (
    <span 
      onClick={handleClick} 
      className={`${variants[variant]} ${className}`}
    >
      {symbol}
    </span>
  );
};

export default ClickableTicker;
