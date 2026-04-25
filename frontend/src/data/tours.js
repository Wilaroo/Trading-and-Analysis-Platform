/**
 * Tours — guided step-by-step walkthroughs of the app.
 *
 * Each tour is just an array of steps. A step is:
 *   {
 *     selector: '[data-testid="..."]',  // CSS selector for the element to spotlight
 *     title:    'Pipeline HUD',          // short title shown in the popover
 *     body:     'Long-form explanation', // 1-3 sentences
 *     position: 'bottom' | 'top' | 'left' | 'right',  // popover side
 *   }
 *
 * Tours are surfaced by:
 *   - The `>tour` command in ⌘K (palette enumerates these by id)
 *   - Direct call: window.dispatchEvent(new CustomEvent('sentcom:start-tour', {detail: {id: 'command-center'}}))
 *
 * Once a tour is completed, its id is added to localStorage under
 * `sentcom.tours.seen` so we don't re-prompt automatically.
 *
 * Keep step bodies short — the popover is small. For deep-dives, link
 * the matching glossary term via `helpId` and let the user click into
 * the drawer.
 */

export const tours = {
  'command-center': {
    id: 'command-center',
    name: 'Command Center fundamentals',
    description: 'A 6-step walkthrough of the V5 trading dashboard.',
    steps: [
      {
        selector: '[data-testid="data-freshness-badge"]',
        title: 'Data Freshness Badge',
        body: 'Top-right of the screen. Always visible across every tab. One glance tells you whether the app is showing live data or a cached snapshot. Click it to open the Freshness Inspector.',
        helpId: 'data-freshness-badge',
        position: 'bottom',
      },
      {
        selector: '[data-testid="cmdk-hint"]',
        title: '⌘K Palette',
        body: 'Power-user search. Hit ⌘K (or Ctrl+K) anywhere to jump to a symbol. Type ?term to look up any badge\'s meaning without leaving the page.',
        helpId: 'cmd-k',
        position: 'bottom',
      },
      {
        selector: '[data-testid="health-chip"]',
        title: 'System Health Chip',
        body: 'Aggregates 7 backend subsystems (mongo, IB pipeline, queues, caches…) into one verdict. Click for the per-subsystem breakdown.',
        helpId: 'health-chip',
        position: 'bottom',
      },
      {
        selector: '[data-testid="top-movers-tile"]',
        title: 'Top Movers Strip',
        body: 'Watchlist movers ranked by absolute % change, refreshed every 30s. Click any chip to open that symbol in the Enhanced Ticker Modal.',
        helpId: 'top-movers-tile',
        position: 'bottom',
      },
      {
        selector: '[data-testid="sentcom-v5-grid"]',
        title: 'Three-Column Layout',
        body: 'Scanner on the left, Chart in the center, Briefings + Open Positions + Stream on the right. Each panel is wrapped in an error boundary, so a crash in one cannot bring down the others.',
        position: 'top',
      },
      {
        selector: '[data-testid="floating-help-btn"]',
        title: 'Glossary Drawer',
        body: 'Click here, or press the ? key, anytime you forget what something means. The press-? overlay highlights every helpable element on the page.',
        helpId: 'glossary-drawer',
        position: 'left',
      },
    ],
  },
  'training-workflow': {
    id: 'training-workflow',
    name: 'Backfill → Train workflow',
    description: 'How to safely launch a training run after the backfill drains.',
    steps: [
      {
        selector: '[data-testid="data-freshness-badge"]',
        title: 'Step 1 — Open the Freshness Inspector',
        body: 'Click the freshness badge in the top-right. The Backfill Readiness Card sits at the very top of the modal.',
        helpId: 'freshness-inspector',
        position: 'bottom',
      },
      {
        selector: '[data-testid="floating-help-btn"]',
        title: 'Step 2 — Verify GREEN verdict',
        body: 'The Backfill Readiness Card runs 5 checks (queue drained, critical symbols fresh, overall freshness, no duplicates, density adequate). All must be green for a clean retrain.',
        helpId: 'backfill-readiness',
        position: 'left',
      },
      {
        selector: '[data-testid="train-all-setups-btn"]',
        title: 'Step 3 — Click Train',
        body: 'Once GREEN, the Train buttons unlock. If you must train despite warnings/blockers, hold Shift while clicking to consciously override the gate.',
        helpId: 'pre-train-interlock',
        position: 'top',
      },
    ],
  },
};

const SEEN_KEY = 'sentcom.tours.seen';

export function loadSeenTours() {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

export function markTourSeen(id) {
  try {
    const seen = loadSeenTours();
    seen.add(id);
    localStorage.setItem(SEEN_KEY, JSON.stringify(Array.from(seen)));
  } catch {
    /* ignore */
  }
}

export function startTour(id) {
  window.dispatchEvent(
    new CustomEvent('sentcom:start-tour', { detail: { id } })
  );
}

export default tours;
