import { queryOptions } from '@tanstack/react-query';
import { meetingReport } from '@/api/generated/smartMeetingApi';

/** Markdown report of a meeting (copied to the clipboard); under the meeting key, refreshed with it */
const meetingReportQueryOptions = (meetingId: number) =>
  queryOptions({
    queryKey: ['meeting', meetingId, 'report'],
    queryFn: ({ signal }) => meetingReport(meetingId, { signal }),
  });

export default meetingReportQueryOptions;
