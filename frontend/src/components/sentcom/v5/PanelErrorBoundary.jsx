/**
 * PanelErrorBoundary — per-panel React error boundary.
 * Catches render-phase + lifecycle errors inside a single V5 panel so a
 * crash in Scanner / Briefings / ChartPanel / TopMovers doesn't bring
 * down the whole Command Center.
 *
 * When a child crashes:
 *   - Log the error to console (dev observability)
 *   - Replace the panel with a minimal "⚠ panel crashed" card that
 *     offers a "reload panel" button (resets boundary state → child
 *     re-mounts fresh)
 *   - Siblings keep rendering normally
 *
 * Name the panel via the `label` prop so the crash card identifies which
 * surface failed — makes bug reports faster.
 */

import React from 'react';

export class PanelErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    // eslint-disable-next-line no-console
    console.error(
      `[PanelErrorBoundary] ${this.props.label || 'panel'} crashed:`,
      error,
      errorInfo
    );
  }

  reset = () => {
    this.setState({ hasError: false, error: null });
  };

  copyError = () => {
    try {
      const { label = 'panel' } = this.props;
      const msg = String(this.state.error?.message || this.state.error || 'unknown error');
      const stack = this.state.error?.stack || '';
      const text = `[SentCom panel-error] ${label}\n${msg}\n${stack}`;
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text);
      }
    } catch {
      /* clipboard unavailable — ignore */
    }
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    const { label = 'panel', compact = false } = this.props;
    const msg = String(this.state.error?.message || this.state.error || 'unknown error');
    return (
      <div
        data-testid={`panel-error-${label}`}
        className={`bg-rose-950/30 border border-rose-800/40 rounded p-3 text-rose-300 ${compact ? 'text-[10px]' : 'text-[11px]'}`}
      >
        <div className="flex items-center gap-2 mb-1.5">
          <span className="v5-mono font-bold uppercase tracking-wide">⚠ {label} crashed</span>
          <button
            type="button"
            onClick={this.copyError}
            data-testid={`panel-error-copy-${label}`}
            className="ml-auto v5-mono text-[9px] px-1.5 py-0.5 rounded bg-rose-900/50 hover:bg-rose-800 transition-colors"
            title="Copy error + stack trace to clipboard"
          >
            copy error ⧉
          </button>
          <button
            type="button"
            onClick={this.reset}
            data-testid={`panel-error-reset-${label}`}
            className="v5-mono text-[9px] px-1.5 py-0.5 rounded bg-rose-900/50 hover:bg-rose-800 transition-colors"
          >
            reload panel ↻
          </button>
        </div>
        <div className="v5-mono text-[10px] opacity-75 truncate" title={msg}>
          {msg}
        </div>
      </div>
    );
  }
}

export default PanelErrorBoundary;
