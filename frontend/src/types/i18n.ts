import type fr from '@/locales/fr';

/** Shape of every language file: the French reference (see locales/fr.ts) */
export type Translation = typeof fr;

/** Types `t()` against the French reference: an unknown key does not compile */
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation';
    resources: { translation: Translation };
  }
}
