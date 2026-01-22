import axios from 'axios';

// Use relative URL for API calls - proxy handles routing
const API_URL = '';

export const api = axios.create({
  baseURL: API_URL,
  timeout: 30000
});

// WebSocket URL - detect protocol and construct WS URL
export const getWebSocketUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  // For development with proxy, connect to backend directly
  if (host.includes('localhost:3000')) {
    return 'ws://localhost:8001/ws/quotes';
  }
  return `${protocol}//${host}/ws/quotes`;
};

export default api;
