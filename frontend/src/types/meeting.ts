import type { MeetingListItem } from '@/api/generated/model/meetingListItem';
import type { TRANSCRIPTION_LANGUAGES } from '@/constants/app';

export type TranscriptionLanguage = (typeof TRANSCRIPTION_LANGUAGES)[number];

/** Values of the form starting a recording (devices and audio come from the settings) */
export interface StartFormValues {
  title: string;
  language: TranscriptionLanguage;
  tags: string[];
}

/** Values of the form importing a file */
export interface ImportFormValues {
  file: File | null;
  title: string;
  language: TranscriptionLanguage;
}

/** A question asked to the local AI and its answer, split into lines for display */
export interface AnswerEntry {
  id: string;
  question: string;
  lines: { key: string; text: string }[];
}

/** Steps of quitting the app from its Quit button */
export type QuitState = 'running' | 'quitting' | 'stopped';

/** A meeting renamed from its tab */
export interface RenameValues {
  id: number;
  title: string;
}

/** How the history lists the meetings */
export type HistoryView = 'byDate' | 'byTag';

/** Day of the history a meeting falls in, from its start: today, yesterday, or an earlier day (named by its date) */
export type HistoryPeriod = 'today' | 'yesterday' | 'day';

/** Meetings of a day in the history, newest first (`day`: its midnight, for its label) */
export interface DateGroup {
  key: string;
  period: HistoryPeriod;
  day: Date;
  meetings: MeetingListItem[];
}

/** Meetings of a tag in the history (a meeting with several tags is in several groups) */
export interface TagGroup {
  tag: string;
  meetings: MeetingListItem[];
}
