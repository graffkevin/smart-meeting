import {
  Badge,
  Card,
  DataTable,
  Grid,
  isDefined,
  Stack,
  StatusIcon,
  Tooltip,
  Typography,
} from '@ign-junn/design-system';
import type { TablerIcon } from '@tabler/icons-react';
import { IconAlertTriangle, IconCheck, IconHelpCircle } from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { MeetingReportProps } from '@/types/components';

/** Report of a meeting: summary, decisions, actions, open questions, risks and technical topics */
const MeetingReport = ({ analysis }: MeetingReportProps) => {
  const { t } = useTranslation();
  const { summary, decisions, actions, questions, risks, technical_topics } = analysis;
  const actionRows = actions.map((action, index) => ({
    key: `${index}-${action.task}`,
    cells: {
      task: (
        <Stack direction="row" gap="xs" align="center">
          <Typography variant="body2">{action.task}</Typography>
          {action.verified === false && (
            <Tooltip label={t('report.unverified')}>
              <StatusIcon icon={IconAlertTriangle} tone="warning" size="sm" label={t('report.unverified')} />
            </Tooltip>
          )}
        </Stack>
      ),
      owner: isDefined(action.owner) ? (
        <Badge tone="primary">{action.owner}</Badge>
      ) : (
        <Typography variant="caption">{t('report.noOwner')}</Typography>
      ),
      deadline: isDefined(action.deadline) ? (
        <Badge tone="accent">{action.deadline}</Badge>
      ) : (
        <Typography variant="caption">{t('report.noDeadline')}</Typography>
      ),
    },
  }));
  const section = (title: string, content: ReactNode) => (
    <Card padding="md" fullHeight>
      <Stack gap="sm">
        <Typography variant="h5">{title}</Typography>
        {content}
      </Stack>
    </Card>
  );
  const list = (items: string[], icon: TablerIcon, tone: 'success' | 'primary' | 'warning') =>
    items.length === 0 ? (
      <Typography variant="description">{t('report.nothing')}</Typography>
    ) : (
      <Stack gap="xs">
        {items.map((item) => (
          <Stack key={item} direction="row" gap="xs" align="flex-start" wrap="nowrap">
            <StatusIcon icon={icon} tone={tone} size="sm" />
            <Typography variant="body1">{item}</Typography>
          </Stack>
        ))}
      </Stack>
    );

  return (
    <Stack gap="md">
      <Card padding="lg" highlighted>
        <Stack gap="xs">
          <Typography variant="h5">{t('report.summary')}</Typography>
          <Typography variant="lead">{summary}</Typography>
        </Stack>
      </Card>
      {section(
        t('report.actions'),
        actions.length === 0 ? (
          <Typography variant="description">{t('report.nothing')}</Typography>
        ) : (
          <DataTable
            label={t('report.actions')}
            columns={[
              { key: 'task', label: t('report.task') },
              { key: 'owner', label: t('report.owner') },
              { key: 'deadline', label: t('report.deadline') },
            ]}
            rows={actionRows}
          />
        ),
      )}
      <Grid cols={{ base: 1, sm: 2 }} gap="md">
        {section(t('report.decisions'), list(decisions, IconCheck, 'success'))}
        {section(t('report.questions'), list(questions, IconHelpCircle, 'primary'))}
        {section(t('report.risks'), list(risks, IconAlertTriangle, 'warning'))}
        {section(
          t('report.topics'),
          technical_topics.length === 0 ? (
            <Typography variant="description">{t('report.nothing')}</Typography>
          ) : (
            <Stack direction="row" gap="xs" wrap="wrap">
              {technical_topics.map((topic) => (
                <Badge key={topic} tone="muted">
                  {topic}
                </Badge>
              ))}
            </Stack>
          ),
        )}
      </Grid>
    </Stack>
  );
};

export default MeetingReport;
