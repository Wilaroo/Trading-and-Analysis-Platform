/**
 * edgeTripleStore — singleton source of the latest Entry-Edge TRIPLE per symbol.
 *
 * One shared poller (not one fetch per ring) feeds every EdgeRingForSymbol across the
 * live cockpit. Reads GET /api/slow-learning/entry-edge/recent and keeps the LATEST
 * triple per symbol (endpoint is created_at-desc, so first occurrence wins). Ref-counted
 * polling: starts on first subscriber, stops on last. Fail-soft (keeps last good map).
 */
const API = process.env.REACT_APP_BACKEND_URL || '';
const POLL_MS = 30000;

let _bySymbol = {};
const _subs = new Set();
let _timer = null;
let _refs = 0;
let _inflight = false;

async function _fetch() {
  if (_inflight) return;
  _inflight = true;
  try {
    const res = await fetch(`${API}/api/slow-learning/entry-edge/recent?limit=150`);
    const data = await res.json();
    const map = {};
    (data.items || []).forEach((it) => {
      const sym = (it.symbol || '').toUpperCase();
      if (!sym || map[sym]) return;       // first occurrence = latest
      map[sym] = { ...it, symbol: sym };
    });
    _bySymbol = map;
    _subs.forEach((fn) => { try { fn(); } catch (e) { /* noop */ } });
  } catch (e) {
    /* fail-soft: retain last good map */
  } finally {
    _inflight = false;
  }
}

export function getItem(symbol) {
  if (!symbol) return null;
  return _bySymbol[String(symbol).toUpperCase()] || null;
}

export function getTriple(symbol) {
  const it = getItem(symbol);
  return it ? it.triple : null;
}

export function subscribe(fn) {
  _subs.add(fn);
  _refs += 1;
  if (_refs === 1) {
    _fetch();
    _timer = setInterval(_fetch, POLL_MS);
  }
  return () => {
    _subs.delete(fn);
    _refs -= 1;
    if (_refs <= 0 && _timer) {
      clearInterval(_timer);
      _timer = null;
      _refs = 0;
    }
  };
}

export function refreshNow() {
  _fetch();
}
