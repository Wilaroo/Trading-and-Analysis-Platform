/**
 * timeET.js — single source of truth for time formatting in the app.
 *
 * Why this exists: the operator wants ALL user-facing times in 12-hour
 * US Eastern Time (e.g. "9:30 AM", "1:55 PM"). Server timestamps may
 * arrive in UTC, browser-local, or as Unix seconds — these helpers
 * normalize them to ET-12h consistently.
 *
 * EVERY user-facing time formatter in the app should go through
 * fmtET12() / fmtET12Date() / fmtETClock() — DO NOT use raw
 * toLocaleTimeString() with hour12:false anywhere new.
 */

const ET_TZ = 'America/New_York';

const _normalize = (input) => {
  // Accept Date, ISO string, Unix seconds (number ≤ 1e11), Unix millis.
  if (input instanceof Date) return input;
  if (input == null) return null;
  if (typeof input === 'number') {
    return new Date(input < 1e11 ? input * 1000 : input);
  }
  // Fall through for ISO / RFC strings.
  const d = new Date(input);
  return Number.isNaN(d.getTime()) ? null : d;
};

/** "9:30 AM" / "1:55 PM" — 12-hour clock without seconds. */
export const fmtET12 = (input) => {
  const d = _normalize(input);
  if (!d) return '—';
  return d.toLocaleTimeString('en-US', {
    timeZone: ET_TZ,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
};

/** "9:30:42 AM" — with seconds (for "last update XX" style labels). */
export const fmtET12Sec = (input) => {
  const d = _normalize(input);
  if (!d) return '—';
  return d.toLocaleTimeString('en-US', {
    timeZone: ET_TZ,
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
};

/** "Feb 19, 2026 9:30 AM" — full datetime in ET. */
export const fmtET12Date = (input) => {
  const d = _normalize(input);
  if (!d) return '—';
  return d.toLocaleString('en-US', {
    timeZone: ET_TZ,
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
};

/** "Mon Feb 19, 9:30 AM" — short variant for cards/tooltips. */
export const fmtET12Short = (input) => {
  const d = _normalize(input);
  if (!d) return '—';
  return d.toLocaleString('en-US', {
    timeZone: ET_TZ,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
};

/**
 * tickMarkFormatter for lightweight-charts.
 *
 * lightweight-charts passes a `TickMarkType` enum telling us what *kind*
 * of boundary this tick represents:
 *   0 = Year, 1 = Month, 2 = DayOfMonth   → render a DATE label
 *   3 = Time, 4 = TimeWithSeconds         → render a 12-hour TIME label
 *
 * Without this branch, intraday charts that span multiple sessions
 * print non-monotonic labels (e.g. "1:00 PM → 4:00 AM" because the
 * day boundary tick still showed time-of-day instead of "Apr 27").
 */
export const chartTickMarkFormatterET = (time, tickMarkType) => {
  // Daily-series ticks arrive as { year, month, day } regardless of type.
  if (time && typeof time === 'object' && 'year' in time) {
    const d = new Date(Date.UTC(time.year, (time.month || 1) - 1, time.day || 1));
    return d.toLocaleDateString('en-US', { timeZone: ET_TZ, month: 'short', day: 'numeric' });
  }
  // Intraday ticks: switch on the boundary type so day-rollovers show a
  // date and intra-day ticks show a 12-h clock.
  if (tickMarkType === 0 || tickMarkType === 1 || tickMarkType === 2) {
    const d = _normalize(time);
    if (!d) return '—';
    return d.toLocaleDateString('en-US', { timeZone: ET_TZ, month: 'short', day: 'numeric' });
  }
  return fmtET12(time);
};

/**
 * localization.timeFormatter for lightweight-charts crosshair label.
 * Receives Unix seconds (or a BusinessDay obj for daily series).
 */
export const chartCrosshairFormatterET = (time) => {
  if (time && typeof time === 'object' && 'year' in time) {
    const d = new Date(Date.UTC(time.year, (time.month || 1) - 1, time.day || 1));
    return d.toLocaleDateString('en-US', {
      timeZone: ET_TZ,
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }
  return fmtET12Sec(time);
};

/**
 * Returns a "10 sec ago" / "2 min ago" relative string. ET-agnostic
 * (relative time is timezone-independent). Used for "last push 6s ago"
 * style chips.
 */
export const fmtAgoShort = (input) => {
  const d = _normalize(input);
  if (!d) return '—';
  const sec = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
};
