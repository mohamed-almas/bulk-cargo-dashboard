import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useTheme } from '../lib/theme'

const NAV = [
  { to: '/global',          icon: '🌍', label: 'Global Overview' },
  { to: '/dry',              icon: '🪨', label: 'Global Dry Bulk' },
  { to: '/liquid',           icon: '🛢️', label: 'Global Liquid Bulk' },
  { to: '/country',          icon: '🏳️', label: 'Country' },
  { to: '/region',           icon: '🗺️', label: 'Region' },
  { to: '/coastal-region',   icon: '🌊', label: 'Coastal Region' },
  { to: '/port',             icon: '⚓', label: 'Port' },
  { to: '/commodity',        icon: '📦', label: 'Commodity' },
  { to: '/voyage',           icon: '🧭', label: 'Voyage Analysis' },
  { to: '/vessel',           icon: '🚢', label: 'Vessel Analysis' },
]

function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { mode, toggle } = useTheme()
  const next = mode === 'dark' ? 'light' : 'dark'
  return (
    <button
      onClick={toggle}
      title={`Switch to ${next} mode`}
      aria-label={`Switch to ${next} mode`}
      className={`flex items-center gap-2 rounded border transition-colors
                  ${compact ? 'px-2 py-1' : 'px-3 py-1.5 w-full justify-center'}`}
      style={{ borderColor: 'var(--border)', color: 'var(--muted)', background: 'transparent' }}
    >
      <span className="text-sm leading-none">{mode === 'dark' ? '☀️' : '🌙'}</span>
      {!compact && <span className="text-[11px]">{mode === 'dark' ? 'Light' : 'Dark'} mode</span>}
    </button>
  )
}

export default function Layout() {
  const [open, setOpen] = useState(false)

  return (
    <div className="flex w-full min-h-screen">
      {open && (
        <div className="fixed inset-0 bg-black/50 z-20 lg:hidden" onClick={() => setOpen(false)} />
      )}

      <aside
        className={`fixed lg:static inset-y-0 left-0 z-30 w-56 shrink-0 border-r
                    flex flex-col transition-transform
                    ${open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}
        style={{ background: 'var(--sidebar)', borderColor: 'var(--border)' }}
      >
        <div className="px-4 py-4 border-b" style={{ borderColor: 'var(--border)' }}>
          <div className="flex items-center gap-2">
            <span className="text-lg leading-none">🚢</span>
            <div>
              <div className="text-xs font-bold leading-tight" style={{ color: 'var(--text)' }}>
                Global Bulk Trade Flows
              </div>
              <div className="text-[10px] leading-tight" style={{ color: 'var(--muted)' }}>
                Cargo Intelligence
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 py-2 overflow-y-auto">
          {NAV.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setOpen(false)}
              className="flex items-center gap-3 px-4 py-2 text-[13px] transition-colors"
              style={({ isActive }) =>
                isActive
                  ? {
                      background: 'var(--panel)',
                      color: 'var(--accent)',
                      borderRight: '2px solid var(--accent)',
                      fontWeight: 500,
                    }
                  : { color: 'var(--muted)' }
              }
            >
              <span className="text-sm w-4 text-center shrink-0">{item.icon}</span>
              <span className="leading-tight">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="px-3 py-3 border-t space-y-2" style={{ borderColor: 'var(--border)' }}>
          <ThemeToggle />
          <div className="text-[10px] leading-relaxed px-1" style={{ color: 'var(--faint)' }}>
            Data source: Supabase Materialized Views · refreshed weekly
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col" style={{ background: 'var(--bg)' }}>
        <div className="lg:hidden flex items-center gap-3 px-4 py-3 border-b shrink-0"
             style={{ borderColor: 'var(--border)' }}>
          <button onClick={() => setOpen(v => !v)} aria-label="Toggle navigation"
                  className="text-lg leading-none" style={{ color: 'var(--muted)' }}>
            ☰
          </button>
          <span className="text-sm font-semibold flex-1" style={{ color: 'var(--text)' }}>
            Bulk Cargo Trade Flows
          </span>
          <ThemeToggle compact />
        </div>

        <main className="flex-1 min-w-0 overflow-x-hidden p-4 sm:p-5 lg:p-6">
          <div className="mx-auto w-full max-w-[1600px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
