import { CopyButton, InlineCode, isDefined, Stack, Typography } from '@ign-junn/design-system';
import { useTranslation } from 'react-i18next';
import type { StoragePathsProps } from '@/types/components';

/** Where a finished meeting is kept: the database file, and the folder of its audio when kept, each to copy */
const StoragePaths = ({ storage }: StoragePathsProps) => {
  const { t } = useTranslation();
  const paths = [
    { key: 'database', label: t('meeting.storedIn'), path: storage.database },
    ...(isDefined(storage.audio) ? [{ key: 'audio', label: t('meeting.audioIn'), path: storage.audio }] : []),
  ];

  return (
    <Stack gap="xxs">
      {paths.map(({ key, label, path }) => (
        <Stack key={key} direction="row" gap="xs" align="center" wrap="wrap">
          <Typography variant="caption">{label}</Typography>
          <InlineCode>{path}</InlineCode>
          <CopyButton
            value={path}
            size="xs"
            labels={{ copy: t('meeting.copyPath'), copied: t('meeting.pathCopied') }}
          />
        </Stack>
      ))}
    </Stack>
  );
};

export default StoragePaths;
