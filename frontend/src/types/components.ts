import type { ReactNode } from 'react';
import type { AskAnswer } from '@/api/generated/model/askAnswer';
import type { CapturedDevice } from '@/api/generated/model/capturedDevice';
import type { MeetingAnalysis } from '@/api/generated/model/meetingAnalysis';
import type { MeetingListItem } from '@/api/generated/model/meetingListItem';
import type { Preferences } from '@/api/generated/model/preferences';
import type { Segment } from '@/api/generated/model/segment';
import type { AudioSource, LiveState, PartialText } from '@/types/events';

/** A meeting of the history: opened by a click, deleted from its trash button */
export interface MeetingCardProps {
  meeting: MeetingListItem;
  /** The meeting is on screen: outlined */
  active: boolean;
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
  /** Sentences being spoken, shown after the final ones until their transcription replaces them */
  partials?: PartialText[];
  /** Height of the scrolling panel, in pixels */
  height: number;
  /** Names a speaker in the whole meeting (giving an existing name merges both); without it, names are read-only */
  onRenameSpeaker?: (old: string, name: string) => void;
}

/** Questions about a meeting, answered by the local AI from its transcript */
export interface AskPanelProps {
  meetingId: number;
  /** Nothing transcribed yet: questions cannot be asked */
  disabled: boolean;
  /** Expected duration of an answer, in seconds */
  estimateS: number;
  /** Questions already asked about this meeting, oldest first */
  questions: AskAnswer[];
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

/** Opens the settings window from anywhere (header button, "Edit" link of the home page) */
export interface SettingsDialogState {
  opened: boolean;
  open: () => void;
  close: () => void;
}

export interface SettingsDialogProviderProps {
  children: ReactNode;
}

export interface SettingsFormProps {
  preferences: Preferences;
  onSaved: () => void;
}

/** State of a model for its status dot: color and explanation */
export interface ModelState {
  tone: 'success' | 'warning' | 'danger';
  hint: string;
}

/** Status dot of the local AI, with its restart button when it does not run properly */
export interface AiStatusProps {
  ai: ModelState;
  /** AI model in use (e.g. qwen2.5:7b), shown next to "AI" */
  model: string;
  restartable: boolean;
  restarting: boolean;
  onRestart: () => void;
}

/** Start form of a meeting, with the saved settings (devices, audio, default language) */
export interface RecordFormProps {
  preferences: Preferences;
}

/** Meetings open as tabs, by id, in their display order */
export interface TabsState {
  ids: number[];
  add: (meetingId: number) => void;
  remove: (meetingId: number) => void;
}

export interface TabsProviderProps {
  children: ReactNode;
}

/** Progress of a task of known expected duration (the local AI): a horizontal bar and the time left */
export interface EstimatedProgressProps {
  label: string;
  /** Expected duration, in seconds */
  estimateS: number;
  /** When the task started (milliseconds since the epoch) */
  startedAt: number;
}
