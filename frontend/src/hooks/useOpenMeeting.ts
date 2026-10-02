import { useNavigate } from 'react-router';
import { meetingPath } from '@/constants/routes';
import useTabs from '@/contexts/tabs/useTabs';

/** Opens a meeting in its tab (added if needed) */
const useOpenMeeting = () => {
  const navigate = useNavigate();
  const { add } = useTabs();

  return (meetingId: number) => {
    add(meetingId);
    navigate(meetingPath(meetingId));
  };
};

export default useOpenMeeting;
