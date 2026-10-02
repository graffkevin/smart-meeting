import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  CollapsibleSection,
  FileButton,
  isDefined,
  ProgressBar,
  Select,
  Stack,
  TextField,
  Typography,
} from '@ign-junn/design-system';
import {
  IconFileUpload,
  IconHeadphones,
  IconLanguage,
  IconMicrophone,
  IconPlayerRecordFilled,
  IconRefresh,
  IconSparkles,
} from '@tabler/icons-react';
import { useForm } from '@tanstack/react-form';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import type { AudioDevice } from '@/api/generated/model/audioDevice';
import { importMeeting, startMeeting } from '@/api/generated/smartMeetingApi';
import { AUTO_DEVICE, TRANSCRIPTION_LANGUAGES } from '@/constants/app';
import { meetingPath } from '@/constants/routes';
import History from '@/features/history/History';
import audioDevicesQueryOptions from '@/services/audioDevicesQueryOptions';
import healthQueryOptions from '@/services/healthQueryOptions';
import type { ImportFormValues, StartFormValues, TranscriptionLanguage } from '@/types/meeting';
import format from '@/utils/format';

const START_DEFAULTS: StartFormValues = {
  title: '',
  mic: AUTO_DEVICE,
  output: AUTO_DEVICE,
  keepAudio: false,
  language: 'auto',
};

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
      {!settingUp && health.ollama_model_available && health.whisper === 'ready' && (
        <Stack direction="row" gap="xs" wrap="wrap" justify="center">
          <Badge tone="muted" variant="dot" size="sm">
            {t('health.whisper', { detail: health.whisper_detail ?? '' })}
          </Badge>
          <Badge tone="muted" variant="dot" size="sm">
            {t('health.model', { model: health.ollama_model })}
          </Badge>
        </Stack>
      )}
    </Stack>
  );
};

/** The main call to action: name the meeting, choose its language and devices, start recording */
const RecordPanel = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { data: health } = useQuery(healthQueryOptions());
  const { data: devices, refetch: refreshDevices } = useQuery(audioDevicesQueryOptions());
  const start = useMutation({
    mutationFn: (values: StartFormValues) =>
      startMeeting({
        title: values.title,
        mic_device: values.mic === AUTO_DEVICE ? null : values.mic,
        remote_device: values.output === AUTO_DEVICE ? null : values.output,
        keep_audio: values.keepAudio,
        language: values.language,
      }),
    onSuccess: (meeting) => navigate(meetingPath(meeting.id)),
  });
  const { Field, handleSubmit } = useForm({
    defaultValues: START_DEFAULTS,
    onSubmit: ({ value }) => start.mutate(value),
  });
  const sources = devices?.sources ?? [];
  const sinks = devices?.sinks ?? [];
  const none = t('sources.none');
  const micInUse = describe(sources, devices?.in_use_source, none);
  const outputInUse = describe(sinks, devices?.in_use_sink, none);
  const languageOptions = TRANSCRIPTION_LANGUAGES.map((code) => ({ value: code, label: t(`languages.${code}`) }));
  const deviceOptions = (list: AudioDevice[], inUse: string) => [
    { value: AUTO_DEVICE, label: t('sources.auto', { device: inUse }) },
    ...list.map((device) => ({
      value: device.name,
      label: device.is_default ? t('sources.byDefault', { device: device.description }) : device.description,
    })),
  ];

  if (isDefined(health) && isDefined(health.active_meeting_id)) {
    const activeId = health.active_meeting_id;

    return (
      <Card padding="lg" highlighted>
        <Stack gap="md" align="center">
          <Badge tone="danger" variant="dot">
            {t('meeting.recording')}
          </Badge>
          <Typography variant="h2">{t('home.inProgress')}</Typography>
          <Button
            size="md"
            icon={IconMicrophone}
            label={t('home.join')}
            onClick={() => navigate(meetingPath(activeId))}
          />
        </Stack>
      </Card>
    );
  }

  return (
    <Stack gap="md">
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
          <Button
            type="submit"
            size="xl"
            radius="xl"
            color="red"
            icon={IconPlayerRecordFilled}
            label={start.isPending ? t('home.starting') : t('home.start')}
            loading={start.isPending}
          />
          <Typography variant="caption">{t('home.startHint')}</Typography>
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
          {start.isError && (
            <Alert tone="danger" title={t('home.startError')}>
              {start.error.message}
            </Alert>
          )}
        </Stack>
      </Card>

      <Card padding="md">
        <CollapsibleSection
          title={t('sources.title')}
          description={t('sources.summary', { mic: micInUse, output: outputInUse })}
        >
          <Stack gap="md" pt="sm">
            <Typography variant="description">{t('sources.help')}</Typography>
            <Typography variant="description">{t('languages.help')}</Typography>
            <Field name="mic">
              {(field) => (
                <Select
                  label={t('sources.mic')}
                  description={t('sources.micHelp')}
                  icon={IconMicrophone}
                  options={deviceOptions(sources, micInUse)}
                  value={field.state.value}
                  onChange={(value) => field.handleChange(value ?? AUTO_DEVICE)}
                />
              )}
            </Field>
            <Field name="output">
              {(field) => (
                <Select
                  label={t('sources.output')}
                  description={t('sources.outputHelp')}
                  icon={IconHeadphones}
                  options={deviceOptions(sinks, outputInUse)}
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
                  label={t('sources.keepAudio')}
                  description={t('sources.keepAudioHelp')}
                />
              )}
            </Field>
            <Stack direction="row">
              <Button
                variant="light"
                icon={IconRefresh}
                label={t('sources.refresh')}
                onClick={() => refreshDevices()}
              />
            </Stack>
          </Stack>
        </CollapsibleSection>
      </Card>
    </Stack>
  );
};

/** Transcribes a video or audio file: a replay, a webinar, a voice note */
const ImportPanel = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { data: health } = useQuery(healthQueryOptions());
  const upload = useMutation({
    mutationFn: ({ file, title, language }: ImportFormValues) =>
      isDefined(file) ? importMeeting({ file, title, language }) : Promise.reject(new Error(t('importFile.error'))),
    onSuccess: (meeting) => navigate(meetingPath(meeting.id)),
  });
  const { Field, Subscribe, handleSubmit, setFieldValue } = useForm({
    defaultValues: IMPORT_DEFAULTS,
    onSubmit: ({ value }) => upload.mutate(value),
  });
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
