import { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { supabase } from '../lib/supabase'
import { useQuery, unwrap } from '../lib/useQuery'
import { useTheme } from '../lib/theme'
import {
  KPICard, Card, Spinner, ErrorMsg, PageHeader, SectionTitle, Select, BarList,
  CustomTooltip, fmtVolume, fmtCount, YoYBadge, CAGRBadge, topNWithOthers,
  MIN_YEAR, MAX_YEAR, DEFAULT_YEAR,
} from '../components/ui'
import { Donut, FlowSankey, ForecastPanel, type YearPoint } from '../components/charts'
import { NewsInsights } from '../components/NewsInsights'

type CoastalRow = {
  year: number
  coastal_region: string
  total_load_volume: number
  dry_load_volume: number
  liquid_load_volume: number
  total_discharge_volume: number
  dry_discharge_volume: number
  liquid_discharge_volume: number
  total_volume: number
  total_dry_volume: number
  total_liquid_volume: number
  total_port_calls: number
}

type FlowRow = {
  year: number
  load_region: string
  discharge_region: string
  total_volume: number
  flow_count: number
  rank: number
}

export default function CoastalRegion() {
  const { palette } = useTheme()
  const [region, setRegion] = useState('')
  const [year, setYear] = useState(DEFAULT_YEAR)

  // Full summary table — ~144 rows, safe to fetch once and slice client-side.
  const summary = useQuery(async () => {
    const res = await supabase.from('xmv_coastal_region_summary')
      .select('year,coastal_region,total_load_volume,dry_load_volume,liquid_load_volume,total_discharge_volume,dry_discharge_volume,liquid_discharge_volume,total_volume,total_dry_volume,total_liquid_volume,total_port_calls')
      .order('year')
    return unwrap(res) as CoastalRow[]
  }, [])

  const regions = useMemo(() => {
    if (!summary.data) return []
    return Array.from(new Set(summary.data.map(r => r.coastal_region))).sort()
  }, [summary.data])

  // Cap at DEFAULT_YEAR (last full year) rather than the true latest year
  // present, since the current calendar year is partial and would make YoY
  // figures swing misleadingly on first load.
  const latestDataYear = useMemo(() => {
    if (!summary.data?.length) return DEFAULT_YEAR
    const years = summary.data.map(r => r.year)
    const capped = years.filter(y => y <= DEFAULT_YEAR)
    return capped.length ? Math.max(...capped) : Math.max(...years)
  }, [summary.data])

  // Default to the coastal region with the highest total_volume in the latest available year.
  useEffect(() => {
    if (region || !summary.data?.length) return
    const rowsAtLatest = summary.data.filter(r => r.year === latestDataYear)
    const top = [...rowsAtLatest].sort((a, b) => b.total_volume - a.total_volume)[0]
    if (top) setRegion(top.coastal_region)
    setYear(latestDataYear)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary.data, latestDataYear])

  const byYear = useMemo(
    () => (summary.data ?? []).filter(r => r.coastal_region === region).sort((a, b) => a.year - b.year),
    [summary.data, region],
  )

  const current = byYear.find(r => r.year === year)
  const prevYear = byYear.find(r => r.year === year - 1)
  const yoy = current && prevYear && prevYear.total_volume
    ? (current.total_volume - prevYear.total_volume) / prevYear.total_volume
    : null

  const cagr = useMemo(() => {
    if (byYear.length < 2) return null
    const first = byYear[0]
    const last = byYear[byYear.length - 1]
    const years = last.year - first.year
    if (years <= 0 || !first.total_volume) return null
    return (last.total_volume / first.total_volume) ** (1 / years) - 1
  }, [byYear])

  const allAtYear = useMemo(
    () => (summary.data ?? []).filter(r => r.year === year).sort((a, b) => b.total_volume - a.total_volume),
    [summary.data, year],
  )

  const ranking = useMemo(
    () => topNWithOthers(allAtYear, 12, r => r.total_volume, r => r.coastal_region),
    [allAtYear],
  )

  const history: YearPoint[] = useMemo(
    () => byYear.map(r => ({ year: r.year, value: r.total_volume })),
    [byYear],
  )

  // Region-to-region flows touching this coastal region (Clarksons coastal-region granularity —
  // no matview joins coastal_region to country or port, so partner-region flows are the finest
  // geographic breakdown available for this level; see note below).
  const q = useQuery(async () => {
    const res = await supabase.from('xmv_global_region_to_region_flows')
      .select('year,load_region,discharge_region,total_volume,flow_count,rank')
      .eq('year', year)
      .or(`load_region.eq.${region},discharge_region.eq.${region}`)
      .order('total_volume', { ascending: false })
      .limit(500)
    const flows = unwrap(res) as FlowRow[]

    const byPartner = new Map<string, number>()
    for (const f of flows) {
      const partner = f.load_region === region ? f.discharge_region : f.load_region
      byPartner.set(partner, (byPartner.get(partner) ?? 0) + f.total_volume)
    }
    const topPartners = topNWithOthers(
      Array.from(byPartner.entries()),
      10,
      ([, v]) => v,
      ([name]) => name,
    )

    return { flows, topPartners }
  }, [region, year], { skip: !region })

  const sankeyRows = useMemo(() => {
    if (!q.data) return []
    const grouped = new Map<string, number>()
    for (const f of q.data.flows) {
      const key = `${f.load_region} ${f.discharge_region}`
      grouped.set(key, (grouped.get(key) ?? 0) + f.total_volume)
    }
    return Array.from(grouped.entries()).map(([key, value]) => {
      const [source, target] = key.split(' ')
      return { source, target, value }
    })
  }, [q.data])

  const trendData = byYear.map(r => ({
    year: r.year,
    Load: r.total_load_volume,
    Discharge: r.total_discharge_volume,
  }))

  const loading = summary.loading
  const error = summary.error

  return (
    <div className="space-y-5">
      <PageHeader title="Coastal Region Overview" subtitle={region ? `${region} · ${year}` : undefined}>
        <Select
          value={region} onChange={setRegion} placeholder="Select coastal region..."
          options={regions.map(r => ({ value: r, label: r }))}
        />
        <Select
          value={String(year)} onChange={v => setYear(Number(v))} placeholder=""
          options={Array.from({ length: MAX_YEAR - MIN_YEAR + 1 }, (_, i) => MAX_YEAR - i)
            .map(y => ({ value: String(y), label: String(y) }))}
        />
      </PageHeader>

      {loading ? <Spinner /> : error ? <ErrorMsg msg={error} /> : !region ? null : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KPICard label="Total Volume" value={fmtVolume(current?.total_volume)} accent />
            <KPICard label="Load Volume" value={fmtVolume(current?.total_load_volume)} />
            <KPICard label="Discharge Volume" value={fmtVolume(current?.total_discharge_volume)} />
            <KPICard label="Total Port Calls" value={fmtCount(current?.total_port_calls)} />
            <KPICard label="Dry Volume" value={fmtVolume(current?.total_dry_volume)} />
            <KPICard label="Liquid Volume" value={fmtVolume(current?.total_liquid_volume)} />
            <KPICard label="YoY Growth" value={<YoYBadge value={yoy} />} />
            <KPICard label="CAGR" value={<CAGRBadge value={cagr} />} />
          </div>

          <NewsInsights scopeType="coastal_region" scopeKey={region} year={year} />

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Annual Volume Trend" subtitle="load vs. discharge, by year">
              {trendData.length === 0 ? (
                <div className="text-sm text-center py-8" style={{ color: 'var(--dim)' }}>No data</div>
              ) : (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={trendData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <XAxis dataKey="year" tick={{ fill: palette.axis, fontSize: 11 }} axisLine={{ stroke: palette.grid }} tickLine={false} />
                    <YAxis tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false} tickFormatter={fmtVolume} />
                    <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
                    <Bar dataKey="Load" fill={palette.accent} radius={[3, 3, 0, 0]} />
                    <Bar dataKey="Discharge" fill={palette.neutralBar} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>

            <Card title="Volume Forecast" subtitle="projected total volume">
              <ForecastPanel history={history} />
            </Card>
          </div>

          <SectionTitle title="Trade Flows" note={`${region} · ${year}`} />
          <Card subtitle="volume flowing between this coastal region and its trading partner regions">
            {q.loading ? <Spinner /> : q.error ? <ErrorMsg msg={q.error} /> : (
              <FlowSankey rows={sankeyRows} />
            )}
          </Card>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Top Partner Regions" subtitle={`trading with ${region} · ${year}`}>
              {q.loading ? <Spinner /> : q.error ? <ErrorMsg msg={q.error} /> : (
                <BarList rows={q.data?.topPartners ?? []} />
              )}
            </Card>

            <Card title="All Coastal Regions" subtitle={`ranked by total volume · ${year}`}>
              <Donut rows={ranking} />
            </Card>
          </div>

          <p className="text-[10px] text-center pt-2" style={{ color: 'var(--faint)' }}>
            Data source: Supabase Materialized Views · Data refreshed periodically · Hover on charts for details.
          </p>
        </>
      )}
    </div>
  )
}
