import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import fr from '@/locales/fr';

/**
 * Translation instance. Components use `useTranslation()`; non-React code (API errors) calls `i18n.t` directly.
 * French only for now: adding a language = a `locales/<lng>.ts` typed `Translation`, added to `resources`.
 */
i18n.use(initReactI18next).init({
  lng: 'fr',
  fallbackLng: 'fr',
  resources: { fr: { translation: fr } },
  // React already escapes rendered values
  interpolation: { escapeValue: false },
  initAsync: false,
});

document.documentElement.lang = i18n.language;
document.title = i18n.t('app.name');

export default i18n;
