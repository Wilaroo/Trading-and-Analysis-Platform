/**
 * StatusDot - Minimal status indicator dot
 * =========================================
 * 
 * Small, unobtrusive dot indicator for showing connection status
 * next to features that require specific services.
 * 
 * Usage:
 *   <StatusDot service="ibGateway" />
 *   <StatusDot status="connected" />
 *   <StatusDot services={['ibGateway', 'quotesStream']} />
 */

import React from 'react';
import { useSystemStatus } from '../contexts/SystemStatusContext';

// Status to color mapping
const STATUS_COLORS = {
  connected: 'bg-green-500',
  disconnected: 'bg-red-500',
  connecting: 'bg-yellow-500 animate-pulse',
  error: 'bg-red-500',
  unknown: 'bg-zinc-500',
};

// Status to ring color (for glow effect)
const STATUS_RINGS = {
  connected: 'ring-green-500/30',
  disconnected: 'ring-red-500/30',
  connecting: 'ring-yellow-500/30',
  error: 'ring-red-500/30',
  unknown: 'ring-zinc-500/30',
};

/**
 * StatusDot component
 * 
 * @param {string} service - Single service ID to check
 * @param {string[]} services - Multiple service IDs (all must be connected for green)
 * @param {string} status - Direct status override ('connected', 'disconnected', etc.)
 * @param {string} size - 'sm' | 'md' | 'lg'
 * @param {boolean} showRing - Show glow ring around dot
 * @param {boolean} pulse - Animate when not connected
 * @param {string} className - Additional classes
 * @param {string} tooltip - Tooltip text
 */
const StatusDot = ({ 
  service = null,
  services = null,
  status: directStatus = null,
  size = 'sm',
  showRing = false,
  pulse = true,
  className = '',
  tooltip = null,
}) => {
  const { getServiceStatus, isFeatureAvailable, STATUS } = useSystemStatus();
  
  // Determine status
  let status = directStatus;
  
  if (!status) {
    if (services && services.length > 0) {
      // Multiple services - all must be connected
      status = isFeatureAvailable(services) ? STATUS.CONNECTED : STATUS.DISCONNECTED;
    } else if (service) {
      // Single service
      const serviceStatus = getServiceStatus(service);
      status = serviceStatus.status;
    } else {
      status = STATUS.UNKNOWN;
    }
  }
  
  // Size classes
  const sizeClasses = {
    sm: 'w-2 h-2',
    md: 'w-2.5 h-2.5',
    lg: 'w-3 h-3',
  };
  
  const dotSize = sizeClasses[size] || sizeClasses.sm;
  const colorClass = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  const ringClass = showRing ? `ring-2 ${STATUS_RINGS[status] || STATUS_RINGS.unknown}` : '';
  const pulseClass = pulse && status !== 'connected' ? 'animate-pulse' : '';
  
  const dot = (
    <span 
      className={`inline-block rounded-full ${dotSize} ${colorClass} ${ringClass} ${pulseClass} ${className}`}
      data-testid={`status-dot-${service || 'custom'}`}
    />
  );
  
  // With tooltip
  if (tooltip) {
    return (
      <span className="relative group inline-flex items-center">
        {dot}
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 
                        bg-zinc-800 text-xs text-zinc-300 rounded whitespace-nowrap
                        opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
          {tooltip}
        </span>
      </span>
    );
  }
  
  return dot;
};

/**
 * StatusBadge - Larger badge with text for headers
 */
export const StatusBadge = ({
  service = null,
  services = null,
  status: directStatus = null,
  label = null,
  showLabel = true,
  className = '',
}) => {
  const { getServiceStatus, isFeatureAvailable, STATUS, SERVICES } = useSystemStatus();
  
  // Determine status
  let status = directStatus;
  let serviceName = label;
  
  if (!status) {
    if (services && services.length > 0) {
      status = isFeatureAvailable(services) ? STATUS.CONNECTED : STATUS.DISCONNECTED;
      serviceName = label || 'Services';
    } else if (service) {
      const serviceStatus = getServiceStatus(service);
      status = serviceStatus.status;
      serviceName = label || SERVICES[service]?.name || service;
    } else {
      status = STATUS.UNKNOWN;
    }
  }
  
  const isConnected = status === STATUS.CONNECTED;
  
  return (
    <span 
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
        ${isConnected 
          ? 'bg-green-500/20 text-green-400 border border-green-500/30' 
          : 'bg-red-500/20 text-red-400 border border-red-500/30'
        } ${className}`}
    >
      <StatusDot status={status} size="sm" pulse={!isConnected} />
      {showLabel && <span>{serviceName}</span>}
    </span>
  );
};

/**
 * FeatureGate - Wraps content that requires specific services
 * Shows disabled state or message when services unavailable
 */
export const FeatureGate = ({
  services = [],
  children,
  fallback = null,
  showMessage = true,
  message = 'Feature unavailable - required services not connected',
}) => {
  const { isFeatureAvailable } = useSystemStatus();
  
  if (isFeatureAvailable(services)) {
    return children;
  }
  
  if (fallback) {
    return fallback;
  }
  
  if (showMessage) {
    return (
      <div className="flex items-center gap-2 text-zinc-500 text-sm p-2">
        <StatusDot services={services} />
        <span>{message}</span>
      </div>
    );
  }
  
  return null;
};

export default StatusDot;
