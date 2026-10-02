import AiStatus from '@/components/AiStatus';
import useModelStatus from '@/hooks/useModelStatus';

/** Green, orange or red dot of the header: is the local AI running? (the home page tells about transcription) */
const ModelStatus = () => {
  const { ai, model, restartable, restarting, restart } = useModelStatus();

  return <AiStatus ai={ai} model={model} restartable={restartable} restarting={restarting} onRestart={restart} />;
};

export default ModelStatus;
