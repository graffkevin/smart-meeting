/** How often the home page refreshes the server status (installs, models, active meeting) */
export const HEALTH_POLL_MS = 2000;

/** Delay between the last key typed in the history search and the search */
export const SEARCH_DEBOUNCE_MS = 250;

/** Presence WebSocket held by every page (see features/shell/useServerPresence) */
export const PRESENCE_PATH = '/api/presence';

/** Delay before reconnecting the presence WebSocket after the server stopped */
export const PRESENCE_RETRY_MS = 2000;

/** Live events of a meeting: segments, status, audio levels, capture devices, import progress */
export const meetingEventsPath = (meetingId: number) => `/api/meetings/${meetingId}/ws`;

/** Audio level shown as silence (dBFS): the meters go from this floor to 0 dBFS */
export const LEVEL_FLOOR_DB = -60;

/** Expected duration of a local AI task before the server tells it (seconds) */
export const DEFAULT_ESTIMATE_S = 30;

/** A progress bar never shows a task done before it is (its estimate may be short) */
export const PROGRESS_MAX_BEFORE_DONE = 95;

/** Value of the device selects meaning "follow the devices the applications use" */
export const AUTO_DEVICE = 'auto';

/** Transcription languages offered ("auto": detected, sticky), labels in locales `languages` */
export const TRANSCRIPTION_LANGUAGES = ['auto', 'fr', 'en', 'de', 'es', 'it'] as const;

/** A final sentence replaces a provisional text that started at most this much later (seconds) */
export const PARTIAL_TOLERANCE_S = 0.5;

/** Open meeting tabs, kept in this browser between sessions */
export const TABS_STORAGE_KEY = 'smart-meeting.tabs';

/** Recent meetings offered by the "+" of the tab bar */
export const RECENT_MEETINGS_IN_TABS = 8;

/** Value of the "+" option that goes back to the home page to start a meeting */
export const NEW_MEETING_TAB = 'new';
