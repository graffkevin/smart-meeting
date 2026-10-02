import { Badge, Box, Button, Stack, Tooltip } from '@ign-junn/design-system';
import { IconRefresh } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { AiStatusProps } from '@/types/components';

/** Status dot of the local AI (green, orange, red), and its restart button when it is not green */
const AiStatus = ({ ai, model, restartable, restarting, onRestart }: AiStatusProps) => {
  const { t } = useTranslation();

  return (
    <Stack direction="row" gap="xxs" align="center">
      {/* Box: the badge does not take the ref the tooltip needs */}
      <Tooltip label={ai.hint}>
        <Box component="span" display="inline-flex">
          <Badge tone={ai.tone} variant="dot" size="sm">
            {model === '' ? t('models.ai') : t('models.aiWithModel', { model })}
          </Badge>
        </Box>
      </Tooltip>
      {restartable && (
        <Button
          iconOnly
          icon={IconRefresh}
          label={t('models.restart')}
          variant="subtle"
          disabled={restarting}
          onClick={onRestart}
        />
      )}
    </Stack>
  );
};

export default AiStatus;
