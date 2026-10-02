import '@mantine/core/styles.css';
import '@ign-junn/design-system/styles.css';
import '@/utils/i18n';
import { isDefined } from '@ign-junn/design-system';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from '@/App/App';

const root = document.getElementById('root');
if (isDefined(root))
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
