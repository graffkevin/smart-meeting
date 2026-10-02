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

/** Statuses during which the meeting page listens to live events */
export const LIVE_STATUSES: MeetingStatus[] = ['recording', 'transcribing', 'analyzing'];
