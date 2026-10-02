import { isFiniteNumber } from '@ign-junn/design-system';
import { useState } from 'react';
import { TABS_STORAGE_KEY } from '@/constants/app';
import TabsContext from '@/contexts/tabs/TabsContext';
import type { TabsProviderProps } from '@/types/components';

/** Tabs saved by this browser; storage can be unavailable (private mode, blocked site data) */
const storedTabs = (): number[] => {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(TABS_STORAGE_KEY) ?? '[]');

    return Array.isArray(value) ? value.filter(isFiniteNumber) : [];
  } catch {
    return [];
  }
};

/** Saves the tabs and returns them (for a state update) */
const storeTabs = (ids: number[]) => {
  try {
    localStorage.setItem(TABS_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Storage unavailable: the tabs simply are not remembered
  }

  return ids;
};

/** Provides the meetings open as tabs, remembered between sessions */
const TabsProvider = ({ children }: TabsProviderProps) => {
  const [ids, setIds] = useState(storedTabs);
  const state = {
    ids,
    add: (meetingId: number) =>
      setIds((current) => storeTabs(current.includes(meetingId) ? current : [...current, meetingId])),
    remove: (meetingId: number) => setIds((current) => storeTabs(current.filter((id) => id !== meetingId))),
  };

  return <TabsContext value={state}>{children}</TabsContext>;
};

export default TabsProvider;
