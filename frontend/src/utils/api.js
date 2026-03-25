import axios from 'axios';
import { requestThrottler } from './requestThrottler';

// Use relative URL for API calls - proxy handles routing
const API_URL = '';

export const api = axios.create({
  baseURL: API_URL,
  timeout: 30000  // 30 seconds default timeout
});

// Long-running requests get 10min timeout (job polling, training status)
export const apiLongRunning = axios.create({
  baseURL: API_URL,
  timeout: 600000
});

// ---- Throttled GET (background polling) ----
// Browser allows 6 connections per domain. We reserve 2 for WebSockets,
// leaving 4 for HTTP. Throttler ensures polling GETs don't starve user actions.
const originalGet = api.get.bind(api);

api.get = (url, config) => requestThrottler.throttle(() =>
  originalGet(url, config)
);

// POST/PUT/DELETE are NOT throttled — user-initiated, must go through immediately

// ---- Safe wrappers (catch errors, return null) ----
// Used by components for non-critical data fetching that should fail silently.

export const safeGet = async (url, config) => {
  try {
    const res = await api.get(url, config);
    return res.data;
  } catch {
    return null;
  }
};

export const safePost = async (url, data, config) => {
  try {
    const res = await api.post(url, data, config);
    return res.data;
  } catch {
    return null;
  }
};

export const safeDelete = async (url, config) => {
  try {
    const res = await api.delete(url, config);
    return res.data;
  } catch {
    return null;
  }
};

// ---- Helpers ----

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
  const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
  if (backendUrl) {
    return `${backendUrl.replace(/^http/, 'ws')}/api/ws/quotes`;
  }
  // Fallback: derive from current page URL
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/api/ws/quotes`;
};

export default api;
