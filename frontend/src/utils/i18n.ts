import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { DEFAULT_LANGUAGE, LANGUAGE_STORAGE_KEY } from '@/constants/i18n';
import en from '@/locales/en';
import fr from '@/locales/fr';
import { isLanguage, type Language } from '@/types/i18n';

/** Language chosen earlier, else the browser's; storage can be unavailable (private mode) */
const initialLanguage = (): Language => {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (isLanguage(stored)) return stored;
  } catch {
    // Storage unavailable: fall back to the browser language
  }
  const browser = navigator.language.slice(0, 2);

  return isLanguage(browser) ? browser : DEFAULT_LANGUAGE;
};

/**
 * Translation instance. Components use `useTranslation()`; non-React code (API errors) calls `i18n.t` directly.
 * Adding a language = a `locales/<lng>.ts` typed `Translation`, added to `resources` and `LANGUAGES`.
 */
i18n.use(initReactI18next).init({
  lng: initialLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  resources: { fr: { translation: fr }, en: { translation: en } },
  // React already escapes rendered values
  interpolation: { escapeValue: false },
  initAsync: false,
});

/** Keeps the page language, its title and the stored choice in sync (no React effect needed) */
const syncDocument = (language: string) => {
  document.documentElement.lang = language;
  document.title = i18n.t('app.name');
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Storage unavailable: the choice simply is not remembered
  }
};
i18n.on('languageChanged', syncDocument);
syncDocument(i18n.language);

export default i18n;
