import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Mode = 'dark' | 'light'

/**
 * Colours that have to reach JavaScript rather than CSS — Recharts axis ticks,
 * treemap/sankey fills and similar. Everything else themes through CSS custom
 * properties declared in index.css, so most components just use var(--token).
 */
export type Palette = {
  axis: string
  grid: string
  text: string
  muted: string
  tooltipBg: string
  tooltipBorder: string
  accent: string
  neutralBar: string
  dry: string
  liquid: string
}

const DARK: Palette = {
  axis: '#94A3B8', grid: '#1E3A5F', text: '#FFFFFF', muted: '#94A3B8',
  tooltipBg: '#0B1830', tooltipBorder: '#2F5480',
  accent: '#00C2CB', neutralBar: '#1E4E6B',
  dry: '#C68B3E', liquid: '#3E7CA6',
}

const LIGHT: Palette = {
  axis: '#64748B', grid: '#CBD5E1', text: '#0F172A', muted: '#475569',
  tooltipBg: '#FFFFFF', tooltipBorder: '#94A3B8',
  accent: '#0E7C8B', neutralBar: '#7BA5C4',
  dry: '#B5762A', liquid: '#2E6690',
}

type Ctx = { mode: Mode; palette: Palette; toggle: () => void; setMode: (m: Mode) => void }

const ThemeContext = createContext<Ctx>({
  mode: 'dark', palette: DARK, toggle: () => {}, setMode: () => {},
})

const KEY = 'bulk-cargo-theme'

function initialMode(): Mode {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // localStorage unavailable (private mode / blocked) — fall through
  }
  try {
    if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light'
  } catch { /* no matchMedia */ }
  return 'dark'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(initialMode)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode)
    try { localStorage.setItem(KEY, mode) } catch { /* ignore */ }
  }, [mode])

  const value: Ctx = {
    mode,
    palette: mode === 'light' ? LIGHT : DARK,
    toggle: () => setMode(m => (m === 'dark' ? 'light' : 'dark')),
    setMode,
  }
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export const useTheme = () => useContext(ThemeContext)
