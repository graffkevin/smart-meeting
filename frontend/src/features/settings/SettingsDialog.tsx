import { Button, Checkbox, Dialog, isDefined, Select, Spinner, Stack, TextField } from '@ign-junn/design-system';
import { IconHeadphones, IconLanguage, IconMicrophone, IconUser } from '@tabler/icons-react';
import { useForm } from '@tanstack/react-form';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import type { AudioDevice } from '@/api/generated/model/audioDevice';
import type { Preferences } from '@/api/generated/model/preferences';
import { updatePreferences } from '@/api/generated/smartMeetingApi';
import { AUTO_DEVICE, TRANSCRIPTION_LANGUAGES } from '@/constants/app';
import useSettingsDialog from '@/contexts/settings/useSettingsDialog';
import audioDevicesQueryOptions from '@/services/audioDevicesQueryOptions';
import preferencesQueryOptions from '@/services/preferencesQueryOptions';
import type { SettingsFormProps } from '@/types/components';
import type { TranscriptionLanguage } from '@/types/meeting';

/** The form of the settings, once they are loaded (its default values are read once) */
const SettingsForm = ({ preferences, onSaved }: SettingsFormProps) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: devices } = useQuery(audioDevicesQueryOptions());
  const save = useMutation({
    mutationFn: (values: Preferences) => updatePreferences(values),
    onSuccess: (saved) => {
      queryClient.setQueryData(preferencesQueryOptions().queryKey, saved);
      onSaved();
    },
  });
  const { Field, handleSubmit } = useForm({
    defaultValues: {
      userName: preferences.user_name ?? '',
      glossary: preferences.glossary ?? [],
      language: (preferences.language ?? 'auto') as TranscriptionLanguage,
      mic: preferences.mic_device ?? AUTO_DEVICE,
      output: preferences.output_device ?? AUTO_DEVICE,
      keepAudio: preferences.keep_audio ?? false,
    },
    onSubmit: ({ value }) =>
      save.mutate({
        user_name: value.userName,
        glossary: value.glossary,
        language: value.language,
        mic_device: value.mic === AUTO_DEVICE ? null : value.mic,
        output_device: value.output === AUTO_DEVICE ? null : value.output,
        keep_audio: value.keepAudio,
        ui_language: preferences.ui_language,
      }),
  });
  const describe = (list: AudioDevice[], name: string | null | undefined) =>
    list.find((device) => device.name === name)?.description ?? name ?? '';
  const deviceOptions = (list: AudioDevice[], inUse: string | null | undefined) => [
    { value: AUTO_DEVICE, label: t('settings.automatic', { device: describe(list, inUse) }) },
    ...list.map((device) => ({ value: device.name, label: device.description })),
  ];

  return (
    <Stack
      component="form"
      gap="md"
      onSubmit={(event) => {
        event.preventDefault();
        handleSubmit();
      }}
    >
      <Field name="userName">
        {(field) => (
          <TextField
            label={t('settings.name')}
            description={t('settings.nameHelp')}
            icon={IconUser}
            value={field.state.value}
            onChange={field.handleChange}
          />
        )}
      </Field>
      <Field name="glossary">
        {(field) => (
          <TextField
            type="tags"
            label={t('settings.glossary')}
            description={t('settings.glossaryHelp')}
            placeholder={t('settings.glossaryPlaceholder')}
            value={field.state.value}
            onChange={field.handleChange}
          />
        )}
      </Field>
      <Field name="language">
        {(field) => (
          <Select<TranscriptionLanguage>
            label={t('settings.language')}
            description={t('languages.help')}
            icon={IconLanguage}
            options={TRANSCRIPTION_LANGUAGES.map((code) => ({ value: code, label: t(`languages.${code}`) }))}
            value={field.state.value}
            onChange={(value) => field.handleChange(value ?? 'auto')}
          />
        )}
      </Field>
      <Field name="mic">
        {(field) => (
          <Select
            label={t('settings.mic')}
            description={t('settings.micHelp')}
            icon={IconMicrophone}
            options={deviceOptions(devices?.sources ?? [], devices?.in_use_source)}
            value={field.state.value}
            onChange={(value) => field.handleChange(value ?? AUTO_DEVICE)}
          />
        )}
      </Field>
      <Field name="output">
        {(field) => (
          <Select
            label={t('settings.output')}
            description={t('settings.outputHelp')}
            icon={IconHeadphones}
            options={deviceOptions(devices?.sinks ?? [], devices?.in_use_sink)}
            value={field.state.value}
            onChange={(value) => field.handleChange(value ?? AUTO_DEVICE)}
          />
        )}
      </Field>
      <Field name="keepAudio">
        {(field) => (
          <Checkbox
            checked={field.state.value}
            onChange={field.handleChange}
            label={t('settings.keepAudio')}
            description={t('settings.keepAudioHelp')}
          />
        )}
      </Field>
      <Stack direction="row" justify="flex-end">
        <Button type="submit" label={t('settings.save')} loading={save.isPending} />
      </Stack>
    </Stack>
  );
};

/** Settings window, opened from the header or the home page */
const SettingsDialog = () => {
  const { t } = useTranslation();
  const { data: preferences } = useQuery(preferencesQueryOptions());
  const { opened, close } = useSettingsDialog();

  return (
    <Dialog
      opened={opened}
      onClose={close}
      title={t('settings.title')}
      description={t('settings.description')}
      closeLabel={t('common.close')}
    >
      {isDefined(preferences) ? (
        <SettingsForm preferences={preferences} onSaved={close} />
      ) : (
        <Spinner label={t('common.loading')} />
      )}
    </Dialog>
  );
};

export default SettingsDialog;
