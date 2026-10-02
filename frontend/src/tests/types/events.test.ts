import { describe, expect, it } from 'vitest';
import { isMeetingEvent } from '@/types/events';

describe('isMeetingEvent', () => {
  it('accepts the events of the backend', () => {
    expect(isMeetingEvent({ type: 'segment', segment: { source: 'mic', start_s: 1, end_s: 2, text: 'Bonjour' } })).toBe(
      true,
    );
    expect(isMeetingEvent({ type: 'status', status: 'transcribing', error: null })).toBe(true);
    expect(isMeetingEvent({ type: 'levels', levels: { mic: -20, remote: -100 }, queue: 0 })).toBe(true);
    expect(isMeetingEvent({ type: 'devices', devices: { mic: { device: 'x', auto: true } } })).toBe(true);
    expect(isMeetingEvent({ type: 'progress', done_s: 12, total_s: null })).toBe(true);
    expect(
      isMeetingEvent({ type: 'partial', source: 'remote', speaker: 'Interlocuteur', start_s: 3, text: 'On a' }),
    ).toBe(true);
  });

  it('rejects anything else', () => {
    expect(isMeetingEvent(null)).toBe(false);
    expect(isMeetingEvent({ type: 'segment', segment: { source: 'tv', start_s: 1, text: 'x' } })).toBe(false);
    expect(isMeetingEvent({ type: 'status', status: 'paused' })).toBe(false);
    expect(isMeetingEvent({ type: 'levels', levels: { mic: 'loud' }, queue: 0 })).toBe(false);
    expect(isMeetingEvent({ type: 'partial', source: 'mic', start_s: 3 })).toBe(false);
    expect(isMeetingEvent({ type: 'unknown' })).toBe(false);
  });
});
