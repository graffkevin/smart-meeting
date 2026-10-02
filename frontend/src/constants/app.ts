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

/** Value of the device selects meaning "follow the devices the applications use" */
export const AUTO_DEVICE = 'auto';

/** Transcription languages offered ("auto": detected, sticky), labels in locales `languages` */
export const TRANSCRIPTION_LANGUAGES = ['auto', 'fr', 'en', 'de', 'es', 'it'] as const;
