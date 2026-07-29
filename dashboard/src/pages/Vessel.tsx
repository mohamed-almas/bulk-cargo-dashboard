import { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { supabase } from '../lib/supabase'
import { useQuery, fetchAll } from '../lib/useQuery'
import { useTheme } from '../lib/theme'
import {
  KPICard, Card, Spinner, ErrorMsg, Empty, PageHeader, SectionTitle, Select, Tabs, BarList,
  CustomTooltip, fmt, fmtVolume, fmtCount, fmtPct, topNWithOthers,
  MIN_YEAR, MAX_YEAR, DEFAULT_YEAR,
} from '../components/ui'
import { ForecastPanel, Donut, type YearPoint } from '../components/charts'

const TABLE = 'xmv_vessel_segment_summary'

type VesselRow = {
  year: number
  imo: number
  vessel_name: string
  segment: string
  sub_segment: string | null
  dwt: number
  cargo_bucket: 'Dry Bulk' | 'Liquid Bulk'
  total_volume: number
  voyages: number
  ton_miles: number
  sum_days_steaming: number
  sum_days_total_duration: number
}

const CARGO_OPTIONS = ['All', 'Dry Bulk', 'Liquid Bulk'] as const
type CargoTab = typeof CARGO_OPTIONS[number]

const YEAR_OPTIONS = Array.from({ length: MAX_YEAR - MIN_YEAR + 1 }, (_, i) => MAX_YEAR - i)

/** Sums a numeric field across rows, tolerating string-typed Postgres numerics. */
function sumBy(rows: VesselRow[], key: keyof VesselRow): number {
  return rows.reduce((s, r) => s + (Number(r[key]) || 0), 0)
}

export default function Vessel() {
  const { palette } = useTheme()
  const [year, setYear] = useState(DEFAULT_YEAR)
  const [cargoTab, setCargoTab] = useState<CargoTab>('All')
  const [segment, setSegment] = useState('')
  const [hasSetDefault, setHasSetDefault] = useState(false)

  // Segment/cargo combinations present in the selected year, with total volume —
  // used to populate the segment dropdown and pick a sensible default.
  const segMeta = useQuery(async () => {
    const rawRows = await fetchAll<{ imo: number; segment: string; cargo_bucket: string; total_volume: number }>(
      (from, to) => supabase.from(TABLE)
        .select('imo,segment,cargo_bucket,total_volume')
        .eq('year', year)
        .order('imo')
        .range(from, to),
      50000,
    )
    // Same defensive de-dup as yearData (see comment there).
    const seenRows = new Set<string>()
    const rows = rawRows.filter(r => {
      const key = `${r.imo}|${r.cargo_bucket}`
      if (seenRows.has(key)) return false
      seenRows.add(key)
      return true
    })
    const m = new Map<string, { segment: string; cargo_bucket: string; total_volume: number }>()
    for (const r of rows) {
      const key = `${r.segment}|${r.cargo_bucket}`
      const cur = m.get(key)
      if (cur) cur.total_volume += Number(r.total_volume) || 0
      else m.set(key, { segment: r.segment, cargo_bucket: r.cargo_bucket, total_volume: Number(r.total_volume) || 0 })
    }
    return Array.from(m.values()).sort((a, b) => b.total_volume - a.total_volume)
  }, [year])

  // Segment options filtered by the active cargo tab (segment names are NOT
  // unique to a cargo bucket — e.g. "Capesize" and "Tanker" appear under both
  // Dry Bulk and Liquid Bulk with different fleets, so options are de-duped by
  // name only within the currently selected cargo tab).
  const segmentOptions = useMemo(() => {
    const rows = segMeta.data ?? []
    const filtered = cargoTab === 'All' ? rows : rows.filter(r => r.cargo_bucket === cargoTab)
    const names = Array.from(new Set(filtered.map(r => r.segment)))
    return names.sort()
  }, [segMeta.data, cargoTab])

  // Default to the highest-volume segment in the latest year, once.
  useEffect(() => {
    if (!hasSetDefault && segMeta.data?.length) {
      setSegment(segMeta.data[0].segment)
      setHasSetDefault(true)
    }
  }, [segMeta.data, hasSetDefault])

  // Reset an out-of-range segment when the cargo tab changes.
  useEffect(() => {
    if (segment && segmentOptions.length && !segmentOptions.includes(segment)) {
      setSegment(segmentOptions[0])
    }
  }, [cargoTab, segmentOptions, segment])

  // Per-vessel rows for the selected year / cargo / segment — drives the KPI
  // row, top-vessels table, and vessel count.
  const yearData = useQuery(async () => {
    const rows = await fetchAll<VesselRow>(
      (from, to) => {
        let q = supabase.from(TABLE).select('*').eq('year', year)
        if (cargoTab !== 'All') q = q.eq('cargo_bucket', cargoTab)
        if (segment) q = q.eq('segment', segment)
        return q.order('imo').range(from, to)
      },
      50000,
    )
    // Defensive de-dup by (imo, cargo_bucket): StrictMode's dev-mode double
    // effect invocation plus overlapping in-flight requests can otherwise
    // leave duplicate rows in the array even though the source view is clean.
    const seen = new Set<string>()
    return rows.filter(r => {
      const key = `${r.imo}|${r.cargo_bucket}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [year, cargoTab, segment])

  // Annual trend for the selected segment/cargo — one row fetch per year is
  // avoided by fetching all years at once, filtered narrowly by segment
  // (bounded to the vessels in that segment across the full time series).
  const trend = useQuery(async () => {
    const rawRows = await fetchAll<{ year: number; imo: number; cargo_bucket: string; total_volume: number; voyages: number; ton_miles: number }>(
      (from, to) => {
        let q = supabase.from(TABLE).select('year,imo,cargo_bucket,total_volume,voyages,ton_miles')
          .gte('year', MIN_YEAR).lte('year', MAX_YEAR)
        if (cargoTab !== 'All') q = q.eq('cargo_bucket', cargoTab)
        if (segment) q = q.eq('segment', segment)
        return q.order('imo').range(from, to)
      },
      200000,
    )
    // Same defensive de-dup as yearData (see comment there).
    const seen = new Set<string>()
    const rows = rawRows.filter(r => {
      const key = `${r.year}|${r.imo}|${r.cargo_bucket}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    const byYear = new Map<number, { year: number; volume: number; voyages: number; tonMiles: number }>()
    for (const r of rows) {
      const cur = byYear.get(r.year) ?? { year: r.year, volume: 0, voyages: 0, tonMiles: 0 }
      cur.volume += Number(r.total_volume) || 0
      cur.voyages += Number(r.voyages) || 0
      cur.tonMiles += Number(r.ton_miles) || 0
      byYear.set(r.year, cur)
    }
    return Array.from(byYear.values()).sort((a, b) => a.year - b.year)
  }, [cargoTab, segment], { skip: !segment })

  // Segment comparison for the selected year — all segments, for context on
  // where the selected one stands. Combines segment+cargo since names repeat
  // across cargo buckets.
  const segCompare = useMemo(() => {
    const rows = segMeta.data ?? []
    return topNWithOthers(
      rows, 10,
      r => r.total_volume,
      r => rows.filter(x => x.segment === r.segment).length > 1
        ? `${r.segment} (${r.cargo_bucket === 'Dry Bulk' ? 'Dry' : 'Liquid'})`
        : r.segment,
    )
  }, [segMeta.data])

  const kpi = useMemo(() => {
    const rows = yearData.data ?? []
    if (!rows.length) return null
    const totalVolume = sumBy(rows, 'total_volume')
    const totalVoyages = sumBy(rows, 'voyages')
    const tonMiles = sumBy(rows, 'ton_miles')
    const steaming = sumBy(rows, 'sum_days_steaming')
    const totalDuration = sumBy(rows, 'sum_days_total_duration')
    const avgDwt = rows.reduce((s, r) => s + (Number(r.dwt) || 0), 0) / rows.length
    const vesselCount = rows.length
    const avgParcel = totalVoyages > 0 ? totalVolume / totalVoyages : 0
    const tripDayPct = totalDuration > 0 ? steaming / totalDuration : 0
    const portDayPct = totalDuration > 0 ? 1 - tripDayPct : 0
    return { totalVolume, totalVoyages, tonMiles, avgDwt, vesselCount, avgParcel, tripDayPct, portDayPct }
  }, [yearData.data])

  const topVessels = useMemo(() => {
    return [...(yearData.data ?? [])]
      .sort((a, b) => (Number(b.total_volume) || 0) - (Number(a.total_volume) || 0))
      .slice(0, 20)
  }, [yearData.data])

  const trendSeries = trend.data ?? []
  const volumeSeries: YearPoint[] = useMemo(
    () => trendSeries.map(r => ({ year: r.year, value: r.volume })), [trendSeries])

  const loading = segMeta.loading || yearData.loading
  const err = segMeta.error || yearData.error

  return (
    <div className="space-y-5">
      <PageHeader
        title={segment ? `${segment} — Vessel Overview` : 'Vessel Overview'}
        subtitle={`${cargoTab === 'All' ? 'All cargo' : cargoTab} · ${year}`}
      >
        <Tabs value={cargoTab} onChange={v => setCargoTab(v as CargoTab)} options={[...CARGO_OPTIONS]} />
        <Select
          value={segment} onChange={setSegment} placeholder="All segments"
          options={segmentOptions.map(s => ({ value: s, label: s }))}
        />
        <Select
          value={String(year)} onChange={v => setYear(Number(v))} placeholder=""
          options={YEAR_OPTIONS.map(y => ({ value: String(y), label: String(y) }))}
        />
      </PageHeader>

      {loading ? <Spinner /> : err ? <ErrorMsg msg={err} /> : !kpi ? (
        <Card><Empty msg="No vessel data for this selection." /></Card>
      ) : (
        <>
          {/* ---------- KPI grid ---------- */}
          <SectionTitle title="Key Metrics" note={String(year)} />
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
            <KPICard label="Total Volume" value={fmtVolume(kpi.totalVolume)} accent />
            <KPICard label="Total Voyages" value={fmtCount(kpi.totalVoyages)} />
            <KPICard label="Ton-Miles" value={fmtVolume(kpi.tonMiles)} />
            <KPICard label="Average DWT" value={fmtCount(kpi.avgDwt)} />
            <KPICard label="Vessel Count" value={fmt(kpi.vesselCount)} sub="distinct IMOs" />
            <KPICard label="Avg Parcel Size" value={fmtVolume(kpi.avgParcel)} sub="volume ÷ voyages" />
            <KPICard label="Trip-Day %" value={fmtPct(kpi.tripDayPct)} sub={`Port-Day % ${fmtPct(kpi.portDayPct)}`} />
          </div>

          {/* ---------- Annual trend ---------- */}
          <SectionTitle title="Annual Trend" note={segment || 'select a segment'} />
          <Card subtitle="volume and voyages by year">
            {trend.loading ? <Spinner /> : trend.error ? <ErrorMsg msg={trend.error} /> : trendSeries.length === 0 ? <Empty /> : (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={trendSeries} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="year" tick={{ fill: palette.axis, fontSize: 11 }}
                         axisLine={{ stroke: palette.grid }} tickLine={false} />
                  <YAxis yAxisId="left" tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false}
                         tickFormatter={fmtVolume} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fill: palette.axis, fontSize: 11 }} width={48}
                         axisLine={false} tickLine={false} tickFormatter={fmtCount} />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
                  <Bar yAxisId="left" dataKey="volume" name="Volume" fill={palette.accent} radius={[2, 2, 0, 0]} />
                  <Bar yAxisId="right" dataKey="voyages" name="Voyages" fill={palette.neutralBar} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>

          {/* ---------- Forecast ---------- */}
          <SectionTitle title="Volume Forecast" note="projected total volume" />
          <Card>
            <ForecastPanel history={volumeSeries} />
          </Card>

          {/* ---------- Trip-day vs port-day ---------- */}
          <SectionTitle title="Time Utilization" note="steaming vs in-port, PBI-sourced" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card title="Trip-Day %" subtitle="share of time spent steaming" className="md:col-span-1">
              <div className="flex items-center justify-center h-32">
                <span className="text-3xl font-bold" style={{ color: palette.accent }}>{fmtPct(kpi.tripDayPct)}</span>
              </div>
            </Card>
            <Card title="Port-Day %" subtitle="share of time spent in port" className="md:col-span-1">
              <div className="flex items-center justify-center h-32">
                <span className="text-3xl font-bold" style={{ color: palette.neutralBar }}>{fmtPct(kpi.portDayPct)}</span>
              </div>
            </Card>
            <Card title="Steaming vs Port" subtitle="stacked split" className="md:col-span-1">
              <div className="h-32 flex items-center">
                <div className="w-full h-6 rounded-sm overflow-hidden flex" style={{ background: 'var(--panel-alt)' }}>
                  <div style={{ width: `${kpi.tripDayPct * 100}%`, background: palette.accent }} title="Trip-Day %" />
                  <div style={{ width: `${kpi.portDayPct * 100}%`, background: palette.neutralBar }} title="Port-Day %" />
                </div>
              </div>
            </Card>
          </div>

          {/* ---------- Top vessels ---------- */}
          <SectionTitle title="Top Vessels" note={`by total volume, ${year}`} />
          <Card>
            {topVessels.length === 0 ? <Empty /> : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead>
                    <tr className="border-b" style={{ color: 'var(--muted)', borderColor: 'var(--border)' }}>
                      <th className="py-1.5 pr-3 font-semibold">#</th>
                      <th className="py-1.5 pr-3 font-semibold">Vessel</th>
                      <th className="py-1.5 pr-3 font-semibold">Sub-Segment</th>
                      <th className="py-1.5 pr-3 font-semibold text-right">DWT</th>
                      <th className="py-1.5 pr-3 font-semibold text-right">Voyages</th>
                      <th className="py-1.5 pr-3 font-semibold text-right">Total Volume</th>
                      <th className="py-1.5 pr-3 font-semibold text-right">Ton-Miles</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topVessels.map((v, i) => (
                      <tr key={v.imo} className="border-b" style={{ borderColor: 'var(--border)' }}>
                        <td className="py-1.5 pr-3" style={{ color: 'var(--faint)' }}>{i + 1}</td>
                        <td className="py-1.5 pr-3 font-medium" style={{ color: 'var(--text)' }}>{v.vessel_name}</td>
                        <td className="py-1.5 pr-3" style={{ color: 'var(--text-2)' }}>{v.sub_segment ?? '—'}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums" style={{ color: 'var(--text-2)' }}>{fmt(v.dwt)}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums" style={{ color: 'var(--text-2)' }}>{fmt(v.voyages)}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums font-semibold" style={{ color: 'var(--text)' }}>{fmtVolume(v.total_volume)}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums" style={{ color: 'var(--text-2)' }}>{fmtVolume(v.ton_miles)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* ---------- Segment comparison ---------- */}
          <SectionTitle title="Segment Comparison" note={`ranked by total volume, ${year}`} />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="All Segments" subtitle="by total volume">
              <BarList rows={segCompare} color={palette.accent} />
            </Card>
            <Card title="Share of Total" subtitle="donut view">
              <Donut rows={segCompare} />
            </Card>
          </div>

          <p className="text-[10px] leading-relaxed" style={{ color: 'var(--faint)' }}>
            Data source: Supabase Materialized Views &middot; Data refreshed periodically &middot; Hover on charts for details.
          </p>
        </>
      )}
    </div>
  )
}
