import { isDefined, TabBar } from '@ign-junn/design-system';
import { IconMicrophone, IconPlus } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useMatch, useNavigate } from 'react-router';
import { deleteMeeting, updateMeeting } from '@/api/generated/smartMeetingApi';
import { NEW_MEETING_TAB, RECENT_MEETINGS_IN_TABS } from '@/constants/app';
import { meetingPath, ROUTES } from '@/constants/routes';
import useTabs from '@/contexts/tabs/useTabs';
import useOpenMeeting from '@/hooks/useOpenMeeting';
import meetingListQueryOptions from '@/services/meetingListQueryOptions';
import type { RenameValues } from '@/types/meeting';

/**
 * Meetings open as tabs, under the header: switch, close, rename (double click), delete; the "+" opens a recent
 * meeting or goes back home to start a new one. A meeting reached by its address gets its tab too.
 */
const MeetingTabs = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const match = useMatch(ROUTES.meeting);
  const { data: meetings } = useQuery(meetingListQueryOptions(''));
  const rename = useMutation({
    mutationFn: ({ id, title }: RenameValues) => updateMeeting(id, { title }),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['meetings'] });
      queryClient.invalidateQueries({ queryKey: ['meeting', id] });
    },
  });
  const removal = useMutation({
    mutationFn: (id: number) => deleteMeeting(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['meetings'] }),
  });
  const { ids, remove } = useTabs();
  const openMeeting = useOpenMeeting();
  const activeId = isDefined(match) ? Number(match.params.meetingId) : null;
  const openIds = isDefined(activeId) && !ids.includes(activeId) ? [...ids, activeId] : ids;
  // Meetings deleted elsewhere disappear from the tabs once the list is known
  const items = openIds
    .filter((id) => !isDefined(meetings) || meetings.some((meeting) => meeting.id === id))
    .map((id) => ({
      value: String(id),
      label: meetings?.find((meeting) => meeting.id === id)?.title ?? t('tabs.loading'),
      icon: IconMicrophone,
    }));
  const recent = (meetings ?? [])
    .filter((meeting) => !openIds.includes(meeting.id))
    .slice(0, RECENT_MEETINGS_IN_TABS)
    .map((meeting) => ({ value: String(meeting.id), label: meeting.title }));
  const close = (value: string) => {
    const id = Number(value);
    const index = openIds.indexOf(id);
    const neighbor = openIds.filter((other) => other !== id)[Math.max(0, index - 1)];
    remove(id);
    if (id !== activeId) return;
    if (isDefined(neighbor)) navigate(meetingPath(neighbor));
    else navigate(ROUTES.home);
  };
  const add = (value: string) => (value === NEW_MEETING_TAB ? navigate(ROUTES.home) : openMeeting(Number(value)));
  const destroy = (value: string) => {
    close(value);
    removal.mutate(Number(value));
  };

  if (items.length === 0) return null;

  return (
    <TabBar
      items={items}
      active={isDefined(activeId) ? String(activeId) : ''}
      label={t('tabs.label')}
      onChange={(value) => openMeeting(Number(value))}
      onClose={close}
      closeLabel={({ label }) => t('tabs.close', { title: label })}
      addLabel={t('tabs.add')}
      addOptions={[{ value: NEW_MEETING_TAB, label: t('tabs.newMeeting'), icon: IconPlus }, ...recent]}
      onAdd={add}
      onRename={(value, title) => rename.mutate({ id: Number(value), title })}
      renameLabel={({ label }) => t('tabs.rename', { title: label })}
      onDelete={destroy}
      deleteLabels={{
        button: ({ label }) => t('tabs.delete', { title: label }),
        confirm: ({ label }) => t('tabs.deleteConfirm', { title: label }),
        submit: t('deletion.confirm'),
        cancel: t('common.cancel'),
      }}
    />
  );
};

export default MeetingTabs;
