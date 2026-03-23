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

// Create throttled versions of api methods
const originalGet = api.get.bind(api);
const originalPost = api.post.bind(api);
const originalPut = api.put.bind(api);
const originalDelete = api.delete.bind(api);

api.get = (url, config) => requestThrottler.throttle(() => originalGet(url, config));
api.post = (url, data, config) => requestThrottler.throttle(() => originalPost(url, data, config));
api.put = (url, data, config) => requestThrottler.throttle(() => originalPut(url, data, config));
api.delete = (url, config) => requestThrottler.throttle(() => originalDelete(url, config));

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

export default api;
