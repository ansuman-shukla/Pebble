import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';

import '@/index.css';
import { AppLayout } from '@/components/layout/app-layout';
import { configureApiClient } from '@/lib/api/client';
import { StatusPage } from '@/pages/status-page';

configureApiClient();

const queryClient = new QueryClient();
// shown while a lazy page's code loads on the first visit
const pageLoading = (
  <div className="text-muted-foreground p-4 text-sm">Loading…</div>
);
const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      {
        index: true,
        hydrateFallbackElement: pageLoading,
        lazy: async () => ({
          Component: (await import('@/pages/world-page')).WorldPage,
        }),
      },
      {
        path: 'gallery',
        hydrateFallbackElement: pageLoading,
        lazy: async () => ({
          Component: (await import('@/pages/gallery-page')).GalleryPage,
        }),
      },
      { path: 'status', element: <StatusPage /> },
      {
        path: 'dev/walk',
        hydrateFallbackElement: pageLoading,
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
