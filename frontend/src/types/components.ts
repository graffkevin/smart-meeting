import type { CapturedDevice } from '@/api/generated/model/capturedDevice';
import type { MeetingAnalysis } from '@/api/generated/model/meetingAnalysis';
import type { MeetingListItem } from '@/api/generated/model/meetingListItem';
import type { Segment } from '@/api/generated/model/segment';
import type { AudioSource, LiveState } from '@/types/events';

/** A meeting of the history: opened by a click, deleted from its trash button */
export interface MeetingCardProps {
  meeting: MeetingListItem;
  onOpen: () => void;
  onDelete: () => void;
}

/** Report of a meeting, from the analysis of the local AI */
export interface MeetingReportProps {
  analysis: MeetingAnalysis;
}

/** Transcript as a conversation: my sentences on one side, the other participants on the other */
export interface TranscriptProps {
  segments: Segment[];
  /** Meeting start, for wall-clock times; `null` shows positions in the file (imported files) */
  startedAt: string | null;
  /** Recording: follows the last sentence, and an empty transcript means "listening" */
  live: boolean;
}

/** Confirmation of an action that cannot be undone */
export interface ConfirmDialogProps {
  opened: boolean;
  title: string;
  text: string;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
  /** The confirmed action is running */
  loading?: boolean;
}

/** Quit button of the header: the app shows its stopped state while and after quitting */
export interface QuitButtonProps {
  onStopping: () => void;
  onStopped: () => void;
}

export interface MeetingViewProps {
  meetingId: number;
}

/** Live part of a meeting being recorded: duration, audio levels, captured devices, stop button */
export interface LivePanelProps {
  startedAt: string;
  live: LiveState;
  captured: Partial<Record<AudioSource, CapturedDevice>> | null;
  onStop: () => void;
  stopping: boolean;
}
