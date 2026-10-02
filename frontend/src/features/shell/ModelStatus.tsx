import { Badge, Stack, Tooltip } from '@ign-junn/design-system';
import { useTranslation } from 'react-i18next';
import AiStatus from '@/components/AiStatus';
import useModelStatus from '@/hooks/useModelStatus';

/** Green, orange or red dots of the header: are the transcription model and the local AI running? */
const ModelStatus = () => {
  const { t } = useTranslation();
  const { transcription, ai, restartable, restarting, restart } = useModelStatus();

  return (
    <Stack direction="row" gap="xs" align="center">
      <Tooltip label={transcription.hint}>
        <Badge tone={transcription.tone} variant="dot" size="sm">
          {t('models.transcription')}
        </Badge>
      </Tooltip>
      <AiStatus ai={ai} restartable={restartable} restarting={restarting} onRestart={restart} />
    </Stack>
  );
};

export default ModelStatus;
