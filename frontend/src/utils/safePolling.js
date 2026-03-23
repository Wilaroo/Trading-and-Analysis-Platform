/**
 * safePolling - Startup-safe polling utility
 * 
 * Replaces raw setInterval with:
 * 1. Random stagger on first call (prevents thundering herd)
 * 2. Tab visibility awareness (skips polls when tab is hidden)
 * 3. Proper cleanup
 * 
 * Usage:
 *   useEffect(() => {
 *     const cleanup = safePolling(fetchData, 30000, { immediate: true, stagger: 3000 });
 *     return cleanup;
 *   }, [fetchData]);
 */

let globalStaggerCounter = 0;

/**
 * Creates a visibility-aware, staggered polling timer
 * 
 * @param {Function} callback - The function to call on each tick
 * @param {number} interval - Polling interval in ms
 * @param {Object} options
 * @param {boolean} options.immediate - Call immediately (after stagger delay)
 * @param {number} options.stagger - Max random stagger delay in ms (default 3000)
 * @param {boolean} options.visibilityAware - Skip polls when tab is hidden (default true)
 * @param {boolean} options.essential - If true, reduces stagger and continues when hidden
 * @returns {Function} cleanup function
 */
export function safePolling(callback, interval, options = {}) {
  const {
    immediate = true,
    stagger = 3000,
    visibilityAware = true,
    essential = false,
  } = options;

  let timerId = null;
  let staggerTimerId = null;
  let cleaned = false;

  // Deterministic stagger based on order of creation + random jitter
  // Spreads out initial requests to avoid thundering herd
  globalStaggerCounter++;
  const baseDelay = (globalStaggerCounter % 8) * 200; // 0-1400ms spread
  const jitter = Math.random() * Math.min(stagger, 500); // 0-500ms random
  const totalStagger = essential ? Math.min(baseDelay, 300) : baseDelay + jitter;

  const wrappedCallback = () => {
    if (cleaned) return;
    // Skip if tab is hidden (unless essential)
    if (visibilityAware && !essential && document.visibilityState === 'hidden') {
      return;
    }
    callback();
  };

  // Stagger the initial call and timer start
  staggerTimerId = setTimeout(() => {
    if (cleaned) return;

    // Immediate first call (after stagger)
    if (immediate) {
      wrappedCallback();
    }

    // Start the interval
    timerId = setInterval(wrappedCallback, interval);
  }, totalStagger);

  // Return cleanup function
  return () => {
    cleaned = true;
    if (staggerTimerId) clearTimeout(staggerTimerId);
    if (timerId) clearInterval(timerId);
  };
}

/**
 * Reset the stagger counter (call when app reinitializes)
 */
export function resetStaggerCounter() {
  globalStaggerCounter = 0;
}

export default safePolling;
