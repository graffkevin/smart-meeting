import { queryOptions } from '@tanstack/react-query';
import { getUpdate } from '@/api/generated/smartMeetingApi';

/** Latest version published, read by the server every few hours */
const updateQueryOptions = () =>
  queryOptions({
    queryKey: ['update'],
    queryFn: ({ signal }) => getUpdate(undefined, { signal }),
    refetchInterval: 30 * 60 * 1000,
  });

export default updateQueryOptions;
