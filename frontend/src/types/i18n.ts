import type { LANGUAGES } from '@/constants/i18n';
import type fr from '@/locales/fr';

/** Shape of every language file: the French reference (see locales/fr.ts) */
export type Translation = typeof fr;

/** Language of the interface */
export type Language = (typeof LANGUAGES)[number];

export const isLanguage = (value: unknown): value is Language => value === 'fr' || value === 'en';

/** Types `t()` against the French reference: an unknown key does not compile */
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation';
    resources: { translation: Translation };
  }
}
