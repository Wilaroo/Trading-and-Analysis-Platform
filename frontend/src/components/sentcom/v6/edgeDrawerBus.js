/** edgeDrawerBus — open the shared Edge drawer from any ring anywhere in the cockpit.
 *  Mirrors the v5 tqsDrawerBus pattern (a single mounted host listens). */
const EVT = 'sentcom:edge-drawer';

export function openEdgeDrawer(item) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(EVT, { detail: item || null }));
}

export function onEdgeDrawer(handler) {
  if (typeof window === 'undefined') return () => {};
  const fn = (e) => handler(e.detail);
  window.addEventListener(EVT, fn);
  return () => window.removeEventListener(EVT, fn);
}
