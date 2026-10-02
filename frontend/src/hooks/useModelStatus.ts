import { isDefined } from '@ign-junn/design-system';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { restartAi } from '@/api/generated/smartMeetingApi';
import healthQueryOptions from '@/services/healthQueryOptions';
import type { ModelState } from '@/types/components';

/**
 * Are the transcription model and the local AI running? Green, orange or red with an explanation, from the polled
 * server status, and the restart of the local AI (shown when it is not green, outside its first install).
 */
const useModelStatus = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: health, isError } = useQuery(healthQueryOptions());
  const restart = useMutation({
    mutationFn: () => restartAi(),
    onSettled: () => queryClient.invalidateQueries({ queryKey: healthQueryOptions().queryKey }),
  });
  const unreachable: ModelState = { tone: 'danger', hint: t('models.unreachable') };
  const detail = health?.whisper_detail ?? '';
  const model = health?.ollama_model ?? '';
  const installing = (health?.setup ?? []).some((step) => !step.done && !isDefined(step.error));
  const transcriptionStates: Record<string, ModelState> = {
    loading: { tone: 'warning', hint: t('models.transcriptionLoading') },
    ready: { tone: 'success', hint: t('models.transcriptionReady', { detail }) },
    error: { tone: 'danger', hint: t('models.transcriptionError', { detail }) },
  };
  const aiDown: ModelState = installing
    ? { tone: 'warning', hint: t('models.aiInstalling') }
    : { tone: 'danger', hint: t('models.aiDown') };
  const aiUp: ModelState =
    health?.ollama_model_available === true
      ? { tone: 'success', hint: t('models.aiReady', { model }) }
      : { tone: 'warning', hint: t('models.aiMissing', { model }) };
  const reachable = !isError && isDefined(health);
  const ai = reachable && health?.ollama === true ? aiUp : aiDown;
  const transcription = transcriptionStates[health?.whisper ?? ''] ?? unreachable;

  return {
    transcription: reachable ? transcription : unreachable,
    ai: reachable ? ai : unreachable,
    /** The local AI can be restarted: it is not green and not being installed */
    restartable: reachable && ai.tone !== 'success' && !installing,
    restarting: restart.isPending,
    restart: () => restart.mutate(),
  };
};

export default useModelStatus;
