import type { TRANSCRIPTION_LANGUAGES } from '@/constants/app';

export type TranscriptionLanguage = (typeof TRANSCRIPTION_LANGUAGES)[number];

/** Values of the form starting a recording */
export interface StartFormValues {
  title: string;
  mic: string;
  output: string;
  keepAudio: boolean;
  language: TranscriptionLanguage;
}

/** Values of the form importing a file */
export interface ImportFormValues {
  file: File | null;
  title: string;
  language: TranscriptionLanguage;
}

/** Steps of quitting the app from its Quit button */
export type QuitState = 'running' | 'quitting' | 'stopped';
