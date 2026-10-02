import {
  Alert,
  Badge,
  Button,
  Card,
  FileButton,
  gradients,
  isDefined,
  ProgressBar,
  Select,
  Spinner,
  Stack,
  TextField,
  Typography,
} from '@ign-junn/design-system';
import {
  IconFileUpload,
  IconLanguage,
  IconMicrophone,
  IconPlayerRecordFilled,
  IconSettings,
  IconSparkles,
} from '@tabler/icons-react';
import { useForm } from '@tanstack/react-form';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import type { AudioDevice } from '@/api/generated/model/audioDevice';
import { importMeeting, startMeeting } from '@/api/generated/smartMeetingApi';
import { TRANSCRIPTION_LANGUAGES } from '@/constants/app';
import useSettingsDialog from '@/contexts/settings/useSettingsDialog';
import History from '@/features/history/History';
import useOpenMeeting from '@/hooks/useOpenMeeting';
import audioDevicesQueryOptions from '@/services/audioDevicesQueryOptions';
import healthQueryOptions from '@/services/healthQueryOptions';
import preferencesQueryOptions from '@/services/preferencesQueryOptions';
import type { RecordFormProps } from '@/types/components';
import type { ImportFormValues, StartFormValues, TranscriptionLanguage } from '@/types/meeting';
import format from '@/utils/format';

const IMPORT_DEFAULTS: ImportFormValues = { file: null, title: '', language: 'auto' };

/** Description of a device by its name, or the name itself */
const describe = (devices: AudioDevice[], name: string | null | undefined, none: string) =>
  devices.find((device) => device.name === name)?.description ?? name ?? none;

/** Server status: first-run installs with their progress, models, problems */
const HealthStatus = () => {
  const { t } = useTranslation();
  const { data: health, isError } = useQuery(healthQueryOptions());

  if (isError)
    return (
      <Alert tone="danger" title={t('health.unreachable')}>
        {t('health.unreachableHint')}
      </Alert>
    );
  if (!isDefined(health)) return null;
  const setup = health.setup ?? [];
  const settingUp = setup.length > 0;

  return (
    <Stack gap="sm">
      {health.whisper === 'loading' && (
        <Alert tone="primary" title={t('health.whisperLoading')}>
          {t('health.whisperLoadingHint')}
        </Alert>
      )}
      {health.whisper === 'error' && (
        <Alert tone="danger">{t('health.whisperError', { detail: health.whisper_detail ?? '' })}</Alert>
      )}
      {settingUp && (
        <Alert tone={setup.some((step) => isDefined(step.error)) ? 'danger' : 'primary'} title={t('health.setupTitle')}>
          <Stack gap="sm">
            {setup.map((step) =>
              isDefined(step.error) ? (
                <Typography key={step.label} variant="error">
                  {t('health.setupFailed', { label: step.label, error: step.error })}
                </Typography>
              ) : (
                <ProgressBar
                  key={step.label}
                  label={
                    isDefined(step.progress)
                      ? t('health.setupProgress', { label: step.label, percent: Math.floor(step.progress * 100) })
                      : t('health.setupRunning', { label: step.label })
                  }
                  value={(step.progress ?? 1) * 100}
                  animated
                />
              ),
            )}
            <Typography variant="caption">{t('health.setupHint')}</Typography>
          </Stack>
        </Alert>
      )}
      {!settingUp && !health.ollama && <Alert tone="warning">{t('health.ollamaDown')}</Alert>}
      {!settingUp && health.ollama && !health.ollama_model_available && (
        <Alert tone="warning">{t('health.modelMissing', { model: health.ollama_model })}</Alert>
      )}
    </Stack>
  );
};

/** The main call to action: name the meeting, check its language, start recording */
const RecordForm = ({ preferences }: RecordFormProps) => {
  const { t } = useTranslation();
  const { data: devices } = useQuery(audioDevicesQueryOptions());
  const start = useMutation({
    mutationFn: (values: StartFormValues) =>
      startMeeting({
        title: values.title,
        mic_device: preferences.mic_device ?? null,
        remote_device: preferences.output_device ?? null,
        keep_audio: preferences.keep_audio ?? false,
        language: values.language,
      }),
    onSuccess: (meeting) => openMeeting(meeting.id),
  });
  const { Field, handleSubmit } = useForm({
    defaultValues: { title: '', language: (preferences.language ?? 'auto') as TranscriptionLanguage },
    onSubmit: ({ value }) => start.mutate(value),
  });
  const { open: openSettings } = useSettingsDialog();
  const openMeeting = useOpenMeeting();
  const none = t('sources.none');
  // Chosen device, or the one the applications use right now (automatic)
  const mic = describe(devices?.sources ?? [], preferences.mic_device ?? devices?.in_use_source, none);
  const output = describe(devices?.sinks ?? [], preferences.output_device ?? devices?.in_use_sink, none);
  const languageOptions = TRANSCRIPTION_LANGUAGES.map((code) => ({ value: code, label: t(`languages.${code}`) }));

  return (
    <Card padding="lg" highlighted>
      <Stack
        component="form"
        gap="lg"
        align="center"
        onSubmit={(event) => {
          event.preventDefault();
          handleSubmit();
        }}
      >
        <Stack gap="xs" align="center">
          <Typography variant="h2">{t('home.title')}</Typography>
          <Typography variant="lead">{t('home.lead')}</Typography>
        </Stack>
        <Stack direction="row" gap="md" align="flex-end" wrap="wrap" w="100%">
          <Field name="title">
            {(field) => (
              <TextField
                label={t('home.titleLabel')}
                placeholder={t('home.titlePlaceholder')}
                value={field.state.value}
                onChange={field.handleChange}
                grow
              />
            )}
          </Field>
          <Field name="language">
            {(field) => (
              <Select<TranscriptionLanguage>
                label={t('languages.label')}
                icon={IconLanguage}
                options={languageOptions}
                value={field.state.value}
                onChange={(value) => field.handleChange(value ?? 'auto')}
              />
            )}
          </Field>
        </Stack>
        <Button
          type="submit"
          size="md"
          radius="xl"
          variant="gradient"
          gradient={gradients.alert}
          icon={IconPlayerRecordFilled}
          label={start.isPending ? t('home.starting') : t('home.start')}
          loading={start.isPending}
        />
        <Stack direction="row" gap="xs" align="center" justify="center" wrap="wrap">
          <Typography variant="caption">{t('sources.summary', { mic, output })}</Typography>
          <Button variant="subtle" size="xs" icon={IconSettings} label={t('sources.edit')} onClick={openSettings} />
        </Stack>
        <Typography variant="caption">{t('home.startHint')}</Typography>
        {start.isError && (
          <Alert tone="danger" title={t('home.startError')}>
            {start.error.message}
          </Alert>
        )}
      </Stack>
    </Card>
  );
};

/** Recording panel: a meeting in progress to join, or the form to start one (once the settings are loaded) */
const RecordPanel = () => {
  const { t } = useTranslation();
  const { data: health } = useQuery(healthQueryOptions());
  const { data: preferences } = useQuery(preferencesQueryOptions());
  const openMeeting = useOpenMeeting();

  if (isDefined(health) && isDefined(health.active_meeting_id)) {
    const activeId = health.active_meeting_id;

    return (
      <Card padding="lg" highlighted>
        <Stack gap="md" align="center">
          <Badge tone="danger" variant="dot">
            {t('meeting.recording')}
          </Badge>
          <Typography variant="h2">{t('home.inProgress')}</Typography>
          <Button size="md" icon={IconMicrophone} label={t('home.join')} onClick={() => openMeeting(activeId)} />
        </Stack>
      </Card>
    );
  }

  return isDefined(preferences) ? <RecordForm preferences={preferences} /> : <Spinner label={t('common.loading')} />;
};

/** Transcribes a video or audio file: a replay, a webinar, a voice note */
const ImportPanel = () => {
  const { t } = useTranslation();
  const { data: health } = useQuery(healthQueryOptions());
  const upload = useMutation({
    mutationFn: ({ file, title, language }: ImportFormValues) =>
      isDefined(file) ? importMeeting({ file, title, language }) : Promise.reject(new Error(t('importFile.error'))),
    onSuccess: (meeting) => openMeeting(meeting.id),
  });
  const { Field, Subscribe, handleSubmit, setFieldValue } = useForm({
    defaultValues: IMPORT_DEFAULTS,
    onSubmit: ({ value }) => upload.mutate(value),
  });
  const openMeeting = useOpenMeeting();
  const busy = isDefined(health) && isDefined(health.active_meeting_id);

  return (
    <Card padding="md">
      <Stack gap="sm">
        <Stack direction="row" gap="sm" align="center" justify="space-between" wrap="wrap">
          <Stack gap="xxs" flex={1}>
            <Typography variant="subtitle1">{t('importFile.title')}</Typography>
            <Typography variant="description">{t('importFile.lead')}</Typography>
          </Stack>
          <Subscribe selector={(state) => state.values.file}>
            {(file) => (
              <FileButton
                label={isDefined(file) ? t('importFile.change') : t('importFile.choose')}
                icon={IconFileUpload}
                accept="video/*,audio/*"
                variant="light"
                disabled={busy}
                onChange={(picked) => {
                  setFieldValue('file', picked);
                  setFieldValue('title', format.fileTitle(picked.name));
                }}
              />
            )}
          </Subscribe>
        </Stack>
        <Subscribe selector={(state) => state.values.file}>
          {(file) =>
            isDefined(file) && (
              <Stack direction="row" gap="sm" align="flex-end" wrap="wrap">
                <Field name="title">
                  {(field) => (
                    <TextField
                      label={t('importFile.titleLabel')}
                      value={field.state.value}
                      onChange={field.handleChange}
                      grow
                    />
                  )}
                </Field>
                <Field name="language">
                  {(field) => (
                    <Select<TranscriptionLanguage>
                      label={t('languages.label')}
                      icon={IconLanguage}
                      options={TRANSCRIPTION_LANGUAGES.map((code) => ({ value: code, label: t(`languages.${code}`) }))}
                      value={field.state.value}
                      onChange={(value) => field.handleChange(value ?? 'auto')}
                    />
                  )}
                </Field>
                <Button
                  icon={IconSparkles}
                  label={upload.isPending ? t('importFile.sending') : t('importFile.submit', { name: file.name })}
                  loading={upload.isPending}
                  disabled={busy}
                  onClick={() => handleSubmit()}
                />
              </Stack>
            )
          }
        </Subscribe>
        {busy && <Typography variant="caption">{t('importFile.busy')}</Typography>}
        {upload.isError && (
          <Alert tone="danger" title={t('importFile.error')}>
            {upload.error.message}
          </Alert>
        )}
      </Stack>
    </Card>
  );
};

/** Home: server status, recording, file import and the history */
const Home = () => (
  <Stack gap="lg">
    <HealthStatus />
    <RecordPanel />
    <ImportPanel />
    <History />
  </Stack>
);

export default Home;
