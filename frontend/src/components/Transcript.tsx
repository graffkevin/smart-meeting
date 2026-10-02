import { Card, isDefined, ScrollArea, Stack, Typography } from '@ign-junn/design-system';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { TranscriptProps } from '@/types/components';
import format from '@/utils/format';

/**
 * Transcript as a conversation: my sentences on the right, highlighted; the other participants on the left. While
 * recording, the sentences being spoken follow in grey, word after word, until their final transcription.
 */
const Transcript = ({ segments, startedAt, live, partials = [], height }: TranscriptProps) => {
  const viewport = useRef<HTMLDivElement>(null);
  const { t, i18n } = useTranslation();
  const time = (offset: number) =>
    isDefined(startedAt) ? format.clock(startedAt, offset, i18n.language) : format.duration(offset);

  // Follows the conversation while recording (scrolls the panel, an external system)
  // biome-ignore lint/correctness/useExhaustiveDependencies: scrolls again on each new or growing sentence
  useEffect(() => {
    const element = viewport.current;
    if (live && isDefined(element)) element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
  }, [live, segments.length, partials]);

  if (segments.length === 0 && partials.length === 0)
    return <Typography variant="description">{live ? t('transcript.listening') : t('transcript.empty')}</Typography>;

  return (
    <ScrollArea h={height} viewportRef={viewport}>
      <Stack gap="sm" pr="sm">
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
        {partials.map((partial) => (
          <Stack key={partial.source} gap="xxs" align={partial.source === 'mic' ? 'flex-end' : 'flex-start'}>
            <Typography variant="caption">
              {partial.speaker} · {time(partial.start_s)}
            </Typography>
            <Card padding="sm">
              <Typography variant="description">{t('transcript.partial', { text: partial.text })}</Typography>
            </Card>
          </Stack>
        ))}
      </Stack>
    </ScrollArea>
  );
};

export default Transcript;
