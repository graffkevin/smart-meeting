import { describe, expect, it } from 'vitest';
import { TRANSCRIPTION_LANGUAGES } from '@/constants/app';
import { STATUS_TONES } from '@/constants/meeting';
import fr from '@/locales/fr';

describe('French texts', () => {
  it('name every meeting status', () => {
    Object.keys(STATUS_TONES).forEach((status) => {
      expect(fr.status).toHaveProperty(status);
    });
  });

  it('name every transcription language', () => {
    TRANSCRIPTION_LANGUAGES.forEach((code) => {
      expect(fr.languages).toHaveProperty(code);
    });
  });
});

describe('English texts', () => {
  const keys = (value: unknown, prefix = ''): string[] =>
    typeof value === 'object' && value !== null
      ? Object.entries(value).flatMap(([key, child]) => keys(child, `${prefix}${key}.`))
      : [prefix];

  it('translate every French text', async () => {
    const { default: en } = await import('@/locales/en');
    expect(keys(en)).toEqual(keys(fr));
  });
});
