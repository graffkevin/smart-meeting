import { queryOptions } from '@tanstack/react-query';
import { listMeetings } from '@/api/generated/smartMeetingApi';
import { LIVE_STATUSES } from '@/constants/meeting';

/** While a meeting of the list records, transcribes or is analyzed, its status is checked this often */
const LIVE_REFRESH_MS = 5000;

/**
 * History, newest first; `search` matches titles, summaries and transcripts. Refreshed while a meeting in it is in
 * progress, even when its page is not open (an analysis ending while the home page is shown).
 */
const meetingListQueryOptions = (search: string) =>
  queryOptions({
    queryKey: ['meetings', search],
    queryFn: ({ signal }) => listMeetings({ q: search }, { signal }),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((meeting) => LIVE_STATUSES.includes(meeting.status)) ? LIVE_REFRESH_MS : false,
  });

export default meetingListQueryOptions;
