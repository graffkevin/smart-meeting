/** Routes of the app (hash router: the backend serves a single page) */
export const ROUTES = {
  home: '/',
  meeting: '/meetings/:meetingId',
} as const;

export const meetingPath = (meetingId: number) => `/meetings/${meetingId}`;
