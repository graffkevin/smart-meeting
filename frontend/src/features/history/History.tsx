import {
  Card,
  CollapsibleSection,
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
import type { MeetingListItem } from '@/api/generated/model/meetingListItem';
import { deleteMeeting } from '@/api/generated/smartMeetingApi';
import ConfirmDialog from '@/components/ConfirmDialog';
import MeetingCard from '@/components/MeetingCard';
import { SEARCH_DEBOUNCE_MS } from '@/constants/app';
import useOpenMeeting from '@/hooks/useOpenMeeting';
import meetingListQueryOptions from '@/services/meetingListQueryOptions';
import type { HistoryView, TagGroup } from '@/types/meeting';

/** Groups of meetings by tag, alphabetically, meetings without tag last */
const byTag = (meetings: MeetingListItem[], untagged: string): TagGroup[] => {
  const tags = [...new Set(meetings.flatMap((meeting) => meeting.tags ?? []))].toSorted((a, b) => a.localeCompare(b));
  const groups = tags.map((tag) => ({ tag, meetings: meetings.filter((meeting) => meeting.tags?.includes(tag)) }));
  const without = meetings.filter((meeting) => (meeting.tags ?? []).length === 0);

  return without.length > 0 ? [...groups, { tag: untagged, meetings: without }] : groups;
};

/** History of the meetings, newest first or grouped by tag, searchable in titles, tags, summaries and transcripts */
const History = () => {
  const [search, setSearch] = useState('');
  const [view, setView] = useState<HistoryView>('all');
  const [toDelete, setToDelete] = useState<MeetingListItem | null>(null);
  const { t } = useTranslation();
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
  const card = (meeting: MeetingListItem) => (
    <MeetingCard
      key={meeting.id}
      meeting={meeting}
      onOpen={() => openMeeting(meeting.id)}
      onDelete={() => setToDelete(meeting)}
    />
  );

  return (
    <Stack gap="sm">
      <Stack direction="row" gap="md" align="center" justify="space-between" wrap="wrap">
        <Typography variant="h5">{t('history.title')}</Typography>
        <Stack direction="row" gap="sm" align="center" wrap="wrap">
          <SegmentedSwitch<HistoryView>
            label={t('history.view')}
            options={[
              { value: 'all', label: t('history.viewAll') },
              { value: 'byTag', label: t('history.viewByTag') },
            ]}
            value={view}
            onChange={setView}
            size="sm"
          />
          <TextField
            type="search"
            icon={IconSearch}
            label={t('history.search')}
            hideLabel
            placeholder={t('history.searchPlaceholder')}
            value={search}
            onChange={setSearch}
          />
        </Stack>
      </Stack>
      {isDefined(error) && <Typography variant="error">{error.message}</Typography>}
      {isDefined(meetings) && meetings.length === 0 && (
        <Card padding="lg">
          <Typography variant="description">{emptyText}</Typography>
        </Card>
      )}
      {view === 'all' && meetings?.map(card)}
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
