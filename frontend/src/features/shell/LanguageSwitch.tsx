import { isDefined, SegmentedSwitch } from '@ign-junn/design-system';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { updatePreferences } from '@/api/generated/smartMeetingApi';
import { LANGUAGES } from '@/constants/i18n';
import preferencesQueryOptions from '@/services/preferencesQueryOptions';
import { isLanguage, type Language } from '@/types/i18n';

/**
 * FR | EN switch of the header. The server is told too: the AI answers, the minutes and the default meeting names
 * follow the interface language.
 */
const LanguageSwitch = () => {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { data: preferences } = useQuery(preferencesQueryOptions());
  const { mutate: save } = useMutation({
    mutationFn: (language: Language) =>
      isDefined(preferences)
        ? updatePreferences({ ...preferences, ui_language: language })
        : Promise.reject(new Error(t('common.loading'))),
    onSuccess: (saved) => queryClient.setQueryData(preferencesQueryOptions().queryKey, saved),
  });
  const language = isLanguage(i18n.language) ? i18n.language : 'fr';

  // The server keeps the language of the interface (an external system): aligned once its settings are known
  useEffect(() => {
    if (isDefined(preferences) && preferences.ui_language !== language) save(language);
  }, [preferences, language, save]);

  return (
    <SegmentedSwitch<Language>
      label={t('shell.language')}
      options={LANGUAGES.map((code) => ({ value: code, label: code.toUpperCase() }))}
      value={language}
      onChange={(code) => i18n.changeLanguage(code)}
      size="xs"
    />
  );
};

export default LanguageSwitch;
