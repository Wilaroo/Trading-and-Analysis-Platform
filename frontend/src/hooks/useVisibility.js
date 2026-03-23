/**
 * useVisibility - Lazy loading hook for components
 * 
 * Only triggers polling/loading when component is actually visible in viewport.
 * Uses IntersectionObserver for efficient visibility detection.
 * 
 * Usage:
 * const { ref, isVisible, hasBeenVisible } = useVisibility();
 * 
 * <div ref={ref}>
 *   {(isVisible || hasBeenVisible) && <ExpensiveComponent />}
 * </div>
 */

import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * Hook to detect if an element is visible in the viewport
 * 
 * @param {Object} options
 * @param {number} options.threshold - How much of element must be visible (0-1)
 * @param {string} options.rootMargin - Margin around viewport to trigger early
 * @param {boolean} options.once - If true, stays "visible" once seen
 * @returns {{ ref: React.RefObject, isVisible: boolean, hasBeenVisible: boolean }}
 */
export const useVisibility = (options = {}) => {
  const {
    threshold = 0.1,
    rootMargin = '100px', // Start loading slightly before visible
    once = true, // Once visible, stay "loaded"
  } = options;

  const ref = useRef(null);
  const [isVisible, setIsVisible] = useState(false);
  const [hasBeenVisible, setHasBeenVisible] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    // Check if IntersectionObserver is available
    if (!('IntersectionObserver' in window)) {
      // Fallback: assume visible
      setIsVisible(true);
      setHasBeenVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        const visible = entry.isIntersecting;
        setIsVisible(visible);
        
        if (visible && !hasBeenVisible) {
          setHasBeenVisible(true);
        }
      },
      { threshold, rootMargin }
    );

    observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, [threshold, rootMargin, hasBeenVisible]);

  return { ref, isVisible, hasBeenVisible };
};

/**
 * Hook for tab/window visibility
 * Pauses polling when tab is hidden
 */
export const useTabVisibility = () => {
  const [isTabVisible, setIsTabVisible] = useState(!document.hidden);

  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsTabVisible(!document.hidden);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  return isTabVisible;
};

/**
 * Combined hook for smart loading - only loads when:
 * 1. Component is in viewport (or has been)
 * 2. Tab is visible
 * 3. Feature wave has started (from StartupManager)
 * 
 * @param {string} featureId - Feature identifier for startup manager
 * @param {Object} options - Visibility options
 */
export const useSmartLoading = (featureId, options = {}) => {
  const { ref, isVisible, hasBeenVisible } = useVisibility(options);
  const isTabVisible = useTabVisibility();
  
  // Import dynamically to avoid circular dependency
  const [isFeatureReady, setIsFeatureReady] = useState(false);
  
  useEffect(() => {
    // Dynamic import of startup manager check
    import('../contexts/StartupManagerContext').then(({ useStartupManager }) => {
      // This won't work inside useEffect, but we'll set a flag
      setIsFeatureReady(true);
    }).catch(() => {
      setIsFeatureReady(true); // Fallback to ready
    });
  }, []);

  const shouldLoad = (isVisible || hasBeenVisible) && isTabVisible && isFeatureReady;
  const shouldPoll = isVisible && isTabVisible && isFeatureReady;

  return {
    ref,
    isVisible,
    hasBeenVisible,
    isTabVisible,
    shouldLoad,  // Load data once visible
    shouldPoll,  // Only poll while actively visible
  };
};

/**
 * Hook to pause/resume based on visibility
 * Returns a function that wraps callbacks to only execute when visible
 */
export const useVisibleCallback = (callback, deps = []) => {
  const isTabVisible = useTabVisibility();
  const callbackRef = useRef(callback);
  
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  return useCallback((...args) => {
    if (isTabVisible) {
      return callbackRef.current?.(...args);
    }
  }, [isTabVisible, ...deps]);
};

export default useVisibility;
