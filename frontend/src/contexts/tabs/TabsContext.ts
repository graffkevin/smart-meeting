import { createContext } from 'react';
import type { TabsState } from '@/types/components';

/** Meetings open as tabs, shared by the tab bar and the pages that open meetings */
const TabsContext = createContext<TabsState | null>(null);

export default TabsContext;
