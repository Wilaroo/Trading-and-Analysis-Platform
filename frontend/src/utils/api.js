import axios from 'axios';
import { requestThrottler } from './requestThrottler';

// Use relative URL for API calls - proxy handles routing
const API_URL = '';

export const api = axios.create({
  baseURL: API_URL,
  timeout: 30000  // 30 seconds default timeout
});

// Long-running requests get 10min timeout
export const apiLongRunning = axios.create({
  baseURL: API_URL,
  timeout: 600000
});

// ---- Polling abort controller ----
// All throttled GETs use this signal so we can abort them before user actions.
let _pollingController = new AbortController();

function getPollingSignal() {
  return _pollingController.signal;
}

// Abort all in-flight polling GETs and reset the controller
function abortPolling() {
  _pollingController.abort();
  _pollingController = new AbortController();
}

// ---- Throttled GET (background polling only) ----
const originalGet = api.get.bind(api);

api.get = (url, config) => requestThrottler.throttle(() =>
  originalGet(url, { ...config, signal: getPollingSignal() })
    .catch(err => {
      // Silently swallow AbortError from our intentional abort
      if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') {
        return { data: null };
      }
      throw err;
    })
);

// POST/PUT/DELETE are NOT throttled — user-initiated, must go through immediately

// ---- Direct XHR POST for critical user actions ----
// Posts directly to the backend (port 8001) to bypass the React dev proxy
// and avoid competing with polling GETs for browser connection slots.
// In production (same origin), posts to the normal URL.
export const xhrPost = (url, body, timeout = 30000) => {
  // Determine the target URL:
  // - Dev (localhost:3000 proxying to :8001): POST directly to :8001
  // - Production / preview: POST to same origin
  let fullUrl;
  const loc = window.location;
  if (loc.hostname === 'localhost' && loc.port === '3000') {
    fullUrl = `http://localhost:8001${url}`;
  } else {
    fullUrl = `${loc.origin}${url}`;
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.timeout = timeout;
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        resolve({ data, status: xhr.status });
      } catch {
        resolve({ data: {}, status: xhr.status });
      }
    };
    xhr.ontimeout = () => reject(new Error('Request timed out'));
    xhr.onerror = () => reject(new Error('Network error'));
    xhr.open('POST', fullUrl);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.send(JSON.stringify(body));
  });
};

// ---- Safe wrappers (catch errors, return null) ----

export const safeGet = async (url, config) => {
  try {
    const res = await api.get(url, config);
    return res;
  } catch {
    return { data: null };
  }
};

export const safePost = async (url, data, config) => {
  try {
    const res = await api.post(url, data, config);
    return res;
  } catch {
    return { data: null };
  }
};

export const safeDelete = async (url, config) => {
  try {
    const res = await api.delete(url, config);
    return res;
  } catch {
    return { data: null };
  }
};

// ---- Helpers ----

// Cache helper with TTL
const _cache = {};
export const getCached = (key) => {
  const entry = _cache[key];
  if (!entry) return null;
  if (Date.now() - entry.ts > entry.ttl) {
    delete _cache[key];
    return null;
  }
  return entry;
};

export const setCache = (key, data, ttl = 10000) => {
  _cache[key] = { data, ts: Date.now(), ttl };
};

export const getApiHealth = async () => {
  try {
    const response = await api.get('/api/health');
    return response?.data || {};
  } catch {
    return {};
  }
};

// ---- WebSocket URL helper ----
export const getWebSocketUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}`;
};

export default api;
