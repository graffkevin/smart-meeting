import { queryOptions } from '@tanstack/react-query';
import { health } from '@/api/generated/smartMeetingApi';
import { HEALTH_POLL_MS } from '@/constants/app';

/** Server status, polled: transcription model, local AI and its first-run installs, active meeting */
const healthQueryOptions = () =>
  queryOptions({
    queryKey: ['health'],
    queryFn: ({ signal }) => health({ signal }),
    refetchInterval: HEALTH_POLL_MS,
  });

export default healthQueryOptions;
