const pad = (value: number) => String(value).padStart(2, '0');

/** `hh:mm:ss` of a duration in seconds (negative values count as 0) */
const duration = (totalSeconds: number) => {
  const seconds = Math.max(0, Math.floor(totalSeconds));

  return `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor((seconds % 3600) / 60))}:${pad(seconds % 60)}`;
};

/** Text formats of the meetings: durations, dates, clock times, default titles */
const format = {
  duration,
  /** Seconds between two ISO dates */
  secondsBetween: (start: string, end: string) => (new Date(end).getTime() - new Date(start).getTime()) / 1000,
  /** Wall-clock time of a segment, from the meeting start and its offset in seconds */
  clock: (startedAt: string, offsetSeconds: number, locale: string) =>
    new Date(new Date(startedAt).getTime() + offsetSeconds * 1000).toLocaleTimeString(locale),
  /** Date and time of a meeting */
  date: (iso: string, locale: string) =>
    new Date(iso).toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' }),
  /** File name without its extension, as a default title */
  fileTitle: (name: string) => name.replace(/\.[^.]+$/, ''),
  /** Audio level in dBFS as a 0–100 meter value, from `floor` (silence) to 0 dBFS */
  level: (db: number, floor: number) => Math.min(100, Math.max(0, ((db - floor) / -floor) * 100)),
};

export default format;
