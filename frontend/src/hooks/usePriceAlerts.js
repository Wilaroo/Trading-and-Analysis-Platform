import { useState, useEffect, useCallback, useRef } from 'react';
import { createAlertSound } from '../utils/alertSounds';

// v322o — minimum gap between two alerts for the SAME symbol. The old
// dedup key was per-minute, so a symbol sitting past the threshold
// re-toasted every 60s all session (the "2% move spam" complaint).
const ALERT_COOLDOWN_MS = 15 * 60 * 1000;

// ===================== PRICE ALERTS HOOK =====================
export const usePriceAlerts = (streamingQuotes, watchlist = []) => {
  const [alerts, setAlerts] = useState([]);
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [alertThreshold, setAlertThreshold] = useState(() => {
    // Load from localStorage or default to 2%
    const saved = localStorage.getItem('alertThreshold');
    return saved ? parseFloat(saved) : 2;
  });
  const previousPricesRef = useRef({});
  const alertSoundRef = useRef(null);
  // v322o — per-symbol last-alert timestamps for the 15-min cooldown.
  const lastAlertAtRef = useRef({});
  
  // Save threshold to localStorage when it changes
  useEffect(() => {
    localStorage.setItem('alertThreshold', alertThreshold.toString());
  }, [alertThreshold]);
  
  // Initialize audio on first user interaction
  const initializeAudio = useCallback(() => {
    if (!alertSoundRef.current) {
      alertSoundRef.current = createAlertSound();
    }
  }, []);
  
  // Check for price movements and trigger alerts
  const checkPriceAlerts = useCallback((quotes) => {
    if (!quotes || Object.keys(quotes).length === 0) return;
    
    const newAlerts = [];
    const now = Date.now();
    
    // Get watchlist symbols (or use streaming symbols if no watchlist)
    const symbolsToWatch = watchlist.length > 0 
      ? watchlist.map(w => w.symbol) 
      : Object.keys(quotes);
    
    symbolsToWatch.forEach(symbol => {
      const quote = quotes[symbol];
      if (!quote) return;
      
      const previousPrice = previousPricesRef.current[symbol];
      const currentPrice = quote.price;
      const changePercent = quote.change_percent || 0;
      
      // Check for significant movement (use either price change or % change)
      let alertTriggered = false;
      let alertType = 'info';
      let alertMessage = '';
      
      // Method 1: Check absolute change percent from API
      if (Math.abs(changePercent) >= alertThreshold) {
        alertTriggered = true;
        alertType = changePercent > 0 ? 'bullish' : 'bearish';
        alertMessage = `${symbol} ${changePercent > 0 ? 'up' : 'down'} ${Math.abs(changePercent).toFixed(2)}%`;
      }
      
      // Method 2: Check price change since last update (for real-time spikes)
      if (previousPrice && currentPrice) {
        const priceDelta = ((currentPrice - previousPrice) / previousPrice) * 100;
        if (Math.abs(priceDelta) >= alertThreshold * 0.5) { // Half threshold for real-time
          alertTriggered = true;
          alertType = priceDelta > 0 ? 'bullish' : 'bearish';
          alertMessage = `${symbol} moved ${priceDelta > 0 ? '+' : ''}${priceDelta.toFixed(2)}% in real-time`;
        }
      }
      
      // v322o — throttle: at most ONE alert per symbol per 15 minutes,
      // no matter how long the move persists past the threshold.
      const lastAt = lastAlertAtRef.current[symbol] || 0;
      if (alertTriggered && (now - lastAt) >= ALERT_COOLDOWN_MS) {
        lastAlertAtRef.current[symbol] = now;
        
        const alert = {
          id: `${symbol}-${now}`,
          symbol,
          price: currentPrice,
          changePercent,
          type: alertType,
          message: alertMessage,
          timestamp: new Date().toISOString(),
          read: false
        };
        
        newAlerts.push(alert);
        
        // Play sound
        if (audioEnabled && alertSoundRef.current) {
          if (Math.abs(changePercent) >= alertThreshold * 2) {
            alertSoundRef.current.playUrgent();
          } else if (alertType === 'bullish') {
            alertSoundRef.current.playBullish();
          } else {
            alertSoundRef.current.playBearish();
          }
        }
      }
      
      // Update previous price
      previousPricesRef.current[symbol] = currentPrice;
    });
    
    if (newAlerts.length > 0) {
      setAlerts(prev => [...newAlerts, ...prev].slice(0, 50)); // Keep last 50 alerts
    }
  }, [watchlist, alertThreshold, audioEnabled]);
  
  // Process quotes when they update
  useEffect(() => {
    if (Object.keys(streamingQuotes).length > 0) {
      checkPriceAlerts(streamingQuotes);
    }
  }, [streamingQuotes, checkPriceAlerts]);
  
  const clearAlerts = useCallback(() => {
    setAlerts([]);
  }, []);
  
  const dismissAlert = useCallback((alertId) => {
    setAlerts(prev => prev.filter(a => a.id !== alertId));
  }, []);
  
  return {
    alerts,
    audioEnabled,
    setAudioEnabled,
    alertThreshold,
    setAlertThreshold,
    initializeAudio,
    clearAlerts,
    dismissAlert
  };
};

export default usePriceAlerts;
