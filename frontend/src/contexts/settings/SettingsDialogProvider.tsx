import { useState } from 'react';
import SettingsDialogContext from '@/contexts/settings/SettingsDialogContext';
import type { SettingsDialogProviderProps } from '@/types/components';

/** Provides the open state of the settings window */
const SettingsDialogProvider = ({ children }: SettingsDialogProviderProps) => {
  const [opened, setOpened] = useState(false);
  const state = { opened, open: () => setOpened(true), close: () => setOpened(false) };

  return <SettingsDialogContext value={state}>{children}</SettingsDialogContext>;
};

export default SettingsDialogProvider;
