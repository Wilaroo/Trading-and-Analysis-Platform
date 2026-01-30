import { useEffect, useCallback } from 'react';

/**
 * Custom hook for handling keyboard shortcuts
 * @param {Object} shortcuts - Object mapping key combinations to callbacks
 * @param {boolean} enabled - Whether shortcuts are active
 * 
 * Key format examples:
 * - 'ctrl+k' - Ctrl+K (Cmd+K on Mac)
 * - 'ctrl+shift+a' - Ctrl+Shift+A
 * - 'escape' - Escape key
 * - 'enter' - Enter key
 */
export const useKeyboardShortcuts = (shortcuts, enabled = true) => {
  const handleKeyDown = useCallback((event) => {
    if (!enabled) return;
    
    // Don't trigger shortcuts when typing in inputs
    const target = event.target;
    const isInput = target.tagName === 'INPUT' || 
                   target.tagName === 'TEXTAREA' || 
                   target.isContentEditable;
    
    // Build the key combination string
    const keys = [];
    if (event.ctrlKey || event.metaKey) keys.push('ctrl');
    if (event.shiftKey) keys.push('shift');
    if (event.altKey) keys.push('alt');
    
    const key = event.key.toLowerCase();
    if (!['control', 'shift', 'alt', 'meta'].includes(key)) {
      keys.push(key);
    }
    
    const combo = keys.join('+');
    
    // Check if this combo matches any shortcut
    if (shortcuts[combo]) {
      // Allow Escape to work even in inputs
      if (combo === 'escape' || !isInput) {
        event.preventDefault();
        shortcuts[combo](event);
      }
    }
  }, [shortcuts, enabled]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
};

/**
 * Predefined keyboard shortcuts for trading app
 */
export const TRADING_SHORTCUTS = {
  FOCUS_SEARCH: 'ctrl+k',
  OPEN_AI_ASSISTANT: 'ctrl+shift+a',
  CLOSE_MODAL: 'escape',
  QUICK_REFRESH: 'ctrl+r',
  TOGGLE_SOUND: 'ctrl+m',
};

export default useKeyboardShortcuts;
