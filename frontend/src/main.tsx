import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';

import '@/index.css';
import { configureApiClient } from '@/lib/api/client';
import { StatusPage } from '@/pages/status-page';

configureApiClient();

const queryClient = new QueryClient();
const router = createBrowserRouter([{ path: '/', element: <StatusPage /> }]);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
