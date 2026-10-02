import { createContext } from 'react';
import type { SettingsDialogState } from '@/types/components';

/** State of the settings window, shared by the header and the pages */
const SettingsDialogContext = createContext<SettingsDialogState | null>(null);

export default SettingsDialogContext;
