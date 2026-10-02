import { isDefined } from '@ign-junn/design-system';
import { use } from 'react';
import TabsContext from '@/contexts/tabs/TabsContext';

/** The meetings open as tabs */
const useTabs = () => {
  const state = use(TabsContext);
  if (!isDefined(state)) throw new Error('useTabs outside TabsProvider');

  return state;
};

export default useTabs;
