/**
 * SystemBanner.jsx (v19.30.11, 2026-05-01)
 * ========================================
 *
 * Top-of-page alert strip that polls /api/system/banner every 10s and
 * renders a giant red banner when a critical subsystem is degraded.
 *
 * Why this exists:
 *   Operator spent 2026-05-01 afternoon thinking the Spark backend was
 *   broken because the dashboard had no live data. The real cause was
 *   the Windows pusher had died — but that was buried in a small
 *   "PUSHER RED" pill on the side of the V5 HUD that was easy to miss.
 *   The operator ran ./start_backend.sh to "fix" the dashboard,
 *   accidentally killing a perfectly-healthy backend.
 *
 *   This banner makes that mistake structurally impossible: when a
 *   critical subsystem is red, the dashboard SCREAMS at the operator
 *   in a way that cannot be missed, AND tells them exactly what to do.
 *
 * Mounted at the root of the V5 HUD layout (above all other content).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const POLL_INTERVAL_MS = 10000;            // poll banner every 10s
const REAPPEAR_INTERVAL_MS = 60000;        // dismissed banners reappear after 60s
                                            // if problem persists

const SystemBanner = () => {
    const [banner, setBanner] = useState(null);
    const [dismissedAt, setDismissedAt] = useState(0);
    const dismissedSubsystemRef = useRef(null);

    const fetchBanner = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/system/banner`);
            if (!resp.ok) return;
            const data = await resp.json();
            setBanner(data);
        } catch {
            // Network blip — keep the previous banner state. We never
            // want to clear a critical banner just because one poll
            // failed (the network outage IS the problem we're alerting
            // on).
        }
    }, []);

    useEffect(() => {
        fetchBanner();
        const id = setInterval(fetchBanner, POLL_INTERVAL_MS);
        return () => clearInterval(id);
    }, [fetchBanner]);

    if (!banner || !banner.level) return null;

    // Auto-clear dismissal if the problem is now a different subsystem
    // (so we don't accidentally hide a NEW alert because we dismissed
    // an OLD one).
    if (
        dismissedSubsystemRef.current &&
        dismissedSubsystemRef.current !== banner.subsystem
    ) {
        dismissedSubsystemRef.current = null;
        setDismissedAt(0);
    }

    // If dismissed within the reappear window, hide.
    const now = Date.now();
    if (dismissedAt > 0 && (now - dismissedAt) < REAPPEAR_INTERVAL_MS) {
        return null;
    }

    const isCritical = banner.level === 'critical';
    const stripClasses = isCritical
        ? 'bg-red-700 border-red-500 text-white'
        : 'bg-amber-700 border-amber-500 text-white';

    const sinceLabel = banner.since_seconds != null
        ? `${Math.floor(banner.since_seconds / 60)}m ${banner.since_seconds % 60}s`
        : null;

    const handleDismiss = () => {
        dismissedSubsystemRef.current = banner.subsystem;
        setDismissedAt(Date.now());
    };

    return (
        <div
            data-testid="system-banner"
            data-level={banner.level}
            data-subsystem={banner.subsystem || 'unknown'}
            className={`w-full border-b-2 ${stripClasses} px-4 py-3 shadow-lg`}
            style={{ position: 'sticky', top: 0, zIndex: 9999 }}
        >
            <div className="max-w-screen-2xl mx-auto flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 flex-1 min-w-0">
                    <span
                        className="text-xl font-bold flex-shrink-0"
                        aria-hidden="true"
                    >
                        {isCritical ? '⚠' : '!'}
                    </span>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-3 flex-wrap">
                            <span
                                data-testid="system-banner-message"
                                className="font-bold text-base sm:text-lg"
                            >
                                {banner.message}
                            </span>
                            {sinceLabel && (
                                <span
                                    data-testid="system-banner-since"
                                    className="text-xs opacity-80 font-mono"
                                >
                                    for {sinceLabel}
                                </span>
                            )}
                        </div>
                        {banner.detail && (
                            <div
                                data-testid="system-banner-detail"
                                className="text-sm opacity-95 mt-0.5"
                            >
                                {banner.detail}
                            </div>
                        )}
                        {banner.action && (
                            <div
                                data-testid="system-banner-action"
                                className="text-sm font-medium mt-1 opacity-100"
                            >
                                <span className="opacity-80">→</span> {banner.action}
                            </div>
                        )}
                    </div>
                </div>
                <button
                    type="button"
                    data-testid="system-banner-dismiss"
                    onClick={handleDismiss}
                    className="flex-shrink-0 text-xs px-3 py-1 rounded border border-white/40 hover:bg-white/10 transition-colors font-medium"
                    title="Dismiss for 60s — banner reappears if problem persists"
                >
                    Dismiss 60s
                </button>
            </div>
        </div>
    );
};

export default SystemBanner;
export { SystemBanner };
