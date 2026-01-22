import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

// Suppress third-party script errors in development overlay
if (process.env.NODE_ENV === 'development') {
  window.addEventListener('error', (event) => {
    if (event.message === 'Script error.' || 
        event.filename?.includes('tradingview') ||
        event.filename?.includes('widget') ||
        event.message?.includes('Script error')) {
      event.stopImmediatePropagation();
      event.preventDefault();
      return true;
    }
  }, true);
  
  window.addEventListener('unhandledrejection', (event) => {
    if (event.reason?.message?.includes('Script error') ||
        event.reason?.stack?.includes('tradingview')) {
      event.stopImmediatePropagation();
      event.preventDefault();
      return true;
    }
  }, true);
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
