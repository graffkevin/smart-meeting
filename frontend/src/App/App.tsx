import theme from '@ign-junn/design-system/theme';
import { MantineProvider } from '@mantine/core';
import { QueryClientProvider } from '@tanstack/react-query';
import { createHashRouter, RouterProvider } from 'react-router';
import RootLayout from '@/App/RootLayout';
import { ROUTES } from '@/constants/routes';
import HomePage from '@/pages/HomePage';
import MeetingPage from '@/pages/MeetingPage';
import queryClient from '@/utils/queryClient';

/** Hash routes: the backend serves a single static page */
const router = createHashRouter([
  {
    element: <RootLayout />,
    children: [
      { path: ROUTES.home, element: <HomePage /> },
      { path: ROUTES.meeting, element: <MeetingPage /> },
    ],
  },
]);

const App = () => (
  <MantineProvider theme={theme} defaultColorScheme="auto">
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </MantineProvider>
);

export default App;
