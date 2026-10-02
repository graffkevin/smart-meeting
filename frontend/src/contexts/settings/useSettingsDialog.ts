import { isDefined } from '@ign-junn/design-system';
import { use } from 'react';
import SettingsDialogContext from '@/contexts/settings/SettingsDialogContext';

/** The settings window: `open()` from any button */
const useSettingsDialog = () => {
  const state = use(SettingsDialogContext);
  if (!isDefined(state)) throw new Error('useSettingsDialog outside SettingsDialogProvider');

  return state;
};

export default useSettingsDialog;
