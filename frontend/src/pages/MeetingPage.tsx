import { useParams } from 'react-router';
import MeetingView from '@/features/meeting/MeetingView';

/** A meeting, from the `:meetingId` route parameter */
const MeetingPage = () => {
  const { meetingId } = useParams();

  return <MeetingView key={meetingId} meetingId={Number(meetingId)} />;
};

export default MeetingPage;
