import { Badge, Box, Button, Card, ColorSchemeToggle, Page, Stack, Typography } from '@ign-junn/design-system';
import { IconShieldLock } from '@tabler/icons-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Outlet } from 'react-router';
import { ROUTES } from '@/constants/routes';
import QuitButton from '@/features/shell/QuitButton';
import useServerPresence from '@/features/shell/useServerPresence';
import type { QuitState } from '@/types/meeting';

/** Header (brand, local badge, theme, quit) and the current page, or the stopped state once quit */
const RootLayout = () => {
  const [quitState, setQuitState] = useState<QuitState>('running');
  const { t } = useTranslation();
  useServerPresence();
  const stopping = quitState === 'quitting';

  return (
    <Box mih="100vh">
      <Stack component="header" direction="row" align="center" gap="sm" px="lg" py="sm">
        <Button
          component={Link}
          to={ROUTES.home}
          variant="subtle"
          size="md"
          label={
            <Stack direction="row" gap="xs" align="center">
              <Box component="img" src="/favicon.svg" alt="" w="xl" h="xl" />
              <Typography variant="brand">{t('app.name')}</Typography>
            </Stack>
          }
        />
        <Badge tone="success" icon={IconShieldLock} size="sm" title={t('shell.localHint')}>
          {t('shell.local')}
        </Badge>
        <Box flex={1} />
        <ColorSchemeToggle labels={{ toLight: t('shell.toLight'), toDark: t('shell.toDark') }} />
        {quitState === 'running' && (
          <QuitButton onStopping={() => setQuitState('quitting')} onStopped={() => setQuitState('stopped')} />
        )}
      </Stack>
      <Page width="medium">
        {quitState === 'running' ? (
          <Outlet />
        ) : (
          <Card padding="lg">
            <Stack gap="xs" align="center">
              <Typography variant="h5">{stopping ? t('shell.stopping') : t('shell.stopped')}</Typography>
              <Typography variant="description">
                {stopping ? t('shell.stoppingDetail') : t('shell.stoppedDetail')}
              </Typography>
            </Stack>
          </Card>
        )}
      </Page>
    </Box>
  );
};

export default RootLayout;
