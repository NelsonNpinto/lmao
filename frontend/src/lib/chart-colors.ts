import { useEffect, useState } from 'react'
import { useTheme } from './stores'

/**
 * SVG presentation attributes (what Recharts writes for stroke/fill) do not
 * resolve CSS custom properties, so chart colours are read from the tokens as
 * concrete values and re-read whenever the theme or the OS scheme changes.
 */
const TOKENS = ['actual', 'forecast', 'band', 'muted', 'grid', 'border', 'text', 'error-pos', 'error-neg'] as const
export type ChartColors = Record<(typeof TOKENS)[number], string>

function read(): ChartColors {
  const cs = getComputedStyle(document.documentElement)
  return Object.fromEntries(TOKENS.map((t) => [t, cs.getPropertyValue(`--${t}`).trim()])) as ChartColors
}

export function useChartColors(): ChartColors {
  const theme = useTheme((s) => s.theme)
  const [colors, setColors] = useState(read)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)')
    const update = () => setColors(read())
    const id = requestAnimationFrame(update) // after data-theme is applied
    mq.addEventListener('change', update)
    return () => {
      cancelAnimationFrame(id)
      mq.removeEventListener('change', update)
    }
  }, [theme])
  return colors
}
