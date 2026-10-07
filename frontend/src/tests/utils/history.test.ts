import { describe, expect, it } from 'vitest';
import type { MeetingListItem } from '@/api/generated/model/meetingListItem';
import byDate from '@/utils/history';

/** A meeting of the list started at a local date and time */
const meeting = (id: number, startedAt: string) => ({ id, started_at: startedAt }) as MeetingListItem;

describe('byDate', () => {
  const now = new Date('2026-10-15T15:00:00');

  it('splits the meetings by day, newest first: today, yesterday, then each day', () => {
    const groups = byDate(
      [
        meeting(1, '2026-10-15T09:00:00'),
        meeting(2, '2026-10-15T08:00:00'),
        meeting(3, '2026-10-14T18:00:00'),
        meeting(4, '2026-10-12T20:00:00'),
        meeting(5, '2026-10-12T10:00:00'),
        meeting(6, '2025-10-12T10:00:00'),
      ],
      now,
    );

    expect(groups.map((group) => [group.period, group.meetings.map(({ id }) => id)])).toEqual([
      ['today', [1, 2]],
      ['yesterday', [3]],
      ['day', [4, 5]],
      ['day', [6]],
    ]);
    expect(groups[3]?.day).toEqual(new Date(2025, 9, 12));
  });

  it('gives no group to an empty list', () => {
    expect(byDate([], now)).toEqual([]);
  });
});
