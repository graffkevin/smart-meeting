import { Button, isDefined } from '@ign-junn/design-system';
import { IconPower } from '@tabler/icons-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { shutdown } from '@/api/generated/smartMeetingApi';
import ConfirmDialog from '@/components/ConfirmDialog';
import healthQueryOptions from '@/services/healthQueryOptions';
import type { QuitButtonProps } from '@/types/components';

/** Quits the app (server and local AI); a meeting being recorded is stopped and its transcription finished first */
const QuitButton = ({ onStopping, onStopped }: QuitButtonProps) => {
  const [opened, setOpened] = useState(false);
  const { t } = useTranslation();
  const { data: health } = useQuery(healthQueryOptions());
  const { mutate } = useMutation({ mutationFn: () => shutdown(), onSettled: onStopped });
  const recording = isDefined(health) && isDefined(health.active_meeting_id);
  const quit = () => {
    setOpened(false);
    onStopping();
    mutate();
  };

  return (
    <>
      <Button iconOnly icon={IconPower} label={t('shell.quit')} variant="subtle" onClick={() => setOpened(true)} />
      <ConfirmDialog
        opened={opened}
        title={t('shell.quitTitle')}
        text={recording ? t('shell.quitRecording') : t('shell.quitText')}
        confirmLabel={t('shell.quitConfirm')}
        onConfirm={quit}
        onClose={() => setOpened(false)}
      />
    </>
  );
};

export default QuitButton;
