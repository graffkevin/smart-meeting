import { Box, Card, isDefined, Stack, Typography } from '@ign-junn/design-system';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { TranscriptProps } from '@/types/components';
import format from '@/utils/format';

/** Transcript as a conversation: my sentences on the right, highlighted; the other participants on the left */
const Transcript = ({ segments, startedAt, live }: TranscriptProps) => {
  const end = useRef<HTMLDivElement>(null);
  const { t, i18n } = useTranslation();
  const time = (offset: number) =>
    isDefined(startedAt) ? format.clock(startedAt, offset, i18n.language) : format.duration(offset);

  // Follows the conversation while recording (scrolls the page, an external system)
  // biome-ignore lint/correctness/useExhaustiveDependencies: scrolls again on each new sentence
  useEffect(() => {
    if (live) end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [live, segments.length]);

  if (segments.length === 0)
    return <Typography variant="description">{live ? t('transcript.listening') : t('transcript.empty')}</Typography>;

  return (
    <Stack gap="sm">
      {segments.map((segment) => {
        const mine = segment.source === 'mic';

        return (
          <Stack key={segment.id ?? segment.start_s} gap="xxs" align={mine ? 'flex-end' : 'flex-start'}>
            <Typography variant="caption">
              {segment.speaker} · {time(segment.start_s)}
            </Typography>
            <Card padding="sm" highlighted={mine}>
              <Typography variant="body1">{segment.text}</Typography>
            </Card>
          </Stack>
        );
      })}
      <Box ref={end} />
    </Stack>
  );
};

export default Transcript;
