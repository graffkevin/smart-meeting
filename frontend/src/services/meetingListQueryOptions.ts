import { queryOptions } from '@tanstack/react-query';
import { listMeetings } from '@/api/generated/smartMeetingApi';

/** History, newest first; `search` matches titles, summaries and transcripts */
const meetingListQueryOptions = (search: string) =>
  queryOptions({
    queryKey: ['meetings', search],
    queryFn: ({ signal }) => listMeetings({ q: search }, { signal }),
  });

export default meetingListQueryOptions;
