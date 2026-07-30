import { useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { supabase } from '../lib/supabase'
import { useQuery, unwrap, fetchAll } from '../lib/useQuery'
import { useTheme } from '../lib/theme'
import {
  KPICard, Card, Spinner, ErrorMsg, PageHeader, SectionTitle, Select, BarList,
  CustomTooltip, fmtVolume, fmtCount, fmtPct, topNWithOthers,
  MIN_YEAR, MAX_YEAR, DEFAULT_YEAR,
} from '../components/ui'
import { Donut, ForecastPanel, type YearPoint } from '../components/charts'
import { NewsInsights } from '../components/NewsInsights'

// ---------------------------------------------------------------------------
// Row shapes for the matviews used on this page.
// ---------------------------------------------------------------------------

type GlobalPortRow = {
  year: number
  port_id: number
  port_name: string
  iso2: string | null
  country_short_name: string | null
  continent: string | null
  load_dry_volume: number
  load_liquid_volume: number
  total_load_volume: number
  discharge_dry_volume: number
  discharge_liquid_volume: number
  total_discharge_volume: number
  total_dry_volume: number
  total_liquid_volume: number
  total_volume: number
  total_load_calls: number
  total_discharge_calls: number
  total_calls: number
}

type PortPairRow = {
  year: number
  load_port_id: number
  load_port_name: string
  load_country: string
  discharge_port_id: number
  discharge_port_name: string
  discharge_country: string
  cargo_bucket: string
  total_volume: number
  voyages: number
}

type GlobalYearRow = {
  year: number
  dry_volume: number
  liquid_volume: number
  total_volume: number
  total_voyages: number
}

export default function Port() {
  const { palette } = useTheme()
  const [portId, setPortId] = useState<string>('')
  const [year, setYear] = useState<number>(DEFAULT_YEAR)

  // Full port roster + volumes for the latest full year — drives the dropdown
  // and the default "biggest port" selection. Uses DEFAULT_YEAR rather than
  // MAX_YEAR since the current calendar year is partial.
  const latestPorts = useQuery(async () => {
    return fetchAll<GlobalPortRow>((from, to) =>
      supabase.from('xmv_global_ports_by_volume_total')
        .select('year,port_id,port_name,iso2,country_short_name,continent,total_volume,total_load_volume,total_discharge_volume,total_dry_volume,total_liquid_volume,total_load_calls,total_discharge_calls,total_calls,load_dry_volume,load_liquid_volume,discharge_dry_volume,discharge_liquid_volume')
        .eq('year', DEFAULT_YEAR)
        .order('port_id')
        .range(from, to))
  }, [])

  const sortedByName = useMemo(
    () => [...(latestPorts.data ?? [])].sort((a, b) => a.port_name.localeCompare(b.port_name)),
    [latestPorts.data])

  const defaultPortId = useMemo(() => {
    if (!latestPorts.data?.length) return ''
    return [...latestPorts.data].sort((a, b) => b.total_volume - a.total_volume)[0].port_id.toString()
  }, [latestPorts.data])

  const activePortId = portId || defaultPortId
  const pid = activePortId ? Number(activePortId) : null

  // This port's full year history from the global ports matview — light
  // (one row per year) and already carries every KPI we need.
  const history = useQuery(async () => {
    if (!pid) return []
    const res = await supabase.from('xmv_global_ports_by_volume_total')
      .select('year,port_id,port_name,iso2,country_short_name,continent,total_volume,total_load_volume,total_discharge_volume,total_dry_volume,total_liquid_volume,total_load_calls,total_discharge_calls,total_calls,load_dry_volume,load_liquid_volume,discharge_dry_volume,discharge_liquid_volume')
      .eq('port_id', pid).gte('year', MIN_YEAR).lte('year', MAX_YEAR).order('year')
    return unwrap(res) as GlobalPortRow[]
  }, [pid], { skip: !pid })

  const selectedRow = useMemo(
    () => history.data?.find(r => r.year === year) ?? null,
    [history.data, year])

  // All ports for the selected year — used for the market-share KPI, rank,
  // and the "All Ports" ranking BarList.
  const yearPorts = useQuery(async () => {
    return fetchAll<GlobalPortRow>((from, to) =>
      supabase.from('xmv_global_ports_by_volume_total')
        .select('year,port_id,port_name,iso2,country_short_name,continent,total_volume,total_load_volume,total_discharge_volume,total_dry_volume,total_liquid_volume,total_load_calls,total_discharge_calls,total_calls,load_dry_volume,load_liquid_volume,discharge_dry_volume,discharge_liquid_volume')
        .eq('year', year)
        .order('port_id')
        .range(from, to))
  }, [year])

  const rank = useMemo(() => {
    if (!yearPorts.data?.length || !pid) return null
    const sorted = [...yearPorts.data].sort((a, b) => b.total_volume - a.total_volume)
    const idx = sorted.findIndex(r => r.port_id === pid)
    return idx >= 0 ? idx + 1 : null
  }, [yearPorts.data, pid])

  const globalTotal = useMemo(
    () => (yearPorts.data ?? []).reduce((s, r) => s + r.total_volume, 0),
    [yearPorts.data])

  const marketShare = selectedRow && globalTotal > 0 ? selectedRow.total_volume / globalTotal : null

  // Global yearly totals — small table, used only for context/CAGR-free share.
  const globalYearly = useQuery(async () => {
    const res = await supabase.from('xmv_global_volume_voyages_by_year_total')
      .select('year,dry_volume,liquid_volume,total_volume,total_voyages')
      .order('year')
    return unwrap(res) as GlobalYearRow[]
  }, [])

  // Partner pairs for this port at this port+year, both directions.
  const pairs = useQuery(async () => {
    if (!pid) return { asLoad: [] as PortPairRow[], asDischarge: [] as PortPairRow[] }
    const [load, disch] = await Promise.all([
      supabase.from('xmv_port_pairs')
        .select('year,load_port_id,load_port_name,load_country,discharge_port_id,discharge_port_name,discharge_country,cargo_bucket,total_volume,voyages')
        .eq('load_port_id', pid).eq('year', year).limit(1000),
      supabase.from('xmv_port_pairs')
        .select('year,load_port_id,load_port_name,load_country,discharge_port_id,discharge_port_name,discharge_country,cargo_bucket,total_volume,voyages')
        .eq('discharge_port_id', pid).eq('year', year).limit(1000),
    ])
    return { asLoad: unwrap(load) as PortPairRow[], asDischarge: unwrap(disch) as PortPairRow[] }
  }, [pid, year], { skip: !pid })

  const topPartnerPorts = useMemo(() => {
    const byPort = new Map<string, number>()
    for (const r of pairs.data?.asLoad ?? []) {
      byPort.set(r.discharge_port_name, (byPort.get(r.discharge_port_name) ?? 0) + r.total_volume)
    }
    for (const r of pairs.data?.asDischarge ?? []) {
      byPort.set(r.load_port_name, (byPort.get(r.load_port_name) ?? 0) + r.total_volume)
    }
    return topNWithOthers(Array.from(byPort.entries()), 12, r => r[1], r => r[0])
  }, [pairs.data])

  const topPartnerCountries = useMemo(() => {
    const byCountry = new Map<string, number>()
    for (const r of pairs.data?.asLoad ?? []) {
      byCountry.set(r.discharge_country, (byCountry.get(r.discharge_country) ?? 0) + r.total_volume)
    }
    for (const r of pairs.data?.asDischarge ?? []) {
      byCountry.set(r.load_country, (byCountry.get(r.load_country) ?? 0) + r.total_volume)
    }
    return topNWithOthers(Array.from(byCountry.entries()), 12, r => r[1], r => r[0])
  }, [pairs.data])

  const trendData = useMemo(
    () => (history.data ?? []).map(r => ({
      year: r.year, Load: r.total_load_volume, Discharge: r.total_discharge_volume,
    })),
    [history.data])

  const forecastHistory: YearPoint[] = useMemo(
    () => (history.data ?? []).map(r => ({ year: r.year, value: r.total_volume })),
    [history.data])

  const dryLiquidRows = useMemo(() => {
    if (!selectedRow) return []
    return [
      { label: 'Dry', value: selectedRow.total_dry_volume },
      { label: 'Liquid', value: selectedRow.total_liquid_volume },
    ].filter(r => r.value > 0)
  }, [selectedRow])

  const allPortsRanking = useMemo(() => {
    return [...(yearPorts.data ?? [])]
      .sort((a, b) => b.total_volume - a.total_volume)
      .slice(0, 20)
      .map(r => ({ label: `${r.port_name}${r.country_short_name ? ` (${r.country_short_name})` : ''}`, value: r.total_volume }))
  }, [yearPorts.data])

  const loading = latestPorts.loading || history.loading
  const error = latestPorts.error || history.error || yearPorts.error || pairs.error || globalYearly.error

  return (
    <div className="space-y-5">
      <PageHeader
        title={selectedRow ? `${selectedRow.port_name} — Port Overview` : 'Port Overview'}
        subtitle={selectedRow
          ? [selectedRow.country_short_name, selectedRow.continent].filter(Boolean).join(' · ')
          : undefined}
      >
        <Select
          value={activePortId}
          onChange={setPortId}
          placeholder=""
          options={sortedByName.map(p => ({
            value: p.port_id.toString(),
            label: `${p.port_name} — ${p.country_short_name ?? p.iso2 ?? ''}`,
          }))}
        />
        <Select
          value={String(year)}
          onChange={v => setYear(Number(v))}
          placeholder=""
          options={Array.from({ length: MAX_YEAR - MIN_YEAR + 1 }, (_, i) => MAX_YEAR - i)
            .map(y => ({ value: String(y), label: String(y) }))}
        />
      </PageHeader>

      {loading ? <Spinner /> : error ? <ErrorMsg msg={error} /> : !selectedRow ? (
        <Card><div className="text-sm text-center py-8" style={{ color: 'var(--dim)' }}>
          No data for this port in {year}.
        </div></Card>
      ) : (
        <>
          {/* ---------- KPIs ---------- */}
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
            <KPICard label="Total Volume" value={fmtVolume(selectedRow.total_volume)} accent sub={`${year} · tonnes`} />
            <KPICard label="Load Volume" value={fmtVolume(selectedRow.total_load_volume)} />
            <KPICard label="Discharge Volume" value={fmtVolume(selectedRow.total_discharge_volume)} />
            <KPICard label="Total Port Calls" value={fmtCount(selectedRow.total_calls)} sub="voyages" />
            <KPICard label="Load Calls" value={fmtCount(selectedRow.total_load_calls)} />
            <KPICard label="Discharge Calls" value={fmtCount(selectedRow.total_discharge_calls)} />
            <KPICard label="Dry Volume" value={fmtVolume(selectedRow.total_dry_volume)} />
            <KPICard label="Liquid Volume" value={fmtVolume(selectedRow.total_liquid_volume)} />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KPICard label="Global Market Share" value={marketShare !== null ? fmtPct(marketShare) : '—'}
                     accent sub={`of ${fmtVolume(globalTotal)} t worldwide, ${year}`} />
            <KPICard label="Global Rank" value={rank ? `#${rank}` : '—'} sub={`of ${fmt2(yearPorts.data?.length)} ports`} />
            <KPICard label="Dry Share" value={selectedRow.total_volume > 0
              ? fmtPct(selectedRow.total_dry_volume / selectedRow.total_volume) : '—'} />
            <KPICard label="Liquid Share" value={selectedRow.total_volume > 0
              ? fmtPct(selectedRow.total_liquid_volume / selectedRow.total_volume) : '—'} />
          </div>

          <NewsInsights scopeType="port" scopeKey={portId} year={year} />

          {/* ---------- Trend ---------- */}
          <SectionTitle title="Annual Volume Trend" note="load vs discharge, by year" />
          <Card>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={trendData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="year" tick={{ fill: palette.axis, fontSize: 11 }}
                       axisLine={{ stroke: palette.grid }} tickLine={false} />
                <YAxis tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false}
                       tickLine={false} tickFormatter={fmtVolume} />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
                <Bar dataKey="Load" fill={palette.accent} radius={[2, 2, 0, 0]} />
                <Bar dataKey="Discharge" fill={palette.neutralBar} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>

          {/* ---------- Forecast ---------- */}
          <SectionTitle title="Volume Forecast" note="projected total port volume" />
          <Card>
            <ForecastPanel history={forecastHistory} />
          </Card>

          {/* ---------- Partners ---------- */}
          <SectionTitle title="Partner Analysis" note={`${year} · load + discharge combined`} />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Top Partner Ports" subtitle="by combined cargo volume">
              {pairs.loading ? <Spinner /> : <BarList rows={topPartnerPorts} maxRows={12} />}
            </Card>
            <Card title="Top Partner Countries" subtitle="by combined cargo volume">
              {pairs.loading ? <Spinner /> : <BarList rows={topPartnerCountries} maxRows={12} color={palette.dry} />}
            </Card>
          </div>

          {/* ---------- Dry vs Liquid ---------- */}
          <SectionTitle title="Dry vs Liquid Split" note={`${year} total volume`} />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Cargo Type Mix">
              <Donut rows={dryLiquidRows} height={220} />
            </Card>
            <div className="grid grid-cols-2 gap-3 content-center">
              <KPICard label="Dry Bulk Volume" value={fmtVolume(selectedRow.total_dry_volume)} sub="tonnes" />
              <KPICard label="Liquid Bulk Volume" value={fmtVolume(selectedRow.total_liquid_volume)} sub="tonnes" />
            </div>
          </div>

          {/* ---------- All Ports ranking ---------- */}
          <SectionTitle title="All Ports" note={`top ports worldwide by volume, ${year}`} />
          <Card subtitle={`${selectedRow.port_name} highlighted at rank ${rank ?? '—'}`}>
            {yearPorts.loading ? <Spinner /> : <BarList rows={allPortsRanking} maxRows={20} />}
          </Card>

          <p className="text-[10px] leading-relaxed pt-2" style={{ color: 'var(--faint)' }}>
            Data source: Supabase Materialized Views · Data refreshed periodically · Hover on charts for details.
          </p>
        </>
      )}
    </div>
  )
}

function fmt2(n: number | undefined | null): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString()
}
