import type { Tone } from '@ign-junn/design-system';
import type { MeetingStatus } from '@/api/generated/model/meetingStatus';

/** Color of the status badge of a meeting */
export const STATUS_TONES: Record<MeetingStatus, Tone> = {
  recording: 'danger',
  transcribing: 'primary',
  transcribed: 'muted',
  analyzing: 'primary',
  done: 'success',
  error: 'warning',
};

/** One-click questions of the meeting page, by their key in locales `ask.quick` and `ask.quickQuestions` */
export const QUICK_QUESTIONS = ['summary', 'myActions', 'decisions'] as const;

/** Height of the transcript side panel, in pixels: it scrolls inside, the page keeps it in view */
export const TRANSCRIPT_PANEL_HEIGHT = 640;

/** Statuses during which the meeting page listens to live events */
export const LIVE_STATUSES: MeetingStatus[] = ['recording', 'transcribing', 'analyzing'];
