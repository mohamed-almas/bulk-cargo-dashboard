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

type YearTotal = {
  year: number
  dry_volume: number; dry_voyages: number
  liquid_volume: number; liquid_voyages: number
  total_volume: number; total_voyages: number
  total_avg_volume_per_voyage: string | number
}
type MonthTotal = {
  month_year: string; year: number; month: number
  dry_volume: number; dry_voyages: number
  liquid_volume: number; liquid_voyages: number
  total_volume: number; total_voyages: number
}
type PortCallYear = { year: number; total_port_calls: number; total_unique_ports: number }
type CountrySummary = {
  year: number; country_short_name: string; iso2: string; continent: string
  total_load_volume: number; dry_load_volume: number; liquid_load_volume: number
  total_discharge_volume: number; dry_discharge_volume: number; liquid_discharge_volume: number
  total_volume: number; total_dry_volume: number; total_liquid_volume: number
  total_load_calls: number; total_discharge_calls: number; total_port_calls: number
}
type PortTotal = {
  year: number; port_id: number; port_name: string; iso2: string; country_short_name: string; continent: string
  load_dry_volume: number; load_liquid_volume: number; total_load_volume: number
  discharge_dry_volume: number; discharge_liquid_volume: number; total_discharge_volume: number
  total_dry_volume: number; total_liquid_volume: number; total_volume: number
}
type CommodityRow = { year: number; commodity_type: string; commodity_group_short: string; volume: number; voyages: number }
type RegionFlow = { year: number; load_region: string; discharge_region: string; total_volume: number; flow_count: number; rank: number }

export default function GlobalOverview() {
  const { palette } = useTheme()
  const [year, setYear] = useState(String(DEFAULT_YEAR))
  const y = Number(year)

  const q = useQuery(async () => {
    const [byYear, byMonth, portCallsYear, countries, ports, commodities, flows] = await Promise.all([
      supabase.from('xmv_global_volume_voyages_by_year_total').select('*').order('year'),
      supabase.from('xmv_global_volume_voyages_by_month_total').select('*').order('year').order('month'),
      supabase.from('xmv_global_port_calls_by_year_total').select('year,total_port_calls,total_unique_ports').order('year'),
      supabase.from('xmv_country_summary').select('*').eq('year', y),
      supabase.from('xmv_global_ports_by_volume_total').select('*').eq('year', y),
      supabase.from('xmv_global_commodities_by_volume_total').select('*').eq('year', y),
      supabase.from('xmv_global_region_to_region_flows').select('*').eq('year', y).order('rank').limit(20),
    ])
    return {
      byYear: unwrap(byYear) as YearTotal[],
      byMonth: unwrap(byMonth) as MonthTotal[],
      portCallsYear: unwrap(portCallsYear) as PortCallYear[],
      countries: unwrap(countries) as CountrySummary[],
      ports: unwrap(ports) as PortTotal[],
      commodities: unwrap(commodities) as CommodityRow[],
      flows: unwrap(flows) as RegionFlow[],
    }
  }, [y])

  const d = q.data

  const yearRows = useMemo(() => d?.byYear ?? [], [d])
  const cur = useMemo(() => yearRows.find(r => r.year === y), [yearRows, y])
  const prev = useMemo(() => yearRows.find(r => r.year === y - 1), [yearRows, y])
  const yoy = cur && prev && prev.total_volume ? cur.total_volume / prev.total_volume - 1 : null
  const dryYoy = cur && prev && prev.dry_volume ? cur.dry_volume / prev.dry_volume - 1 : null
  const liquidYoy = cur && prev && prev.liquid_volume ? cur.liquid_volume / prev.liquid_volume - 1 : null

  const cagr = useMemo(() => {
    const first = yearRows[0]
    const last = yearRows[yearRows.length - 1]
    if (!first || !last || first.year === last.year || first.total_volume <= 0) return null
    const years = last.year - first.year
    return (last.total_volume / first.total_volume) ** (1 / years) - 1
  }, [yearRows])

  const portCallsCur = useMemo(() => d?.portCallsYear.find(r => r.year === y), [d, y])

  const topLoadCountries = useMemo(() => {
    if (!d) return []
    return topNWithOthers(d.countries, 9, c => c.total_load_volume, c => c.country_short_name)
  }, [d])
  const topDischargeCountries = useMemo(() => {
    if (!d) return []
    return topNWithOthers(d.countries, 9, c => c.total_discharge_volume, c => c.country_short_name)
  }, [d])

  const topLoadPorts = useMemo(() => {
    if (!d) return []
    return [...d.ports].sort((a, b) => b.total_load_volume - a.total_load_volume).slice(0, 20)
      .map(p => ({ label: p.port_name, value: p.total_load_volume, sub: p.country_short_name }))
  }, [d])
  const topDischargePorts = useMemo(() => {
    if (!d) return []
    return [...d.ports].sort((a, b) => b.total_discharge_volume - a.total_discharge_volume).slice(0, 20)
      .map(p => ({ label: p.port_name, value: p.total_discharge_volume, sub: p.country_short_name }))
  }, [d])

  const topCommodity = useMemo(() => {
    if (!d || !d.commodities.length) return null
    return [...d.commodities].sort((a, b) => b.volume - a.volume)[0]
  }, [d])

  const topLoadCountry = useMemo(() => {
    if (!d || !d.countries.length) return null
    return [...d.countries].sort((a, b) => b.total_load_volume - a.total_load_volume)[0]
  }, [d])
  const topDischargeCountry = useMemo(() => {
    if (!d || !d.countries.length) return null
    return [...d.countries].sort((a, b) => b.total_discharge_volume - a.total_discharge_volume)[0]
  }, [d])
  const topLoadPort = useMemo(() => {
    if (!d || !d.ports.length) return null
    return [...d.ports].sort((a, b) => b.total_load_volume - a.total_load_volume)[0]
  }, [d])
  const topDischargePort = useMemo(() => {
    if (!d || !d.ports.length) return null
    return [...d.ports].sort((a, b) => b.total_discharge_volume - a.total_discharge_volume)[0]
  }, [d])

  const commodityTreemap = useMemo(() => {
    if (!d) return []
    const byType = new Map<string, { name: string; children: { name: string; size: number }[] }>()
    for (const c of d.commodities) {
      const g = byType.get(c.commodity_type) ?? { name: c.commodity_type, children: [] }
      g.children.push({ name: c.commodity_group_short, size: c.volume })
      byType.set(c.commodity_type, g)
    }
    return Array.from(byType.values())
  }, [d])

  const geoTreemap = useMemo(() => {
    if (!d) return []
    const byContinent = new Map<string, { name: string; children: { name: string; size: number }[] }>()
    for (const c of d.countries) {
      const g = byContinent.get(c.continent) ?? { name: c.continent, children: [] }
      g.children.push({ name: c.country_short_name, size: c.total_volume })
      byContinent.set(c.continent, g)
    }
    return Array.from(byContinent.values())
  }, [d])

  const sankeyRows = useMemo(() => {
    if (!d) return []
    return d.flows.map(f => ({ source: f.load_region, target: f.discharge_region, value: f.total_volume }))
  }, [d])

  const annualSeries = useMemo(() => yearRows.map(r => ({
    year: r.year, volume: r.total_volume,
    yoyPct: null as number | null,
  })), [yearRows])
  const annualChartData = useMemo(() => {
    return annualSeries.map((r, i) => {
      const prevV = annualSeries[i - 1]?.volume
      const yoyPct = prevV ? ((r.volume - prevV) / prevV) * 100 : null
      return { ...r, yoyPct }
    })
  }, [annualSeries])

  const forecastHistory: YearPoint[] = useMemo(() => yearRows.map(r => ({ year: r.year, value: r.total_volume })), [yearRows])

  const monthlyChartData = useMemo(() => {
    const rows = (d?.byMonth ?? []).slice(-12)
    return rows.map((r, i, arr) => {
      const prevV = arr[i - 1]?.total_volume
      const momPct = prevV ? ((r.total_volume - prevV) / prevV) * 100 : null
      return { label: r.month_year, volume: r.total_volume, momPct }
    })
  }, [d])

  const seasonalForecast = useMemo(() => {
    const rows = d?.byMonth ?? []
    if (rows.length < 13) return []
    const last12 = rows.slice(-12)
    const prior12 = rows.slice(-24, -12)
    let growth = 0
    if (prior12.length === 12) {
      const sumLast = last12.reduce((s, r) => s + r.total_volume, 0)
      const sumPrior = prior12.reduce((s, r) => s + r.total_volume, 0)
      growth = sumPrior > 0 ? sumLast / sumPrior - 1 : 0
    }
    return last12.map(r => ({ label: r.month_year + ' +1Y', volume: r.total_volume * (1 + growth) }))
  }, [d])

  const insights = useMemo(() => {
    if (!d || !cur) return []
    const out: string[] = []
    if (yoy !== null) {
      out.push(`📈 Trade Volume: Global bulk trade reached ${fmtVolume(cur.total_volume)} in ${y}, ${yoy >= 0 ? 'up' : 'down'} ${fmtPct(Math.abs(yoy))} YoY.`)
    }
    if (topLoadCountry) {
      const share = cur.total_volume ? topLoadCountry.total_load_volume / cur.total_volume : 0
      out.push(`🌏 ${topLoadCountry.country_short_name} remains the leading exporter with ${fmtVolume(topLoadCountry.total_load_volume)} loaded (${fmtPct(share)} of global load volume).`)
    }
    if (topDischargeCountry) {
      out.push(`🏗️ ${topDischargeCountry.country_short_name} is the top discharge market, receiving ${fmtVolume(topDischargeCountry.total_discharge_volume)}.`)
    }
    if (topCommodity) {
      const share = cur.total_volume ? topCommodity.volume / cur.total_volume : 0
      out.push(`📦 ${topCommodity.commodity_group_short} is the leading commodity by volume at ${fmtVolume(topCommodity.volume)} (${fmtPct(share)} of total).`)
    }
    if (dryYoy !== null) {
      out.push(`⛏️ Dry bulk volume ${dryYoy >= 0 ? 'grew' : 'declined'} ${fmtPct(Math.abs(dryYoy))} YoY to ${fmtVolume(cur.dry_volume)}.`)
    }
    if (liquidYoy !== null) {
      out.push(`🛢️ Liquid bulk volume ${liquidYoy >= 0 ? 'grew' : 'declined'} ${fmtPct(Math.abs(liquidYoy))} YoY to ${fmtVolume(cur.liquid_volume)}.`)
    }
    if (topLoadPort) {
      out.push(`⚓ ${topLoadPort.port_name} is the busiest load port globally, handling ${fmtVolume(topLoadPort.total_load_volume)}.`)
    }
    if (cagr !== null) {
      out.push(`📊 Global bulk trade has grown at a ${fmtPct(cagr)} CAGR since ${yearRows[0]?.year}.`)
    }
    return out.slice(0, 8)
  }, [d, cur, yoy, dryYoy, liquidYoy, topLoadCountry, topDischargeCountry, topCommodity, topLoadPort, cagr, y, yearRows])

  if (q.loading) return <Spinner />
  if (q.error) return <ErrorMsg msg={q.error} />
  if (!d) return null

  const yearOptions = Array.from({ length: MAX_YEAR - MIN_YEAR + 1 }, (_, i) => MAX_YEAR - i)
    .map(v => ({ value: String(v), label: String(v) }))

  return (
    <div className="space-y-5">
      <PageHeader title="Global Overview" subtitle="Dry + liquid bulk seaborne trade, worldwide">
        <Select value={year} onChange={setYear} options={yearOptions} placeholder="" />
      </PageHeader>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <KPICard label="Total Volume" value={fmtVolume(cur?.total_volume)} accent delta={yoy}
                 sub={cagr !== null ? `CAGR ${fmtPct(cagr)}` : undefined} />
        <KPICard label="Dry Bulk Volume" value={fmtVolume(cur?.dry_volume)} delta={dryYoy} />
        <KPICard label="Liquid Bulk Volume" value={fmtVolume(cur?.liquid_volume)} delta={liquidYoy} />
        <KPICard label="Total Port Calls" value={fmtCount(portCallsCur?.total_port_calls)}
                 sub={`${fmtCount(portCallsCur?.total_unique_ports)} unique ports`} />
        <KPICard label="Total Voyages" value={fmtCount(cur?.total_voyages)}
                 sub={`avg ${fmtVolume(Number(cur?.total_avg_volume_per_voyage))}/voyage`} />
        <KPICard label="Top Commodity" value={topCommodity?.commodity_group_short ?? '—'}
                 sub={topCommodity ? fmtVolume(topCommodity.volume) : undefined} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPICard label="Top Load Country" value={topLoadCountry?.country_short_name ?? '—'}
                 sub={topLoadCountry ? fmtVolume(topLoadCountry.total_load_volume) : undefined} />
        <KPICard label="Top Discharge Country" value={topDischargeCountry?.country_short_name ?? '—'}
                 sub={topDischargeCountry ? fmtVolume(topDischargeCountry.total_discharge_volume) : undefined} />
        <KPICard label="Top Load Port" value={topLoadPort?.port_name ?? '—'}
                 sub={topLoadPort ? fmtVolume(topLoadPort.total_load_volume) : undefined} />
        <KPICard label="Top Discharge Port" value={topDischargePort?.port_name ?? '—'}
                 sub={topDischargePort ? fmtVolume(topDischargePort.total_discharge_volume) : undefined} />
      </div>

      <SectionTitle title="Executive Insights" />
      <Card>
        <ul className="space-y-1.5 text-sm" style={{ color: 'var(--text-2)' }}>
          {insights.map((line, i) => <li key={i}>{line}</li>)}
        </ul>
      </Card>

      <SectionTitle title="Annual Volume Trend" note={`${MIN_YEAR}–${MAX_YEAR}`} />
      <Card>
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={annualChartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="year" tick={{ fill: palette.axis, fontSize: 11 }} axisLine={{ stroke: palette.grid }} tickLine={false} />
            <YAxis yAxisId="l" tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false} tickFormatter={fmtVolume} />
            <YAxis yAxisId="r" orientation="right" tick={{ fill: palette.axis, fontSize: 11 }} width={40} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
            <Bar yAxisId="l" dataKey="volume" name="Total Volume" fill={palette.accent} radius={[2, 2, 0, 0]} />
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
            <Bar yAxisId="l" dataKey="volume" name="Volume" fill={palette.accent} radius={[2, 2, 0, 0]} />
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
          <BarList rows={topLoadPorts} maxRows={20} />
        </Card>
        <Card title="Top 20 Discharge Ports">
          <BarList rows={topDischargePorts} maxRows={20} />
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

      <SectionTitle title="Trade Flows" note="Load Region → Discharge Region, top 20" />
      <Card>
        <FlowSankey rows={sankeyRows} />
      </Card>

      <p className="text-[10px] leading-relaxed" style={{ color: 'var(--faint)' }}>
        Data source: Supabase Materialized Views · Data refreshed periodically · Hover on charts for details.
      </p>
    </div>
  )
}
