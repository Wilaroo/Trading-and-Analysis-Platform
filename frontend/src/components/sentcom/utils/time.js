// Timestamp formatters used across SentCom panels.

// Format timestamp to relative time (e.g., "2 mins ago", "Just now")
export const formatRelativeTime = (timestamp) => {
  if (!timestamp) return '';

  const now = new Date();
  const time = new Date(timestamp);
  const diffMs = now - time;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 10) return 'Just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;

  return time.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

// Format timestamp to full time (e.g., "2:05:36 PM")
export const formatFullTime = (timestamp) => {
  if (!timestamp) return '';
  const time = new Date(timestamp);
  return time.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
};
