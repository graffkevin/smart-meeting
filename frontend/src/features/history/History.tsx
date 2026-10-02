import { Card, isDefined, Stack, TextField, Typography } from '@ign-junn/design-system';
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

/** History of the meetings, newest first, searchable in titles, summaries and transcripts */
const History = () => {
  const [search, setSearch] = useState('');
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

  return (
    <Stack gap="sm">
      <Stack direction="row" gap="md" align="center" justify="space-between" wrap="wrap">
        <Typography variant="h5">{t('history.title')}</Typography>
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
      {isDefined(error) && <Typography variant="error">{error.message}</Typography>}
      {isDefined(meetings) && meetings.length === 0 && (
        <Card padding="lg">
          <Typography variant="description">{emptyText}</Typography>
        </Card>
      )}
      {meetings?.map((meeting) => (
        <MeetingCard
          key={meeting.id}
          meeting={meeting}
          onOpen={() => openMeeting(meeting.id)}
          onDelete={() => setToDelete(meeting)}
        />
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
