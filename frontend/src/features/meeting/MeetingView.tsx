import {
  Alert,
  Badge,
  Button,
  Card,
  CopyButton,
  EditableText,
  isDefined,
  ProgressBar,
  Spinner,
  Stack,
  Typography,
} from '@ign-junn/design-system';
import { useInterval } from '@mantine/hooks';
import {
  IconArrowLeft,
  IconFileUpload,
  IconLanguage,
  IconPlayerStopFilled,
  IconSparkles,
  IconTrash,
  IconVolumeOff,
} from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';
import type { CapturedDevice } from '@/api/generated/model/capturedDevice';
import {
  analyzeMeeting,
  deleteAudio,
  deleteMeeting,
  stopMeeting,
  updateMeeting,
} from '@/api/generated/smartMeetingApi';
import ConfirmDialog from '@/components/ConfirmDialog';
import MeetingReport from '@/components/MeetingReport';
import Transcript from '@/components/Transcript';
import { LEVEL_FLOOR_DB } from '@/constants/app';
import { LIVE_STATUSES, STATUS_TONES } from '@/constants/meeting';
import { ROUTES } from '@/constants/routes';
import useMeetingEvents from '@/features/meeting/useMeetingEvents';
import audioDevicesQueryOptions from '@/services/audioDevicesQueryOptions';
import meetingQueryOptions from '@/services/meetingQueryOptions';
import meetingReportQueryOptions from '@/services/meetingReportQueryOptions';
import type { LivePanelProps, MeetingViewProps } from '@/types/components';
import format from '@/utils/format';

/** Duration, audio levels and captured devices of a meeting being recorded, and its stop button */
const LivePanel = ({ startedAt, live, captured, onStop, stopping }: LivePanelProps) => {
  const [now, setNow] = useState(Date.now());
  const { t } = useTranslation();
  const { data: devices } = useQuery(audioDevicesQueryOptions());
  useInterval(() => setNow(Date.now()), 1000, { autoInvoke: true });
  const known = [...(devices?.sources ?? []), ...(devices?.sinks ?? [])];
  const deviceLabel = (name: string, auto: boolean) => {
    const description = known.find((device) => device.name === name)?.description ?? name;

    return auto ? t('meeting.automatic', { device: description }) : description;
  };
  const device = (source?: CapturedDevice) =>
    isDefined(source) && isDefined(source.device)
      ? deviceLabel(source.device, source.auto)
      : t('meeting.systemDefault');

  return (
    <Stack gap="md" align="center">
      <Badge tone="danger" variant="dot">
        {t('meeting.recording')}
      </Badge>
      <Typography variant="display">{format.duration((now - new Date(startedAt).getTime()) / 1000)}</Typography>
      {isDefined(live.levels) && (
        <Stack direction="row" gap="lg" w="100%">
          <Stack flex={1}>
            <ProgressBar label={t('meeting.me')} value={format.level(live.levels.mic, LEVEL_FLOOR_DB)} />
          </Stack>
          <Stack flex={1}>
            <ProgressBar
              label={t('meeting.others')}
              value={format.level(live.levels.remote, LEVEL_FLOOR_DB)}
              tone="accent"
            />
          </Stack>
        </Stack>
      )}
      <Button
        size="lg"
        radius="xl"
        color="red"
        icon={IconPlayerStopFilled}
        label={t('meeting.stop')}
        loading={stopping}
        onClick={onStop}
      />
      {live.queue > 0 && <Typography variant="caption">{t('meeting.queue', { count: live.queue })}</Typography>}
      {isDefined(captured) && (
        <Typography variant="caption">
          {t('meeting.capture', { mic: device(captured.mic), output: device(captured.remote) })}
        </Typography>
      )}
      {isDefined(captured) && isDefined(captured.mic) && isDefined(captured.mic.error) && (
        <Alert tone="warning">{t('meeting.micError', { error: captured.mic.error })}</Alert>
      )}
      {isDefined(captured) && isDefined(captured.remote) && isDefined(captured.remote.error) && (
        <Alert tone="warning">{t('meeting.remoteError', { error: captured.remote.error })}</Alert>
      )}
    </Stack>
  );
};

/** A meeting: live recording, then its report, actions on it and its transcript */
const MeetingView = ({ meetingId }: MeetingViewProps) => {
  const [deleting, setDeleting] = useState(false);
  const navigate = useNavigate();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: detail, error } = useQuery(meetingQueryOptions(meetingId));
  const { data: report } = useQuery({
    ...meetingReportQueryOptions(meetingId),
    enabled: isDefined(detail) && !LIVE_STATUSES.includes(detail.meeting.status),
  });
  // Every change reloads the meeting (status, title, audio)
  const stop = useMutation({
    mutationFn: () => stopMeeting(meetingId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] }),
  });
  const analyze = useMutation({
    mutationFn: () => analyzeMeeting(meetingId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] }),
  });
  const rename = useMutation({
    mutationFn: (title: string) => updateMeeting(meetingId, { title }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] }),
  });
  const removeAudio = useMutation({
    mutationFn: () => deleteAudio(meetingId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] }),
  });
  const removal = useMutation({
    mutationFn: () => deleteMeeting(meetingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meetings'] });
      navigate(ROUTES.home);
    },
  });
  const live = useMeetingEvents(meetingId);

  if (!isDefined(detail))
    return isDefined(error) ? <Alert tone="danger">{error.message}</Alert> : <Spinner label={t('common.loading')} />;
  const { meeting, segments, analysis, has_audio, captured } = detail;
  const { status } = meeting;
  const recording = status === 'recording';
  const finished = status === 'transcribed' || status === 'done';
  const progress = live.progress;
  const errors = [meeting.error, stop.error?.message, analyze.error?.message].filter(isDefined);

  return (
    <Stack gap="lg">
      <Stack direction="row">
        <Button component={Link} to={ROUTES.home} variant="subtle" icon={IconArrowLeft} label={t('meeting.back')} />
      </Stack>

      <Card padding="lg" highlighted={recording}>
        <Stack gap="md">
          <Stack direction="row" gap="sm" align="center" justify="space-between" wrap="wrap">
            <EditableText
              value={meeting.title}
              onChange={(title) => rename.mutate(title)}
              label={t('meeting.rename')}
              variant="h2"
            />
            <Stack direction="row" gap="xs" align="center">
              {meeting.language !== 'auto' && isDefined(meeting.language) && (
                <Badge tone="muted" variant="outline" icon={IconLanguage}>
                  {meeting.language.toUpperCase()}
                </Badge>
              )}
              {!recording && <Badge tone={STATUS_TONES[status]}>{t(`status.${status}`)}</Badge>}
            </Stack>
          </Stack>
          {isDefined(meeting.source_file) && (
            <Badge tone="muted" variant="outline" icon={IconFileUpload}>
              {t('meeting.importedFrom', { file: meeting.source_file })}
            </Badge>
          )}

          {recording && (
            <LivePanel
              startedAt={meeting.started_at}
              live={live}
              captured={live.devices ?? captured ?? null}
              onStop={() => stop.mutate()}
              stopping={stop.isPending}
            />
          )}
          {status === 'transcribing' && isDefined(progress) && (
            <ProgressBar
              label={`${t('meeting.importing')} · ${format.duration(progress.done)}${isDefined(progress.total) ? ` / ${format.duration(progress.total)}` : ''}`}
              value={isDefined(progress.total) ? (progress.done / progress.total) * 100 : 100}
              animated
            />
          )}
          {status === 'transcribing' && !isDefined(progress) && (
            <Alert tone="primary">{t('meeting.transcribing')}</Alert>
          )}
          {status === 'analyzing' && (
            <Alert tone="primary" title={t('meeting.analyzing')}>
              {t('meeting.analyzingHint')}
            </Alert>
          )}
          {errors.map((message) => (
            <Alert key={message} tone="warning">
              {message}
            </Alert>
          ))}

          {finished && (
            <Stack direction="row" gap="sm" wrap="wrap">
              {isDefined(report) && (
                <CopyButton
                  value={report}
                  variant="button"
                  labels={{ copy: t('meeting.copy'), copied: t('meeting.copied') }}
                />
              )}
              {segments.length > 0 && (
                <Button
                  variant="light"
                  icon={IconSparkles}
                  label={isDefined(analysis) ? t('meeting.reanalyze') : t('meeting.analyze')}
                  loading={analyze.isPending}
                  onClick={() => analyze.mutate()}
                />
              )}
              {has_audio && (
                <Button
                  variant="subtle"
                  icon={IconVolumeOff}
                  label={t('meeting.deleteAudio')}
                  onClick={() => removeAudio.mutate()}
                />
              )}
              <Button
                variant="subtle"
                color="red"
                icon={IconTrash}
                label={t('meeting.delete')}
                onClick={() => setDeleting(true)}
              />
            </Stack>
          )}
        </Stack>
      </Card>

      {isDefined(analysis) && <MeetingReport analysis={analysis} />}

      <Card padding="lg">
        <Stack gap="md">
          <Typography variant="h5">{t('transcript.title')}</Typography>
          <Transcript
            segments={segments}
            startedAt={isDefined(meeting.source_file) ? null : meeting.started_at}
            live={recording}
          />
        </Stack>
      </Card>

      <ConfirmDialog
        opened={deleting}
        title={t('deletion.title')}
        text={t('deletion.text', { title: meeting.title })}
        confirmLabel={t('deletion.confirm')}
        loading={removal.isPending}
        onConfirm={() => removal.mutate()}
        onClose={() => setDeleting(false)}
      />
    </Stack>
  );
};

export default MeetingView;
