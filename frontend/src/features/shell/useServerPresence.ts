import { isDefined } from '@ign-junn/design-system';
import { useEffect } from 'react';
import { PRESENCE_PATH, PRESENCE_RETRY_MS } from '@/constants/app';
import webSocketUrl from '@/utils/webSocketUrl';

/**
 * Presence of this page: an open WebSocket tells the server the page exists. The launcher then reuses it instead of
 * opening another one, and the app stops once the last page is closed. When the server comes back after a stop or a
 * restart, the page reloads so that it is reused. The WebSocket is the external system this effect synchronizes.
 */
const useServerPresence = () => {
  useEffect(() => {
    const state: { lost: boolean; closed: boolean; socket?: WebSocket; retry?: ReturnType<typeof setTimeout> } = {
      lost: false,
      closed: false,
    };
    const connect = () => {
      const socket = new WebSocket(webSocketUrl(PRESENCE_PATH));
      socket.onopen = () => {
        if (state.lost) location.reload();
      };
      socket.onclose = () => {
        state.lost = true;
        if (!state.closed) state.retry = setTimeout(connect, PRESENCE_RETRY_MS);
      };
      state.socket = socket;
    };
    connect();

    return () => {
      state.closed = true;
      clearTimeout(state.retry);
      if (isDefined(state.socket)) state.socket.close();
    };
  }, []);
};

export default useServerPresence;
