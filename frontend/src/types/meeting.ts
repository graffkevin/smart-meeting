import type { TRANSCRIPTION_LANGUAGES } from '@/constants/app';

export type TranscriptionLanguage = (typeof TRANSCRIPTION_LANGUAGES)[number];

/** Values of the form starting a recording (devices and audio come from the settings) */
export interface StartFormValues {
  title: string;
  language: TranscriptionLanguage;
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
