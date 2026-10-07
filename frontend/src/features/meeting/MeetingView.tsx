import {
  Alert,
  Autocomplete,
  Badge,
  Box,
  Button,
  Card,
  CopyButton,
  EditableText,
  isDefined,
  ProgressBar,
  Spinner,
  Stack,
  TextField,
  Typography,
} from '@ign-junn/design-system';
import { Grid } from '@mantine/core';
import { useInterval } from '@mantine/hooks';
import {
  IconArrowLeft,
  IconChecklist,
  IconFileUpload,
  IconGavel,
  IconLanguage,
  IconListDetails,
  IconPlayerStopFilled,
  IconSend,
  IconSparkles,
  IconTrash,
  IconVolumeOff,
} from '@tabler/icons-react';
import { useForm } from '@tanstack/react-form';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';
import type { AskAnswer } from '@/api/generated/model/askAnswer';
import type { CapturedDevice } from '@/api/generated/model/capturedDevice';
import {
  analyzeMeeting,
  askMeeting,
  deleteAudio,
  deleteMeeting,
  renameSpeaker,
  setMeetingTags,
  stopMeeting,
  updateMeeting,
} from '@/api/generated/smartMeetingApi';
import AiStatus from '@/components/AiStatus';
import ConfirmDialog from '@/components/ConfirmDialog';
import EstimatedProgress from '@/components/EstimatedProgress';
import MeetingReport from '@/components/MeetingReport';
import Transcript from '@/components/Transcript';
import { DEFAULT_ESTIMATE_S, LEVEL_FLOOR_DB } from '@/constants/app';
import {
  FIXED_BAR_HEIGHT,
  LIVE_STATUSES,
  QUICK_QUESTIONS,
  STATUS_TONES,
  TRANSCRIPT_PANEL_HEIGHT,
} from '@/constants/meeting';
import { ROUTES } from '@/constants/routes';
import useMeetingEvents from '@/features/meeting/useMeetingEvents';
import useModelStatus from '@/hooks/useModelStatus';
import audioDevicesQueryOptions from '@/services/audioDevicesQueryOptions';
import meetingQueryOptions from '@/services/meetingQueryOptions';
import meetingReportQueryOptions from '@/services/meetingReportQueryOptions';
import recentQuestionsQueryOptions from '@/services/recentQuestionsQueryOptions';
import tagsQueryOptions from '@/services/tagsQueryOptions';
import type { AskPanelProps, LivePanelProps, MeetingViewProps } from '@/types/components';
import type { AnswerEntry } from '@/types/meeting';
import format from '@/utils/format';

/** An answer of the local AI, with stable keys for its lines (empty lines dropped) */
const toEntry = ({ id: savedId, question, answer }: AskAnswer): AnswerEntry => {
  const id = String(savedId ?? question);

  return {
    id,
    question,
    lines: answer
      .split('\n')
      .filter((text) => text.trim() !== '')
      .map((text, position) => ({ key: `${id}-${position}`, text })),
  };
};

/** Icons of the one-click questions */
const QUICK_ICONS = {
  summary: IconListDetails,
  myActions: IconChecklist,
  decisions: IconGavel,
} as const;

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

/**
 * Questions about the meeting, answered by the local AI from the transcript, during or after the meeting: one-click
 * questions (summary, my actions, decisions) or a free question; the answers follow, newest last.
 */
const AskPanel = ({ meetingId, disabled, estimateS, questions }: AskPanelProps) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: recent } = useQuery(recentQuestionsQueryOptions());
  // Answers are kept with the meeting: reload it, and the suggestions
  const ask = useMutation({
    mutationFn: (question: string) => askMeeting(meetingId, { question }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: meetingQueryOptions(meetingId).queryKey }),
        queryClient.invalidateQueries({ queryKey: recentQuestionsQueryOptions().queryKey }),
      ]),
  });
  const { Field, handleSubmit, reset } = useForm({
    defaultValues: { question: '' },
    onSubmit: ({ value }) => {
      if (value.question.trim() === '') return;
      ask.mutate(value.question);
      reset();
    },
  });
  const { ai, model, restartable, restarting, restart } = useModelStatus();
  // Asking needs something transcribed and the local AI answering (green)
  const unavailable = disabled || ai.tone !== 'success' || ask.isPending;
  const answers = questions.map(toEntry);

  return (
    <Card padding="lg">
      <Stack gap="md">
        <Stack direction="row" gap="sm" align="flex-start" justify="space-between">
          <Stack gap="xxs" flex={1}>
            <Typography variant="h5">{t('ask.title')}</Typography>
            <Typography variant="description">{disabled ? t('ask.empty') : t('ask.lead')}</Typography>
          </Stack>
          <AiStatus ai={ai} model={model} restartable={restartable} restarting={restarting} onRestart={restart} />
        </Stack>
        <Stack direction="row" gap="xs" wrap="wrap">
          {QUICK_QUESTIONS.map((key) => (
            <Button
              key={key}
              variant="light"
              icon={QUICK_ICONS[key]}
              label={t(`ask.quick.${key}`)}
              disabled={unavailable}
              onClick={() => ask.mutate(t(`ask.quickQuestions.${key}`))}
            />
          ))}
        </Stack>
        <Stack
          component="form"
          direction="row"
          gap="sm"
          align="flex-end"
          onSubmit={(event) => {
            event.preventDefault();
            handleSubmit();
          }}
        >
          <Field name="question">
            {(field) => (
              <Autocomplete
                label={t('ask.label')}
                placeholder={t('ask.placeholder')}
                value={field.state.value}
                onChange={field.handleChange}
                suggestions={recent ?? []}
                disabled={disabled}
                grow
              />
            )}
          </Field>
          <Button type="submit" icon={IconSend} label={t('ask.submit')} disabled={unavailable} />
        </Stack>
        {answers.map((answer) => (
          <Card key={answer.id} padding="md" highlighted>
            <Stack gap="xs">
              <Typography variant="subtitle2">{answer.question}</Typography>
              {answer.lines.map((line) => (
                <Typography key={line.key} variant="body1">
                  {line.text}
                </Typography>
              ))}
            </Stack>
          </Card>
        ))}
        {ask.isPending && (
          <Card padding="md">
            <Stack gap="xs">
              <Typography variant="subtitle2">{ask.variables}</Typography>
              <EstimatedProgress label={t('ask.thinking')} estimateS={estimateS} startedAt={ask.submittedAt} />
            </Stack>
          </Card>
        )}
        {ask.isError && <Alert tone="warning">{t('ask.error', { error: ask.error.message })}</Alert>}
      </Stack>
    </Card>
  );
};

/** A meeting: live recording, questions to the AI and its report on the left; the live transcript on the right */
const MeetingView = ({ meetingId }: MeetingViewProps) => {
  const [deleting, setDeleting] = useState(false);
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { data: detail, error, dataUpdatedAt } = useQuery(meetingQueryOptions(meetingId));
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
  const nameSpeaker = useMutation({
    mutationFn: ({ old, name }: { old: string; name: string }) => renameSpeaker(meetingId, { old, new: name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] }),
  });
  const removeAudio = useMutation({
    mutationFn: () => deleteAudio(meetingId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] }),
  });
  // Tags group the history: the list and the suggestions change with them
  const retag = useMutation({
    mutationFn: (tags: string[]) => setMeetingTags(meetingId, { tags }),
    onSuccess: () =>
      Promise.all(
        [['meeting', meetingId], ['meetings'], tagsQueryOptions().queryKey].map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
      ),
  });
  const { data: knownTags } = useQuery(tagsQueryOptions());
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

      <Grid gap="lg">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Stack gap="lg">
            <Card padding="lg" highlighted={recording}>
              <Stack gap="md">
                <Stack direction="row" gap="sm" align="center" justify="space-between" wrap="wrap">
                  <Stack direction="row" gap="md" align="center" wrap="wrap" flex={1}>
                    <EditableText
                      value={meeting.title}
                      onChange={(title) => rename.mutate(title)}
                      label={t('meeting.rename')}
                      variant="h2"
                    />
                    <TextField
                      type="tags"
                      label={t('tags.label')}
                      hideLabel
                      placeholder={t('tags.placeholder')}
                      value={meeting.tags ?? []}
                      onChange={(tags) => retag.mutate(tags)}
                      suggestions={(knownTags ?? []).map((tag) => tag.name)}
                      grow
                    />
                  </Stack>
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
                  <EstimatedProgress
                    label={t('meeting.analyzing')}
                    estimateS={detail.estimates?.analysis_s ?? DEFAULT_ESTIMATE_S}
                    startedAt={dataUpdatedAt - (detail.analysis_elapsed_s ?? 0) * 1000}
                  />
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

            <AskPanel
              meetingId={meetingId}
              disabled={segments.length === 0}
              estimateS={detail.estimates?.ask_s ?? DEFAULT_ESTIMATE_S}
              questions={detail.questions ?? []}
            />

            {isDefined(analysis) && <MeetingReport analysis={analysis} />}
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 5 }}>
          {/* Transcript panel: stays in view while the page scrolls, scrolls inside */}
          <Box pos="sticky" top={FIXED_BAR_HEIGHT}>
            <Card padding="md">
              <Stack gap="sm">
                <Stack direction="row" align="center" justify="space-between">
                  <Typography variant="h5">{t('transcript.title')}</Typography>
                  {segments.length > 0 && (
                    <CopyButton
                      value={format.transcript(segments, (offset) =>
                        isDefined(meeting.source_file)
                          ? format.duration(offset)
                          : format.clock(meeting.started_at, offset, i18n.language),
                      )}
                      labels={{ copy: t('transcript.copy'), copied: t('transcript.copied') }}
                    />
                  )}
                </Stack>
                <Transcript
                  segments={segments}
                  startedAt={isDefined(meeting.source_file) ? null : meeting.started_at}
                  live={recording}
                  partials={recording ? Object.values(live.partials).filter(isDefined) : []}
                  height={TRANSCRIPT_PANEL_HEIGHT}
                  onRenameSpeaker={(old, name) => nameSpeaker.mutate({ old, name })}
                />
              </Stack>
            </Card>
          </Box>
        </Grid.Col>
      </Grid>

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
