import { queryOptions } from '@tanstack/react-query';
import { audioDevices } from '@/api/generated/smartMeetingApi';

/** Microphones and outputs of the machine, and the ones the applications use right now */
const audioDevicesQueryOptions = () =>
  queryOptions({
    queryKey: ['audioDevices'],
    queryFn: ({ signal }) => audioDevices({ signal }),
  });

export default audioDevicesQueryOptions;
