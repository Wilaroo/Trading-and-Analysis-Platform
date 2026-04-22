import React from 'react';

export const Sparkline = ({ data = [], color = 'cyan', height = 24 }) => {
  if (!data || data.length < 2) return null;

  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;

  // Add padding to prevent clipping at edges
  const padding = 5;
  const points = data.map((val, i) => {
    const x = padding + (i / (data.length - 1)) * (100 - padding * 2);
    const y = padding + (100 - padding * 2) - ((val - min) / range) * (100 - padding * 2);
    return `${x},${y}`;
  }).join(' ');

  const strokeColor = color === 'emerald' ? '#10b981' : color === 'rose' ? '#f43f5e' : '#06b6d4';

  return (
    <svg
      viewBox="0 0 100 100"
      className="w-full h-full"
      preserveAspectRatio="none"
      style={{ display: 'block' }}
    >
      <polyline
        points={points}
        fill="none"
        stroke={strokeColor}
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
};

// Generate sparkline data based on P&L direction and percentage
export const generateSparklineData = (pnl, pnlPercent = 0) => {
  const isPositive = pnl >= 0;
  const magnitude = Math.min(Math.abs(pnlPercent || 0), 10); // Cap at 10% for visual scaling
  const baseValue = 50;
  const points = 8;
  const data = [];

  for (let i = 0; i < points; i++) {
    // Create a trend line with some variation
    const progress = i / (points - 1);
    const trend = isPositive
      ? baseValue + (magnitude * progress * 3) // Upward trend
      : baseValue - (magnitude * progress * 3); // Downward trend

    // Add some natural variation (smaller as we approach current price)
    const variation = (Math.random() - 0.5) * (2 - progress) * 2;
    data.push(Math.max(0, trend + variation));
  }

  return data;
};
