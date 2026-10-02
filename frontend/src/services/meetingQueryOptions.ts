import { queryOptions } from '@tanstack/react-query';
import { getMeeting } from '@/api/generated/smartMeetingApi';

/** A meeting with its segments and analysis; kept current by the meeting WebSocket (useMeetingEvents) */
const meetingQueryOptions = (meetingId: number) =>
  queryOptions({
    queryKey: ['meeting', meetingId],
    queryFn: ({ signal }) => getMeeting(meetingId, { signal }),
  });

export default meetingQueryOptions;
