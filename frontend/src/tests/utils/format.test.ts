import { describe, expect, it } from 'vitest';
import format from '@/utils/format';

describe('format', () => {
  it('writes durations as hh:mm:ss', () => {
    expect(format.duration(0)).toBe('00:00:00');
    expect(format.duration(3725.9)).toBe('01:02:05');
    expect(format.duration(-4)).toBe('00:00:00');
  });

  it('measures the seconds between two dates', () => {
    expect(format.secondsBetween('2026-10-02T10:00:00Z', '2026-10-02T10:18:42Z')).toBe(1122);
  });

  it('gives the wall-clock time of a segment', () => {
    expect(format.clock('2026-10-02T10:31:00Z', 4, 'fr-FR')).toMatch(/:31:04$/);
  });

  it('names a day of the history, capitalised, with its year when asked', () => {
    expect(format.day(new Date(2026, 9, 5), 'fr-FR', false)).toBe('Lundi 5 octobre');
    expect(format.day(new Date(2025, 9, 5), 'fr-FR', true)).toBe('Dimanche 5 octobre 2025');
  });

  it('uses a file name without its extension as title', () => {
    expect(format.fileTitle('Point projet.Atlas.mp4')).toBe('Point projet.Atlas');
  });

  it('turns a level in dBFS into a meter value', () => {
    expect(format.level(-60, -60)).toBe(0);
    expect(format.level(-30, -60)).toBe(50);
    expect(format.level(-100, -60)).toBe(0);
    expect(format.level(3, -60)).toBe(100);
  });
});
