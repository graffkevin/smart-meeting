import { ProgressBar } from '@ign-junn/design-system';
import { useInterval } from '@mantine/hooks';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PROGRESS_MAX_BEFORE_DONE } from '@/constants/app';
import type { EstimatedProgressProps } from '@/types/components';

/**
 * Horizontal progress of a task of expected duration (an answer or a report of the local AI): fills up with the
 * time spent, tells the time left, and stays short of the end until the task is done.
 */
const EstimatedProgress = ({ label, estimateS, startedAt }: EstimatedProgressProps) => {
  const [now, setNow] = useState(Date.now());
  const { t } = useTranslation();
  useInterval(() => setNow(Date.now()), 500, { autoInvoke: true });
  const elapsed = (now - startedAt) / 1000;
  const remaining = Math.round(estimateS - elapsed);
  const minutes = Math.floor(remaining / 60);
  const time =
    minutes > 0
      ? t('progress.minutes', { minutes, seconds: remaining % 60 })
      : t('progress.seconds', { count: remaining });
  const value = Math.min(PROGRESS_MAX_BEFORE_DONE, (elapsed / Math.max(estimateS, 1)) * 100);

  return (
    <ProgressBar
      label={remaining > 1 ? t('progress.remaining', { label, time }) : t('progress.almost', { label })}
      value={value}
      animated
    />
  );
};

export default EstimatedProgress;
