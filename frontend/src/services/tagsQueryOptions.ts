import { queryOptions } from '@tanstack/react-query';
import { listTags } from '@/api/generated/smartMeetingApi';

/** Every tag in use, most used first: suggestions of the tag fields */
const tagsQueryOptions = () =>
  queryOptions({
    queryKey: ['tags'],
    queryFn: ({ signal }) => listTags({ signal }),
  });

export default tagsQueryOptions;
