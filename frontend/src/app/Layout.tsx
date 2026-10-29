import clsx from 'clsx'
import { Wind } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { CommandBar } from '../components/CommandBar'
import { CommandPalette } from '../components/CommandPalette'
import { StatusBanners, Toaster } from '../components/Feedback'
import { useMeta } from '../features/queries'
import { ErrorBoundary } from './ErrorBoundary'
import { NAV } from './nav'


function Rail() {
  const { search } = useLocation()
  return (
    <nav
      aria-label="Main"
      className="border-border bg-surface flex shrink-0 gap-1 border-b p-2 md:sticky md:top-0 md:h-dvh md:w-48 md:flex-col md:border-r md:border-b-0"
    >
      <div className="mr-2 flex items-center gap-2 px-2 py-1 md:mb-4 md:mr-0">
        <Wind className="text-forecast size-5" aria-hidden />
        <span className="font-semibold tracking-tight">WindSight</span>
      </div>
      <p className="text-muted hidden px-2.5 text-[11px] md:order-last md:mt-auto md:block">
        <kbd className="num">Ctrl/⌘ K</kbd> to jump anywhere
      </p>
      <ul className="flex gap-1 overflow-x-auto md:flex-col">
        {NAV.map(({ to, label, icon: Icon }) => (
          <li key={to}>
            <NavLink
              to={{ pathname: to, search }}
              end={to === '/'}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm whitespace-nowrap',
                  isActive ? 'bg-surface-2 text-text font-medium' : 'text-muted hover:text-text',
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function Footer() {
  const meta = useMeta()
  const d = meta.data?.data
  return (
    <footer className="text-muted px-4 py-6 text-xs">
      Data: Elexon BMRS (FUELHH wind outturn, WINDFOR forecast). All times UK.
      {d && (
        <span className="num">
          {' '}
          · API {d.version} ({d.git_sha}) · data v{d.data_version}
        </span>
      )}
    </footer>
  )
}

export function Layout() {
  const location = useLocation()
  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50">
        Skip to content
      </a>
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">
        <StatusBanners />
        <CommandBar />
        <main id="main" className="min-w-0 flex-1 p-4">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              <ErrorBoundary label="this page">
                <Outlet />
              </ErrorBoundary>
            </motion.div>
          </AnimatePresence>
        </main>
        <Footer />
      </div>
      <Toaster />
      <CommandPalette />
    </div>
  )
}
