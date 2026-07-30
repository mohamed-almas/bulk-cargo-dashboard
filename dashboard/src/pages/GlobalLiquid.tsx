import { useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, ComposedChart, Line,
} from 'recharts'
import { supabase } from '../lib/supabase'
import { useQuery, unwrap } from '../lib/useQuery'
import { useTheme } from '../lib/theme'
import {
  KPICard, Card, Spinner, ErrorMsg, PageHeader, SectionTitle, BarList, Select,
  CustomTooltip, fmtVolume, fmtCount, fmtPct, topNWithOthers,
  MIN_YEAR, MAX_YEAR, DEFAULT_YEAR,
} from '../components/ui'
import { Donut, TwoLevelTreemap, FlowSankey, ForecastPanel, type YearPoint } from '../components/charts'
import { NewsInsights } from '../components/NewsInsights'

type YearTotal = {
  year: number
  liquid_volume: number; liquid_voyages: number; liquid_avg_volume_per_voyage: string | number
  total_volume: number; total_voyages: number
}
type MonthTotal = { month_year: string; year: number; month: number; liquid_volume: number; liquid_voyages: number }
type PortCallYearLiquid = { year: number; total_port_calls: number }
type CountryLiquid = { year: number; iso2: string; country_short_name: string; continent: string; liquid_volume: number; liquid_calls: number; rank: number }
type PortLiquid = { year: number; port_id: number; port_name: string; iso2: string; country_short_name: string; continent: string; liquid_volume: number; liquid_calls: number; rank: number }
type CommodityRow = { year: number; commodity_group_short: string; commodity_short: string; volume: number; voyages: number }
type RegionFlow = { year: number; load_region: string; discharge_region: string; total_volume: number; flow_count: number; rank: number }

export default function GlobalLiquid() {
  const { palette } = useTheme()
  const [year, setYear] = useState(String(DEFAULT_YEAR))
  const y = Number(year)

  const q = useQuery(async () => {
    const [byYear, byMonth, portCallsYear, loadCountries, dischCountries, loadPorts, dischPorts, commodities, flows] = await Promise.all([
      supabase.from('xmv_global_volume_voyages_by_year_total').select('year,liquid_volume,liquid_voyages,liquid_avg_volume_per_voyage,total_volume,total_voyages').order('year'),
      supabase.from('xmv_global_volume_voyages_by_month_total').select('month_year,year,month,liquid_volume,liquid_voyages').order('year').order('month'),
      supabase.from('xmv_global_port_calls_by_year_liquid').select('*').eq('year', y),
      supabase.from('xmv_global_countries_by_volume_liquid__load').select('*').eq('year', y).order('rank'),
      supabase.from('xmv_global_countries_by_volume_liquid__discharge').select('*').eq('year', y).order('rank'),
      supabase.from('xmv_global_ports_by_volume_liquid__load').select('*').eq('year', y).order('rank').limit(20),
      supabase.from('xmv_global_ports_by_volume_liquid__discharge').select('*').eq('year', y).order('rank').limit(20),
      supabase.from('xmv_global_commodities_by_volume_liquid').select('*').eq('year', y),
      supabase.from('xmv_global_region_to_region_flows').select('*').eq('year', y).order('rank').limit(30),
    ])
    return {
      byYear: unwrap(byYear) as YearTotal[],
      byMonth: unwrap(byMonth) as MonthTotal[],
      portCallsYear: unwrap(portCallsYear) as PortCallYearLiquid[],
      loadCountries: unwrap(loadCountries) as CountryLiquid[],
      dischCountries: unwrap(dischCountries) as CountryLiquid[],
      loadPorts: unwrap(loadPorts) as PortLiquid[],
      dischPorts: unwrap(dischPorts) as PortLiquid[],
      commodities: unwrap(commodities) as CommodityRow[],
      flows: unwrap(flows) as RegionFlow[],
    }
  }, [y])

  const d = q.data

  const yearRows = useMemo(() => d?.byYear ?? [], [d])
  const cur = useMemo(() => yearRows.find(r => r.year === y), [yearRows, y])
  const prev = useMemo(() => yearRows.find(r => r.year === y - 1), [yearRows, y])
  const yoy = cur && prev && prev.liquid_volume ? cur.liquid_volume / prev.liquid_volume - 1 : null

  const cagr = useMemo(() => {
    const first = yearRows[0]
    const last = yearRows[yearRows.length - 1]
    if (!first || !last || first.year === last.year || first.liquid_volume <= 0) return null
    const years = last.year - first.year
    return (last.liquid_volume / first.liquid_volume) ** (1 / years) - 1
  }, [yearRows])

  const portCallsCur = useMemo(() => d?.portCallsYear.find(r => r.year === y), [d, y])

  const flowRows = useMemo(() => {
    if (!d) return []
    return [...d.flows].sort((a, b) => b.total_volume - a.total_volume).slice(0, 20)
  }, [d])

  const topLoadCountries = useMemo(() => {
    if (!d) return []
    return topNWithOthers(d.loadCountries, 9, c => c.liquid_volume, c => c.country_short_name)
  }, [d])
  const topDischargeCountries = useMemo(() => {
    if (!d) return []
    return topNWithOthers(d.dischCountries, 9, c => c.liquid_volume, c => c.country_short_name)
  }, [d])

  const topLoadPortsList = useMemo(() => {
    if (!d) return []
    return d.loadPorts.map(p => ({ label: p.port_name, value: p.liquid_volume, sub: p.country_short_name }))
  }, [d])
  const topDischargePortsList = useMemo(() => {
    if (!d) return []
    return d.dischPorts.map(p => ({ label: p.port_name, value: p.liquid_volume, sub: p.country_short_name }))
  }, [d])

  const topCommodity = useMemo(() => {
    if (!d || !d.commodities.length) return null
    return [...d.commodities].sort((a, b) => b.volume - a.volume)[0]
  }, [d])
  const topLoadCountry = useMemo(() => (d?.loadCountries.length ? d.loadCountries[0] : null), [d])
  const topDischargeCountry = useMemo(() => (d?.dischCountries.length ? d.dischCountries[0] : null), [d])
  const topLoadPort = useMemo(() => (d?.loadPorts.length ? d.loadPorts[0] : null), [d])
  const topDischargePort = useMemo(() => (d?.dischPorts.length ? d.dischPorts[0] : null), [d])

  const commodityTreemap = useMemo(() => {
    if (!d) return []
    const byGroup = new Map<string, { name: string; children: { name: string; size: number }[] }>()
    for (const c of d.commodities) {
      const g = byGroup.get(c.commodity_group_short) ?? { name: c.commodity_group_short, children: [] }
      g.children.push({ name: c.commodity_short, size: c.volume })
      byGroup.set(c.commodity_group_short, g)
    }
    return Array.from(byGroup.values())
  }, [d])

  const geoTreemap = useMemo(() => {
    if (!d) return []
    const byContinent = new Map<string, { name: string; children: { name: string; size: number }[] }>()
    for (const c of d.loadCountries) {
      const g = byContinent.get(c.continent) ?? { name: c.continent, children: [] }
      g.children.push({ name: c.country_short_name, size: c.liquid_volume })
      byContinent.set(c.continent, g)
    }
    return Array.from(byContinent.values())
  }, [d])

  const sankeyRows = useMemo(() => flowRows.map(f => ({ source: f.load_region, target: f.discharge_region, value: f.total_volume })), [flowRows])

  const annualChartData = useMemo(() => {
    return yearRows.map((r, i) => {
      const prevV = yearRows[i - 1]?.liquid_volume
      const yoyPct = prevV ? ((r.liquid_volume - prevV) / prevV) * 100 : null
      return { year: r.year, volume: r.liquid_volume, yoyPct }
    })
  }, [yearRows])

  const forecastHistory: YearPoint[] = useMemo(() => yearRows.map(r => ({ year: r.year, value: r.liquid_volume })), [yearRows])

  const monthlyChartData = useMemo(() => {
    const rows = (d?.byMonth ?? []).slice(-12)
    return rows.map((r, i, arr) => {
      const prevV = arr[i - 1]?.liquid_volume
      const momPct = prevV ? ((r.liquid_volume - prevV) / prevV) * 100 : null
      return { label: r.month_year, volume: r.liquid_volume, momPct }
    })
  }, [d])

  const seasonalForecast = useMemo(() => {
    const rows = d?.byMonth ?? []
    if (rows.length < 13) return []
    const last12 = rows.slice(-12)
    const prior12 = rows.slice(-24, -12)
    let growth = 0
    if (prior12.length === 12) {
      const sumLast = last12.reduce((s, r) => s + r.liquid_volume, 0)
      const sumPrior = prior12.reduce((s, r) => s + r.liquid_volume, 0)
      growth = sumPrior > 0 ? sumLast / sumPrior - 1 : 0
    }
    return last12.map(r => ({ label: r.month_year + ' +1Y', volume: r.liquid_volume * (1 + growth) }))
  }, [d])

  const insights = useMemo(() => {
    if (!d || !cur) return []
    const out: string[] = []
    if (yoy !== null) {
      out.push(`📈 Liquid Bulk Volume: Global liquid bulk trade reached ${fmtVolume(cur.liquid_volume)} in ${y}, ${yoy >= 0 ? 'up' : 'down'} ${fmtPct(Math.abs(yoy))} YoY.`)
    }
    if (topLoadCountry) {
      const share = cur.liquid_volume ? topLoadCountry.liquid_volume / cur.liquid_volume : 0
      out.push(`🌏 ${topLoadCountry.country_short_name} remains the leading liquid bulk exporter with ${fmtVolume(topLoadCountry.liquid_volume)} loaded (${fmtPct(share)} of global liquid load volume).`)
    }
    if (topDischargeCountry) {
      out.push(`🏗️ ${topDischargeCountry.country_short_name} is the top liquid bulk discharge market, receiving ${fmtVolume(topDischargeCountry.liquid_volume)}.`)
    }
    if (topCommodity) {
      const share = cur.liquid_volume ? topCommodity.volume / cur.liquid_volume : 0
      out.push(`🛢️ ${topCommodity.commodity_short} is the leading liquid bulk commodity at ${fmtVolume(topCommodity.volume)} (${fmtPct(share)} of total liquid volume).`)
    }
    if (topLoadPort) {
      out.push(`⚓ ${topLoadPort.port_name} is the busiest liquid bulk load port globally, handling ${fmtVolume(topLoadPort.liquid_volume)}.`)
    }
    if (topDischargePort) {
      out.push(`🚢 ${topDischargePort.port_name} leads liquid bulk discharges with ${fmtVolume(topDischargePort.liquid_volume)}.`)
    }
    if (cagr !== null) {
      out.push(`📊 Global liquid bulk trade has grown at a ${fmtPct(cagr)} CAGR since ${yearRows[0]?.year}.`)
    }
    if (portCallsCur) {
      out.push(`🛳️ Liquid bulk vessels made ${fmtCount(portCallsCur.total_port_calls)} port calls in ${y}.`)
    }
    return out.slice(0, 8)
  }, [d, cur, yoy, topLoadCountry, topDischargeCountry, topCommodity, topLoadPort, topDischargePort, cagr, y, yearRows, portCallsCur])

  if (q.loading) return <Spinner />
  if (q.error) return <ErrorMsg msg={q.error} />
  if (!d) return null

  const yearOptions = Array.from({ length: MAX_YEAR - MIN_YEAR + 1 }, (_, i) => MAX_YEAR - i)
    .map(v => ({ value: String(v), label: String(v) }))

  return (
    <div className="space-y-5">
      <PageHeader title="Global Liquid Bulk" subtitle="Liquid bulk seaborne trade, worldwide">
        <Select value={year} onChange={setYear} options={yearOptions} placeholder="" />
      </PageHeader>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <KPICard label="Total Volume" value={fmtVolume(cur?.liquid_volume)} accent delta={yoy}
                 sub={cagr !== null ? `CAGR ${fmtPct(cagr)}` : undefined} />
        <KPICard label="Total Port Calls" value={fmtCount(portCallsCur?.total_port_calls)} />
        <KPICard label="Total Voyages" value={fmtCount(cur?.liquid_voyages)}
                 sub={`avg ${fmtVolume(Number(cur?.liquid_avg_volume_per_voyage))}/voyage`} />
        <KPICard label="Top Commodity" value={topCommodity?.commodity_short ?? '—'}
                 sub={topCommodity ? fmtVolume(topCommodity.volume) : undefined} />
        <KPICard label="Top Load Country" value={topLoadCountry?.country_short_name ?? '—'}
                 sub={topLoadCountry ? fmtVolume(topLoadCountry.liquid_volume) : undefined} />
        <KPICard label="Top Discharge Country" value={topDischargeCountry?.country_short_name ?? '—'}
                 sub={topDischargeCountry ? fmtVolume(topDischargeCountry.liquid_volume) : undefined} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPICard label="Top Load Port" value={topLoadPort?.port_name ?? '—'}
                 sub={topLoadPort ? fmtVolume(topLoadPort.liquid_volume) : undefined} />
        <KPICard label="Top Discharge Port" value={topDischargePort?.port_name ?? '—'}
                 sub={topDischargePort ? fmtVolume(topDischargePort.liquid_volume) : undefined} />
      </div>

      <SectionTitle title="Executive Insights" />
      <Card>
        <ul className="space-y-1.5 text-sm" style={{ color: 'var(--text-2)' }}>
          {insights.map((line, i) => <li key={i}>{line}</li>)}
        </ul>
      </Card>

      <NewsInsights scopeType="global" scopeKey="Liquid" year={y} />

      <SectionTitle title="Annual Volume Trend" note={`${MIN_YEAR}–${MAX_YEAR}`} />
      <Card>
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={annualChartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="year" tick={{ fill: palette.axis, fontSize: 11 }} axisLine={{ stroke: palette.grid }} tickLine={false} />
            <YAxis yAxisId="l" tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false} tickFormatter={fmtVolume} />
            <YAxis yAxisId="r" orientation="right" tick={{ fill: palette.axis, fontSize: 11 }} width={40} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
            <Bar yAxisId="l" dataKey="volume" name="Liquid Bulk Volume" fill={palette.liquid} radius={[2, 2, 0, 0]} />
            <Line yAxisId="r" dataKey="yoyPct" name="YoY %" stroke="#D9A400" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>

      <SectionTitle title="Volume Forecast" note={`projected to ${MAX_YEAR + 5}`} />
      <Card>
        <ForecastPanel history={forecastHistory} toYear={MAX_YEAR + 5} />
      </Card>

      <SectionTitle title="Monthly Volume Trend" note="last 12 months" />
      <Card>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={monthlyChartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="label" tick={{ fill: palette.axis, fontSize: 10 }} axisLine={{ stroke: palette.grid }} tickLine={false} />
            <YAxis yAxisId="l" tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false} tickFormatter={fmtVolume} />
            <YAxis yAxisId="r" orientation="right" tick={{ fill: palette.axis, fontSize: 11 }} width={40} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
            <Bar yAxisId="l" dataKey="volume" name="Volume" fill={palette.liquid} radius={[2, 2, 0, 0]} />
            <Line yAxisId="r" dataKey="momPct" name="MoM %" stroke="#D9A400" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>

      <SectionTitle title="12-Month Seasonal Forecast" note="seasonal-naive: same month last year × recent YoY growth rate" />
      <Card>
        {seasonalForecast.length ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={seasonalForecast} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="label" tick={{ fill: palette.axis, fontSize: 10 }} axisLine={{ stroke: palette.grid }} tickLine={false} />
              <YAxis tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false} tickFormatter={fmtVolume} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
              <Bar dataKey="volume" name="Projected Volume" fill="#8B5CF6" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm py-6 text-center" style={{ color: 'var(--dim)' }}>Not enough monthly history to build a seasonal projection.</p>
        )}
      </Card>

      <SectionTitle title="Country Rankings" note={`${y}`} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title="Top 10 Load Countries">
          <Donut rows={topLoadCountries} />
        </Card>
        <Card title="Top 10 Discharge Countries">
          <Donut rows={topDischargeCountries} />
        </Card>
      </div>

      <SectionTitle title="Port Rankings" note={`${y}`} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title="Top 20 Load Ports">
          <BarList rows={topLoadPortsList} maxRows={20} color={palette.liquid} />
        </Card>
        <Card title="Top 20 Discharge Ports">
          <BarList rows={topDischargePortsList} maxRows={20} color={palette.liquid} />
        </Card>
      </div>

      <SectionTitle title="Commodity Hierarchy" note="Type → Group" />
      <Card>
        <TwoLevelTreemap data={commodityTreemap} />
      </Card>

      <SectionTitle title="Geographic Hierarchy" note="Continent → Country" />
      <Card>
        <TwoLevelTreemap data={geoTreemap} />
      </Card>

      <SectionTitle title="Trade Flows" note="Load Region → Discharge Region, top 20 (all-cargo total)" />
      <Card>
        <FlowSankey rows={sankeyRows} />
      </Card>

      <p className="text-[10px] leading-relaxed" style={{ color: 'var(--faint)' }}>
        Data source: Supabase Materialized Views · Data refreshed periodically · Hover on charts for details.
      </p>
    </div>
  )
}
