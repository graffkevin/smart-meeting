import {
  Badge,
  Box,
  Button,
  Card,
  ColorSchemeToggle,
  isDefined,
  Page,
  Stack,
  Typography,
} from '@ign-junn/design-system';
import { IconSettings, IconShieldLock } from '@tabler/icons-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Outlet, useMatch } from 'react-router';
import { ROUTES } from '@/constants/routes';
import SettingsDialogProvider from '@/contexts/settings/SettingsDialogProvider';
import useSettingsDialog from '@/contexts/settings/useSettingsDialog';
import TabsProvider from '@/contexts/tabs/TabsProvider';
import SettingsDialog from '@/features/settings/SettingsDialog';
import MeetingTabs from '@/features/shell/MeetingTabs';
import ModelStatus from '@/features/shell/ModelStatus';
import QuitButton from '@/features/shell/QuitButton';
import useServerPresence from '@/features/shell/useServerPresence';
import type { QuitState } from '@/types/meeting';

/** Opens the settings window */
const SettingsButton = () => {
  const { t } = useTranslation();
  const { open } = useSettingsDialog();

  return <Button iconOnly icon={IconSettings} label={t('settings.open')} variant="subtle" onClick={open} />;
};

/** Header (brand, local badge, models, settings, theme, quit) and the current page, or the stopped state once quit */
const Layout = () => {
  const [quitState, setQuitState] = useState<QuitState>('running');
  const { t } = useTranslation();
  // The meeting page has two columns (transcript panel on the right): a wider page
  const meetingPage = useMatch(ROUTES.meeting);
  useServerPresence();
  const stopping = quitState === 'quitting';

  return (
    <Box mih="100vh">
      {/* Fixed bar: header and tabs stay visible while the page scrolls */}
      <Box pos="sticky" top={0} bg="var(--mantine-color-body)" style={{ zIndex: 'var(--mantine-z-index-app)' }}>
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
          <ModelStatus />
          <SettingsButton />
          <ColorSchemeToggle labels={{ toLight: t('shell.toLight'), toDark: t('shell.toDark') }} />
          {quitState === 'running' && (
            <QuitButton onStopping={() => setQuitState('quitting')} onStopped={() => setQuitState('stopped')} />
          )}
        </Stack>
        {quitState === 'running' && (
          <Box px="lg">
            <MeetingTabs />
          </Box>
        )}
      </Box>
      <Page width={isDefined(meetingPage) ? 'wide' : 'medium'}>
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

const RootLayout = () => (
  <SettingsDialogProvider>
    <TabsProvider>
      <Layout />
      <SettingsDialog />
    </TabsProvider>
  </SettingsDialogProvider>
);

export default RootLayout;
