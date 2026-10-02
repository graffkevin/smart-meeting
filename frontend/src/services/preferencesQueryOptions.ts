import { queryOptions } from '@tanstack/react-query';
import { getPreferences } from '@/api/generated/smartMeetingApi';

/** Settings of the interface: my name, vocabulary, defaults of a new meeting (language, devices) */
const preferencesQueryOptions = () =>
  queryOptions({
    queryKey: ['preferences'],
    queryFn: ({ signal }) => getPreferences({ signal }),
  });

export default preferencesQueryOptions;
