import { queryOptions } from '@tanstack/react-query';
import { recentQuestions } from '@/api/generated/smartMeetingApi';

/** Questions asked lately in any meeting: suggestions of the question field */
const recentQuestionsQueryOptions = () =>
  queryOptions({
    queryKey: ['recentQuestions'],
    queryFn: ({ signal }) => recentQuestions({ signal }),
  });

export default recentQuestionsQueryOptions;
