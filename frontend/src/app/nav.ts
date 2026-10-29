import {
  CalendarDays,
  Database,
  Gauge,
  History,
  Lightbulb,
  Target,
  Timer,
} from 'lucide-react'

export const NAV = [
  { to: '/', label: 'Dashboard', icon: Gauge },
  { to: '/accuracy', label: 'Accuracy', icon: Target },
  { to: '/cutoff', label: 'Cutoff', icon: Timer },
  { to: '/days', label: 'Day explorer', icon: CalendarDays },
  { to: '/replay', label: 'Replay', icon: History },
  { to: '/findings', label: 'Findings', icon: Lightbulb },
  { to: '/data', label: 'Data', icon: Database },
] as const
