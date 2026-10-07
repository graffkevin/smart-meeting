import { isDefined } from '@ign-junn/design-system';
import type { MeetingListItem } from '@/api/generated/model/meetingListItem';
import type { DateGroup, HistoryPeriod } from '@/types/meeting';

const DAY_MS = 24 * 60 * 60 * 1000;

/** Midnight of a date, local time */
const dayStart = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());

/** Period of a meeting started at `start`, seen on `now`: today, yesterday, or an earlier day */
const periodOf = (start: Date, now: Date): HistoryPeriod => {
  const days = Math.round((dayStart(now).getTime() - dayStart(start).getTime()) / DAY_MS);

  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';

  return 'day';
};

/** Groups of meetings by day, in the order of the list (newest first) */
const byDate = (meetings: MeetingListItem[], now = new Date()): DateGroup[] =>
  meetings.reduce<DateGroup[]>((groups, meeting) => {
    const start = new Date(meeting.started_at);
    const day = dayStart(start);
    const key = day.toDateString();
    const group = groups.find((candidate) => candidate.key === key);
    if (isDefined(group)) group.meetings.push(meeting);
    else groups.push({ key, period: periodOf(start, now), day, meetings: [meeting] });

    return groups;
  }, []);

export default byDate;
