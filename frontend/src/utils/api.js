import axios from 'axios';
import { requestThrottler } from './requestThrottler';

// Use relative URL for API calls - proxy handles routing
const API_URL = '';

export const api = axios.create({
  baseURL: API_URL,
  timeout: 30000  // 30 seconds default timeout
});

// Add request interceptor to throttle concurrent requests
api.interceptors.request.use(
  async (config) => {
    // Wrap the request in the throttler
    // This doesn't actually throttle here, but we track it
    return config;
  },
  (error) => Promise.reject(error)
);

// Throttle only GET requests (background polling).
// POST/PUT/DELETE are user-initiated actions — never queue them behind polling.
const originalGet = api.get.bind(api);

api.get = (url, config) => requestThrottler.throttle(() => originalGet(url, config));

// Create a separate instance for long-running operations (Market Intelligence, Scans, etc.)
// This one is NOT throttled since these are intentional long requests
export const apiLongRunning = axios.create({
  baseURL: API_URL,
  timeout: 300000  // 5 minutes for comprehensive scans (they can take a while)
});

// Throttled fetch wrapper for components using native fetch
export const throttledFetch = (url, options = {}) => {
  return requestThrottler.throttle(() => fetch(url, options));
};

// WebSocket URL - detect protocol and construct WS URL
export const getWebSocketUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  // For development with proxy, connect to backend directly
  if (host.includes('localhost:3000')) {
    return 'ws://localhost:8001/api/ws/quotes';
  }
  return `${protocol}//${host}/api/ws/quotes`;
};

// Export throttler for monitoring
export { requestThrottler };

// Safe API wrappers - return empty object on error (matches common fetch pattern)
export const safeGet = async (url) => {
  try {
    const { data } = await api.get(url);
    return data;
  } catch (err) {
    if (err?.response?.status === 429) return null; // Rate limited
    return {};
  }
};

export const safePost = async (url, body) => {
  try {
    const { data } = await api.post(url, body);
    return data;
  } catch (err) {
    if (err?.response?.status === 429) return null;
    return {};
  }
};

export const safeDelete = async (url) => {
  try {
    const { data } = await api.delete(url);
    return data;
  } catch (err) {
    return {};
  }
};

// Direct XHR POST — bypasses axios interceptors and connection pool contention.
// Use for critical user-initiated actions (training, job creation) that must not
// be delayed by background polling.
export const xhrPost = (url, body, timeout = 30000) => {
  const fullUrl = `${window.location.origin}${url}`;
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

export default api;
