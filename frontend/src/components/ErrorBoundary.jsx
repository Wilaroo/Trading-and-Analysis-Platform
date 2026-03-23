/**
 * ErrorBoundary - Catch and recover from component crashes
 * =========================================================
 * 
 * Prevents a single component crash from taking down the whole app.
 * Shows a friendly error UI with retry option.
 */

import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { 
      hasError: false, 
      error: null,
      errorInfo: null,
      retryCount: 0
    };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    
    // Log error for debugging
    console.error('[ErrorBoundary] Caught error:', error);
    console.error('[ErrorBoundary] Component stack:', errorInfo?.componentStack);
    
    // Could send to error tracking service here
  }

  handleRetry = () => {
    this.setState(prev => ({ 
      hasError: false, 
      error: null, 
      errorInfo: null,
      retryCount: prev.retryCount + 1 
    }));
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback UI if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Compact error for smaller components
      if (this.props.compact) {
        return (
          <div className="flex items-center gap-2 p-2 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-xs">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span className="truncate">{this.props.name || 'Component'} error</span>
            <button 
              onClick={this.handleRetry}
              className="ml-auto p-1 hover:bg-red-500/20 rounded"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
          </div>
        );
      }

      // Full error display
      return (
        <div className="flex flex-col items-center justify-center p-6 bg-zinc-900/50 border border-red-500/30 rounded-lg">
          <AlertTriangle className="w-12 h-12 text-red-500 mb-4" />
          <h3 className="text-lg font-medium text-zinc-100 mb-2">
            {this.props.name || 'Component'} Error
          </h3>
          <p className="text-sm text-zinc-400 mb-4 text-center max-w-md">
            Something went wrong. This section encountered an error but the rest of the app should still work.
          </p>
          
          {this.state.retryCount < 3 && (
            <button
              onClick={this.handleRetry}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Try Again
            </button>
          )}
          
          {this.state.retryCount >= 3 && (
            <p className="text-xs text-zinc-500">
              Multiple retries failed. Try refreshing the page.
            </p>
          )}
          
          {process.env.NODE_ENV === 'development' && this.state.error && (
            <details className="mt-4 text-xs text-zinc-500 max-w-full overflow-auto">
              <summary className="cursor-pointer hover:text-zinc-400">Error details</summary>
              <pre className="mt-2 p-2 bg-zinc-800 rounded text-left overflow-x-auto">
                {this.state.error.toString()}
                {this.state.errorInfo?.componentStack}
              </pre>
            </details>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

/**
 * HOC to wrap a component with error boundary
 */
export const withErrorBoundary = (Component, options = {}) => {
  const { name, compact, fallback } = options;
  
  return function WrappedComponent(props) {
    return (
      <ErrorBoundary name={name || Component.displayName || Component.name} compact={compact} fallback={fallback}>
        <Component {...props} />
      </ErrorBoundary>
    );
  };
};

export default ErrorBoundary;
