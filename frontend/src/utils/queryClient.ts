import { QueryClient } from '@tanstack/react-query';

/**
 * Single TanStack Query client. The backend is local: a failed request is not retried, and live data is pushed by
 * the meeting WebSocket (which updates the cache) or polled where needed (`refetchInterval`).
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false },
    mutations: { retry: false },
  },
});

export default queryClient;
