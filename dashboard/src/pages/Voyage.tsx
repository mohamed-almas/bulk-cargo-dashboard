import { useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { supabase } from '../lib/supabase'
import { useQuery, unwrap } from '../lib/useQuery'
import { useTheme } from '../lib/theme'
import {
  KPICard, Card, Spinner, ErrorMsg, PageHeader, SectionTitle, Select, Tabs, BarList,
  CustomTooltip, fmt, fmtVolume, fmtCount,
  MIN_YEAR, MAX_YEAR, DEFAULT_YEAR, CARGO_COLORS,
} from '../components/ui'

// Analysis is drawn from the top-volume routes for the selected year/cargo
// filter, not the full ~110k-row year slice — the matview is indexed on
// (year, cargo_bucket, total_volume desc) so this stays fast, and route
// volume is heavily Pareto-distributed so the top slice captures the vast
// majority of total voyages/volume.
const ROUTE_SAMPLE = 3000

type PairRow = {
  load_port_name: string
  discharge_port_name: string
  cargo_bucket: string
  total_volume: number
  voyages: number
  sum_distance_actual: number
  sum_days_steaming: number
  sum_days_total_duration: number
}

const CARGO_TABS = ['All', 'Dry', 'Liquid'] as const

function avgDistance(r: { sum_distance_actual: number; voyages: number }) {
  return r.voyages > 0 ? r.sum_distance_actual / r.voyages : 0
}
function avgDuration(r: { sum_days_total_duration: number; voyages: number }) {
  return r.voyages > 0 ? r.sum_days_total_duration / r.voyages : 0
}
function avgSpeed(r: { sum_distance_actual: number; sum_days_steaming: number }) {
  const hours = r.sum_days_steaming * 24
  return hours > 0 ? r.sum_distance_actual / hours : 0
}

const DISTANCE_BANDS = [
  { label: '<1,000 nm', min: 0, max: 1000 },
  { label: '1,000–3,000 nm', min: 1000, max: 3000 },
  { label: '3,000–6,000 nm', min: 3000, max: 6000 },
  { label: '>6,000 nm', min: 6000, max: Infinity },
]

export default function Voyage() {
  const { palette } = useTheme()
  const [year, setYear] = useState(String(DEFAULT_YEAR))
  const [cargo, setCargo] = useState<typeof CARGO_TABS[number]>('All')

  const yearOptions = useMemo(() => {
    const out: { value: string; label: string }[] = []
    for (let y = MAX_YEAR; y >= MIN_YEAR; y--) out.push({ value: String(y), label: String(y) })
    return out
  }, [])

  const pairs = useQuery(async () => {
    const bucket = cargo === 'Dry' ? 'Dry Bulk' : cargo === 'Liquid' ? 'Liquid Bulk' : null
    const cols = 'load_port_name,discharge_port_name,cargo_bucket,total_volume,voyages,' +
      'sum_distance_actual,sum_days_steaming,sum_days_total_duration'
    let q = supabase.from('xmv_port_pairs').select(cols).eq('year', Number(year))
    if (bucket) q = q.eq('cargo_bucket', bucket)
    const res = await q.order('total_volume', { ascending: false }).limit(ROUTE_SAMPLE)
    return unwrap(res) as unknown as PairRow[]
  }, [year, cargo])

  const rows = pairs.data ?? []

  const kpis = useMemo(() => {
    const totalVoyages = rows.reduce((s, r) => s + r.voyages, 0)
    const totalVolume = rows.reduce((s, r) => s + r.total_volume, 0)
    const totalDist = rows.reduce((s, r) => s + r.sum_distance_actual, 0)
    const totalDuration = rows.reduce((s, r) => s + r.sum_days_total_duration, 0)
    return {
      totalVoyages,
      totalVolume,
      avgDistance: totalVoyages > 0 ? totalDist / totalVoyages : 0,
      avgDuration: totalVoyages > 0 ? totalDuration / totalVoyages : 0,
      avgParcel: totalVoyages > 0 ? totalVolume / totalVoyages : 0,
    }
  }, [rows])

  const topRoutes = useMemo(() => rows.slice(0, 20), [rows])

  const topLoadPorts = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(r.load_port_name, (m.get(r.load_port_name) ?? 0) + r.voyages)
    return Array.from(m, ([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
  }, [rows])

  const topDischargePorts = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(r.discharge_port_name, (m.get(r.discharge_port_name) ?? 0) + r.voyages)
    return Array.from(m, ([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
  }, [rows])

  const distanceBands = useMemo(() => {
    return DISTANCE_BANDS.map(band => {
      const voyages = rows
        .filter(r => {
          const d = avgDistance(r)
          return d >= band.min && d < band.max
        })
        .reduce((s, r) => s + r.voyages, 0)
      return { label: band.label, voyages }
    })
  }, [rows])

  const parcelByCargo = useMemo(() => {
    const groups: Record<string, { volume: number; voyages: number }> = {}
    for (const r of rows) {
      const key = r.cargo_bucket
      const g = groups[key] ?? { volume: 0, voyages: 0 }
      g.volume += r.total_volume
      g.voyages += r.voyages
      groups[key] = g
    }
    return Object.entries(groups).map(([bucket, g]) => ({
      bucket,
      short: bucket.replace(' Bulk', ''),
      avgParcel: g.voyages > 0 ? g.volume / g.voyages : 0,
    }))
  }, [rows])

  return (
    <div className="space-y-5">
      <PageHeader
        title="P2P Voyage Analysis"
        subtitle="Load port to discharge port route patterns"
      >
        <Select value={year} onChange={setYear} placeholder="" options={yearOptions} />
        <Tabs value={cargo} onChange={v => setCargo(v as typeof CARGO_TABS[number])} options={[...CARGO_TABS]} />
      </PageHeader>

      {pairs.loading ? <Spinner /> : pairs.error ? <ErrorMsg msg={pairs.error} /> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
            <KPICard label="Total Voyages" value={fmtCount(kpis.totalVoyages)} accent sub={`${year} · ${cargo}`} />
            <KPICard label="Total Volume" value={fmtVolume(kpis.totalVolume)} sub="tonnes" />
            <KPICard label="Avg Distance" value={fmt(kpis.avgDistance)} sub="nautical miles / voyage" />
            <KPICard label="Avg Voyage Duration" value={fmt(kpis.avgDuration, 1)} sub="days" />
            <KPICard label="Avg Parcel Size" value={fmtVolume(kpis.avgParcel)} sub="tonnes / voyage" />
          </div>

          <p className="text-[10px]" style={{ color: 'var(--faint)' }}>
            Based on the top {fmt(rows.length)} routes by volume for this selection (out of many more
            low-volume pairs) — the matview is indexed for fast top-N retrieval, and these routes carry
            the large majority of total volume.
          </p>

          <SectionTitle title="Top Routes" note={`by total volume · ${topRoutes.length} shown`} />
          <Card>
            {topRoutes.length === 0 ? (
              <p className="text-sm py-6 text-center" style={{ color: 'var(--dim)' }}>No data for this selection.</p>
            ) : (
              <div className="overflow-auto max-h-[480px]">
                <table className="w-full text-xs text-left">
                  <thead>
                    <tr style={{ color: 'var(--muted)', borderBottom: '1px solid var(--border)' }} className="sticky top-0">
                      <th className="pb-2 pr-3 font-medium" style={{ background: 'var(--panel)' }}>#</th>
                      <th className="pb-2 pr-3 font-medium" style={{ background: 'var(--panel)' }}>Route</th>
                      <th className="pb-2 pr-3 font-medium" style={{ background: 'var(--panel)' }}>Cargo</th>
                      <th className="pb-2 pr-3 font-medium text-right" style={{ background: 'var(--panel)' }}>Volume</th>
                      <th className="pb-2 pr-3 font-medium text-right" style={{ background: 'var(--panel)' }}>Voyages</th>
                      <th className="pb-2 pr-3 font-medium text-right" style={{ background: 'var(--panel)' }}>Avg Distance</th>
                      <th className="pb-2 pr-3 font-medium text-right" style={{ background: 'var(--panel)' }}>Avg Duration</th>
                      <th className="pb-2 font-medium text-right" style={{ background: 'var(--panel)' }}>Avg Speed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topRoutes.map((r, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td className="py-1.5 pr-3 tabular-nums" style={{ color: 'var(--faint)' }}>{i + 1}</td>
                        <td className="py-1.5 pr-3 max-w-[280px] truncate" style={{ color: 'var(--text-2)' }}
                            title={`${r.load_port_name} → ${r.discharge_port_name}`}>
                          {r.load_port_name} → {r.discharge_port_name}
                        </td>
                        <td className="py-1.5 pr-3" style={{ color: r.cargo_bucket.startsWith('Dry') ? CARGO_COLORS.Dry : CARGO_COLORS.Liquid }}>
                          {r.cargo_bucket.replace(' Bulk', '')}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums" style={{ color: 'var(--accent)' }}>{fmtVolume(r.total_volume)}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(r.voyages)}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(avgDistance(r))} nm</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(avgDuration(r), 1)} d</td>
                        <td className="py-1.5 text-right tabular-nums">{fmt(avgSpeed(r), 1)} kn</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <SectionTitle title="Port Rankings" note="by voyage count" />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Top Load Ports">
              <BarList rows={topLoadPorts} valueFormat={fmtCount} maxRows={15} />
            </Card>
            <Card title="Top Discharge Ports">
              <BarList rows={topDischargePorts} valueFormat={fmtCount} maxRows={15} color={palette.liquid} />
            </Card>
          </div>

          <SectionTitle title="Route Characteristics" />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Voyages by Distance Band" subtitle="average route distance per voyage">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={distanceBands} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fill: palette.axis, fontSize: 10 }}
                         axisLine={{ stroke: palette.grid }} tickLine={false} />
                  <YAxis tick={{ fill: palette.axis, fontSize: 11 }} width={44} axisLine={false} tickLine={false}
                         tickFormatter={fmtCount} />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
                  <Bar dataKey="voyages" name="Voyages" fill={palette.accent} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <Card title="Avg Parcel Size by Cargo Type" subtitle="tonnes per voyage">
              {parcelByCargo.length === 0 ? (
                <p className="text-sm py-6 text-center" style={{ color: 'var(--dim)' }}>No data for this selection.</p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={parcelByCargo} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="short" tick={{ fill: palette.axis, fontSize: 11 }}
                           axisLine={{ stroke: palette.grid }} tickLine={false} />
                    <YAxis tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false}
                           tickFormatter={fmtVolume} />
                    <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
                    <Bar dataKey="avgParcel" name="Avg Parcel Size" fill={palette.accent} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>
          </div>

          <p className="text-[10px] leading-relaxed pt-2" style={{ color: 'var(--faint)' }}>
            Data source: Supabase Materialized Views · Data refreshed periodically · Hover on charts for details.
          </p>
        </>
      )}
    </div>
  )
}
