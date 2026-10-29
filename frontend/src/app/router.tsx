/* eslint-disable react/only-export-components -- route table module, not a hot-reloaded component */
import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter } from 'react-router'
import { Card, Skeleton } from '../components/ui'
import Dashboard from '../pages/Dashboard'
import { Layout } from './Layout'

// The dashboard ships in the main bundle; every other page loads on first visit.
const Accuracy = lazy(() => import('../pages/Accuracy'))
const CutoffExplorer = lazy(() => import('../pages/CutoffExplorer'))
const DayExplorer = lazy(() => import('../pages/DayExplorer'))
const Replay = lazy(() => import('../pages/Replay'))
const Findings = lazy(() => import('../pages/Findings'))
const Data = lazy(() => import('../pages/Data'))

const page = (el: ReactNode) => (
  <Suspense
    fallback={
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-80" />
      </div>
    }
  >
    {el}
  </Suspense>
)

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'accuracy', element: page(<Accuracy />) },
      { path: 'cutoff', element: page(<CutoffExplorer />) },
      { path: 'days', element: page(<DayExplorer />) },
      { path: 'days/:date', element: page(<DayExplorer />) },
      { path: 'replay', element: page(<Replay />) },
      { path: 'findings', element: page(<Findings />) },
      { path: 'data', element: page(<Data />) },
      {
        path: '*',
        element: (
          <Card title="Not found">
            <p className="text-muted text-sm">That page does not exist. Use the navigation, or press Ctrl/⌘ K.</p>
          </Card>
        ),
      },
    ],
  },
])
