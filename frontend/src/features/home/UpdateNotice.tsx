import { Alert, Button, isDefined, Stack, Typography } from '@ign-junn/design-system';
import { IconDownload, IconRefresh } from '@tabler/icons-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { applyUpdate } from '@/api/generated/smartMeetingApi';
import updateQueryOptions from '@/services/updateQueryOptions';

/** A newer version: installed in one click (clone, Linux package), or downloaded from its page */
const UpdateNotice = () => {
  const { t } = useTranslation();
  const { data: update } = useQuery(updateQueryOptions());
  // The server restarts on the new version; the page reloads itself once it answers again
  const install = useMutation({ mutationFn: () => applyUpdate() });

  if (!isDefined(update) || !update.available) return null;
  const restarting = install.isSuccess;

  return (
    <Alert tone="primary" title={t('update.available', { version: update.latest })}>
      <Stack gap="sm">
        <Typography variant="caption">
          {restarting ? t('update.restarting') : t('update.current', { version: update.current })}
        </Typography>
        {install.isError && <Typography variant="error">{install.error.message}</Typography>}
        <Stack direction="row" gap="sm">
          {update.method === 'download' ? (
            <Button
              icon={IconDownload}
              label={t('update.download')}
              onClick={() => window.open(update.url ?? undefined, '_blank', 'noopener')}
            />
          ) : (
            <Button
              icon={IconRefresh}
              label={t('update.install')}
              loading={install.isPending || restarting}
              onClick={() => install.mutate()}
            />
          )}
          {isDefined(update.url) && update.method !== 'download' && (
            <Button
              variant="subtle"
              label={t('update.notes')}
              onClick={() => window.open(update.url ?? undefined, '_blank', 'noopener')}
            />
          )}
        </Stack>
      </Stack>
    </Alert>
  );
};

export default UpdateNotice;
