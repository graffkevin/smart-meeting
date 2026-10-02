import { Button, Dialog, Stack, Typography } from '@ign-junn/design-system';
import { useTranslation } from 'react-i18next';
import type { ConfirmDialogProps } from '@/types/components';

/** Asks before an action that cannot be undone (delete, quit) */
const ConfirmDialog = ({ opened, title, text, confirmLabel, onConfirm, onClose, loading }: ConfirmDialogProps) => {
  const { t } = useTranslation();

  return (
    <Dialog opened={opened} onClose={onClose} title={title} closeLabel={t('common.close')} size="sm">
      <Stack gap="lg">
        <Typography variant="body1">{text}</Typography>
        <Stack direction="row" gap="sm" justify="flex-end">
          <Button variant="default" label={t('common.cancel')} onClick={onClose} />
          <Button color="red" label={confirmLabel} loading={loading} onClick={onConfirm} />
        </Stack>
      </Stack>
    </Dialog>
  );
};

export default ConfirmDialog;
