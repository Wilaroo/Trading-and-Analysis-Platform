/**
 * TickerModalContext - Global context for managing the enhanced ticker modal
 * 
 * Allows any component to open the chart modal by calling openTickerModal(symbol)
 * Handles fetching bot position data automatically
 */
import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import EnhancedTickerModal from '../components/EnhancedTickerModal';
import api, { safeGet, safePost } from '../utils/api';

const TickerModalContext = createContext(null);

export const useTickerModal = () => {
  const context = useContext(TickerModalContext);
  if (!context) {
    throw new Error('useTickerModal must be used within a TickerModalProvider');
  }
  return context;
};

export const TickerModalProvider = ({ children, onTrade, onAskAI }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [currentTicker, setCurrentTicker] = useState(null);
  const [botTrades, setBotTrades] = useState([]);
  
  // Fetch bot's open trades to check if we have a position
  const fetchBotTrades = useCallback(async () => {
    try {
      const data = await safeGet('/api/trading-bot/trades/open');
      setBotTrades(data?.trades || []);
    } catch (err) {
      console.error('Failed to fetch bot trades:', err);
    }
  }, []);
  
  // Refresh bot trades periodically
  useEffect(() => {
    fetchBotTrades();
    const interval = setInterval(fetchBotTrades, 10000); // Every 10 seconds
    return () => clearInterval(interval);
  }, [fetchBotTrades]);
  
  // Open modal with a ticker
  const openTickerModal = useCallback((symbolOrTicker) => {
    const ticker = typeof symbolOrTicker === 'string' 
      ? { symbol: symbolOrTicker.toUpperCase() }
      : symbolOrTicker;
    
    setCurrentTicker(ticker);
    setIsOpen(true);
    fetchBotTrades(); // Refresh bot trades when opening
  }, [fetchBotTrades]);
  
  // Close modal
  const closeTickerModal = useCallback(() => {
    setIsOpen(false);
    setCurrentTicker(null);
  }, []);
  
  // Find bot position for current ticker
  const getBotPositionForTicker = useCallback((symbol) => {
    return botTrades.find(t => 
      t.symbol?.toUpperCase() === symbol?.toUpperCase() && 
      t.status === 'open'
    );
  }, [botTrades]);
  
  const value = {
    isOpen,
    currentTicker,
    openTickerModal,
    closeTickerModal,
    botTrades,
    getBotPositionForTicker,
  };
  
  return (
    <TickerModalContext.Provider value={value}>
      {children}
      
      {/* Render the modal */}
      {isOpen && currentTicker && (
        <EnhancedTickerModal
          ticker={currentTicker}
          onClose={closeTickerModal}
          onTrade={onTrade}
          onAskAI={onAskAI}
          botTrade={getBotPositionForTicker(currentTicker.symbol)}
        />
      )}
    </TickerModalContext.Provider>
  );
};

export default TickerModalContext;
