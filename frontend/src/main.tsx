import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router';

import '@/index.css';
import { AppLayout } from '@/components/layout/app-layout';
import { configureApiClient } from '@/lib/api/client';
import { StatusPage } from '@/pages/status-page';

configureApiClient();

const queryClient = new QueryClient();
const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/gallery" replace /> },
      {
        path: 'gallery',
        lazy: async () => ({
          Component: (await import('@/pages/gallery-page')).GalleryPage,
        }),
      },
      { path: 'status', element: <StatusPage /> },
      {
        path: 'dev/walk',
        lazy: async () => ({
          Component: (await import('@/pages/walk-sandbox-page'))
            .WalkSandboxPage,
        }),
      },
    ],
  },
]);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
