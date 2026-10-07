import { isDefined, isFiniteNumber, isRecord, isString } from '@ign-junn/design-system';
import type { CapturedDevice } from '@/api/generated/model/capturedDevice';
import { MeetingStatus } from '@/api/generated/model/meetingStatus';
import type { Segment } from '@/api/generated/model/segment';

/** Audio sources of a meeting: my microphone, and what the other participants say (the output) */
export type AudioSource = 'mic' | 'remote';

export type AudioLevels = Record<AudioSource, number>;

/** Provisional text of the sentence being spoken: shown live, replaced by its final transcription */
export interface PartialText {
  source: AudioSource;
  speaker: string;
  start_s: number;
  text: string;
}

/** Live events of a meeting WebSocket (backend `EventHub`) */
export type MeetingEvent =
  | { type: 'segment'; segment: Segment }
  | { type: 'status'; status: MeetingStatus; error: string | null }
  | { type: 'levels'; levels: AudioLevels; queue: number }
  | { type: 'devices'; devices: Partial<Record<AudioSource, CapturedDevice>> }
  | { type: 'progress'; done_s: number; total_s: number | null }
  | { type: 'speakers' }
  | ({ type: 'partial' } & PartialText);

const isMeetingStatus = (value: unknown): value is MeetingStatus =>
  Object.values(MeetingStatus).some((status) => status === value);

const isSegment = (value: unknown): value is Segment =>
  isRecord(value) &&
  isString(value.text) &&
  isFiniteNumber(value.start_s) &&
  (value.source === 'mic' || value.source === 'remote');

const isLevels = (value: unknown): value is AudioLevels =>
  isRecord(value) && isFiniteNumber(value.mic) && isFiniteNumber(value.remote);

/** A message of the meeting WebSocket, checked before use (external data) */
export const isMeetingEvent = (value: unknown): value is MeetingEvent => {
  if (!isRecord(value)) return false;
  if (value.type === 'segment') return isSegment(value.segment);
  if (value.type === 'status') return isMeetingStatus(value.status);
  if (value.type === 'levels') return isLevels(value.levels) && isFiniteNumber(value.queue);
  if (value.type === 'devices') return isRecord(value.devices);
  if (value.type === 'speakers') return true;
  if (value.type === 'partial')
    return (
      (value.source === 'mic' || value.source === 'remote') &&
      isString(value.speaker) &&
      isFiniteNumber(value.start_s) &&
      isString(value.text)
    );

  return (
    value.type === 'progress' &&
    isFiniteNumber(value.done_s) &&
    (!isDefined(value.total_s) || isFiniteNumber(value.total_s))
  );
};

/** Live state of a meeting that is not stored: audio levels, capture devices, import progress */
export interface LiveState {
  levels: AudioLevels | null;
  queue: number;
  devices: Partial<Record<AudioSource, CapturedDevice>> | null;
  progress: { done: number; total: number | null } | null;
  /** Sentence being spoken, per source */
  partials: Partial<Record<AudioSource, PartialText>>;
}
