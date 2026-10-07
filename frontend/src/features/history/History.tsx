import {
  Card,
  CollapsibleSection,
  Divider,
  isDefined,
  SegmentedSwitch,
  Stack,
  TextField,
  Typography,
} from '@ign-junn/design-system';
import { useDebouncedValue } from '@mantine/hooks';
import { IconSearch } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMatch } from 'react-router';
import type { MeetingListItem } from '@/api/generated/model/meetingListItem';
import { deleteMeeting } from '@/api/generated/smartMeetingApi';
import ConfirmDialog from '@/components/ConfirmDialog';
import MeetingCard from '@/components/MeetingCard';
import { SEARCH_DEBOUNCE_MS } from '@/constants/app';
import { ROUTES } from '@/constants/routes';
import useOpenMeeting from '@/hooks/useOpenMeeting';
import meetingListQueryOptions from '@/services/meetingListQueryOptions';
import type { DateGroup, HistoryView, TagGroup } from '@/types/meeting';
import format from '@/utils/format';
import byDate from '@/utils/history';

/** Groups of meetings by tag, alphabetically, meetings without tag last */
const byTag = (meetings: MeetingListItem[], untagged: string): TagGroup[] => {
  const tags = [...new Set(meetings.flatMap((meeting) => meeting.tags ?? []))].toSorted((a, b) => a.localeCompare(b));
  const groups = tags.map((tag) => ({ tag, meetings: meetings.filter((meeting) => meeting.tags?.includes(tag)) }));
  const without = meetings.filter((meeting) => (meeting.tags ?? []).length === 0);

  return without.length > 0 ? [...groups, { tag: untagged, meetings: without }] : groups;
};

/** History of the meetings (the content of the side panel), by day with a divider each, or grouped by tag; searchable
 * in titles, tags, summaries and transcripts; the meeting on screen is outlined */
const History = () => {
  const [search, setSearch] = useState('');
  const [view, setView] = useState<HistoryView>('byDate');
  const [toDelete, setToDelete] = useState<MeetingListItem | null>(null);
  const { t, i18n } = useTranslation();
  const shown = useMatch(ROUTES.meeting);
  const [debouncedSearch] = useDebouncedValue(search, SEARCH_DEBOUNCE_MS);
  const queryClient = useQueryClient();
  const { data: meetings, error } = useQuery(meetingListQueryOptions(debouncedSearch));
  const removal = useMutation({
    mutationFn: (meetingId: number) => deleteMeeting(meetingId),
    onSuccess: () => {
      setToDelete(null);
      queryClient.invalidateQueries({ queryKey: ['meetings'] });
    },
  });
  const openMeeting = useOpenMeeting();
  const emptyText = search === '' ? t('history.empty') : t('history.noResult', { query: search });
  const dayLabel = ({ period, day }: DateGroup) =>
    period === 'day'
      ? format.day(day, i18n.language, day.getFullYear() !== new Date().getFullYear())
      : t(`history.periods.${period}`);
  const card = (meeting: MeetingListItem) => (
    <MeetingCard
      key={meeting.id}
      meeting={meeting}
      active={shown?.params.meetingId === String(meeting.id)}
      onOpen={() => openMeeting(meeting.id)}
      onDelete={() => setToDelete(meeting)}
    />
  );

  return (
    <Stack gap="sm">
      <TextField
        type="search"
        icon={IconSearch}
        label={t('history.search')}
        hideLabel
        placeholder={t('history.searchPlaceholder')}
        value={search}
        onChange={setSearch}
      />
      <SegmentedSwitch<HistoryView>
        label={t('history.view')}
        options={[
          { value: 'byDate', label: t('history.viewByDate') },
          { value: 'byTag', label: t('history.viewByTag') },
        ]}
        value={view}
        onChange={setView}
        size="sm"
      />
      {isDefined(error) && <Typography variant="error">{error.message}</Typography>}
      {isDefined(meetings) && meetings.length === 0 && (
        <Card padding="lg">
          <Typography variant="description">{emptyText}</Typography>
        </Card>
      )}
      {view === 'byDate' &&
        byDate(meetings ?? []).map((group) => (
          <Stack key={group.key} gap="sm">
            <Divider label={dayLabel(group)} />
            {group.meetings.map(card)}
          </Stack>
        ))}
      {view === 'byTag' &&
        byTag(meetings ?? [], t('tags.untagged')).map((group) => (
          <CollapsibleSection
            key={group.tag}
            title={t('history.group', { tag: group.tag, count: group.meetings.length })}
            defaultOpened
          >
            <Stack gap="sm" pt="xs">
              {group.meetings.map(card)}
            </Stack>
          </CollapsibleSection>
        ))}
      <ConfirmDialog
        opened={isDefined(toDelete)}
        title={t('deletion.title')}
        text={t('deletion.text', { title: toDelete?.title ?? '' })}
        confirmLabel={t('deletion.confirm')}
        loading={removal.isPending}
        onConfirm={() => isDefined(toDelete) && removal.mutate(toDelete.id)}
        onClose={() => setToDelete(null)}
      />
    </Stack>
  );
};

export default History;
