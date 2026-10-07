import { isDefined } from '@ign-junn/design-system';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import type { MeetingDetail } from '@/api/generated/model/meetingDetail';
import type { Segment } from '@/api/generated/model/segment';
import { meetingEventsPath, PARTIAL_TOLERANCE_S } from '@/constants/app';
import { LIVE_STATUSES } from '@/constants/meeting';
import meetingQueryOptions from '@/services/meetingQueryOptions';
import { isMeetingEvent, type LiveState } from '@/types/events';
import webSocketUrl from '@/utils/webSocketUrl';

const EMPTY_LIVE_STATE: LiveState = { levels: null, queue: 0, devices: null, progress: null, partials: {} };

/** A final sentence replaces the provisional text it started from (not the one of a later sentence) */
const withoutReplacedPartial = (state: LiveState, segment: Segment): LiveState => {
  const partial = state.partials[segment.source];
  if (!isDefined(partial) || segment.start_s < partial.start_s - PARTIAL_TOLERANCE_S) return state;

  return { ...state, partials: { ...state.partials, [segment.source]: undefined } };
};

/** Adds a segment in time order (a segment already received is ignored) */
const withSegment = (segments: Segment[], segment: Segment) =>
  segments.some((known) => known.id === segment.id)
    ? segments
    : [...segments, segment].toSorted((a, b) => a.start_s - b.start_s);

/** Parsed message of the WebSocket, `undefined` when it is not JSON */
const parse = (data: unknown): unknown => {
  try {
    return JSON.parse(String(data));
  } catch {
    return undefined;
  }
};

/**
 * Live events of a meeting while it records, transcribes or is analyzed (the meeting WebSocket, an external system):
 * new segments go into the meeting query cache, a status change reloads it (end time, analysis); audio levels,
 * capture devices, import progress and the provisional text of the sentences being spoken are returned.
 */
const useMeetingEvents = (meetingId: number): LiveState => {
  const [liveState, setLiveState] = useState<LiveState>(EMPTY_LIVE_STATE);
  const queryClient = useQueryClient();
  const { data: detail } = useQuery(meetingQueryOptions(meetingId));
  const live = isDefined(detail) && LIVE_STATUSES.includes(detail.meeting.status);

  useEffect(() => {
    if (!live) return;
    const { queryKey } = meetingQueryOptions(meetingId);
    const socket = new WebSocket(webSocketUrl(meetingEventsPath(meetingId)));
    // Connected: reload once, for the segments transcribed before the connection
    socket.onopen = () => queryClient.invalidateQueries({ queryKey });
    socket.onmessage = (message) => {
      const event = parse(message.data);
      if (!isMeetingEvent(event)) return;
      if (event.type === 'segment') {
        queryClient.setQueryData<MeetingDetail>(queryKey, (current) =>
          isDefined(current) ? { ...current, segments: withSegment(current.segments, event.segment) } : current,
        );
        setLiveState((state) => withoutReplacedPartial(state, event.segment));
      }
      if (event.type === 'partial') {
        const { source, speaker, start_s, text } = event;
        setLiveState((state) => ({
          ...state,
          partials: { ...state.partials, [source]: { source, speaker, start_s, text } },
        }));
      }
      // Speakers regrouped or renamed: the whole transcript changes
      if (event.type === 'status' || event.type === 'speakers')
        queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] });
      if (event.type === 'levels') setLiveState((state) => ({ ...state, levels: event.levels, queue: event.queue }));
      if (event.type === 'devices') setLiveState((state) => ({ ...state, devices: event.devices }));
      if (event.type === 'progress')
        setLiveState((state) => ({ ...state, progress: { done: event.done_s, total: event.total_s } }));
    };

    return () => socket.close();
  }, [live, meetingId, queryClient]);

  return liveState;
};

export default useMeetingEvents;
