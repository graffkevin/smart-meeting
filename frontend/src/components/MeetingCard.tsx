import { Badge, Button, Card, isDefined, Stack, Typography } from '@ign-junn/design-system';
import { UnstyledButton } from '@mantine/core';
import { IconChecklist, IconClock, IconFileUpload, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { STATUS_TONES } from '@/constants/meeting';
import type { MeetingCardProps } from '@/types/components';
import format from '@/utils/format';

/** A meeting of the history: title, status, date, duration or file, number of actions, summary */
const MeetingCard = ({ meeting, onOpen, onDelete }: MeetingCardProps) => {
  const { t, i18n } = useTranslation();
  const { title, status, started_at, ended_at, source_file, action_count, summary } = meeting;
  const durationBadge = isDefined(ended_at) && (
    <Badge tone="muted" variant="outline" size="xs" icon={IconClock}>
      {format.duration(format.secondsBetween(started_at, ended_at))}
    </Badge>
  );

  return (
    <Card padding="md">
      <Stack direction="row" gap="md" align="flex-start">
        <UnstyledButton onClick={onOpen} flex={1} miw={0}>
          <Stack gap="xxs">
            <Stack direction="row" gap="xs" align="center" wrap="wrap">
              <Typography variant="subtitle1">{title}</Typography>
              <Badge tone={STATUS_TONES[status]} size="xs">
                {t(`status.${status}`)}
              </Badge>
            </Stack>
            <Stack direction="row" gap="xs" align="center" wrap="wrap">
              <Typography variant="caption">{format.date(started_at, i18n.language)}</Typography>
              {isDefined(source_file) ? (
                <Badge tone="muted" variant="outline" size="xs" icon={IconFileUpload}>
                  {source_file}
                </Badge>
              ) : (
                durationBadge
              )}
              {(action_count ?? 0) > 0 && (
                <Badge tone="primary" variant="outline" size="xs" icon={IconChecklist}>
                  {t('history.actions', { count: action_count ?? 0 })}
                </Badge>
              )}
            </Stack>
            {isDefined(summary) && (
              <Typography variant="body2" lineClamp={2}>
                {summary}
              </Typography>
            )}
          </Stack>
        </UnstyledButton>
        <Button
          iconOnly
          icon={IconTrash}
          label={t('history.delete', { title })}
          variant="subtle"
          color="red"
          disabled={status === 'recording'}
          onClick={onDelete}
        />
      </Stack>
    </Card>
  );
};

export default MeetingCard;
