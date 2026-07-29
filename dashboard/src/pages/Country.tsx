import { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { supabase } from '../lib/supabase'
import { useQuery, unwrap, fetchAll } from '../lib/useQuery'
import { useTheme } from '../lib/theme'
import {
  KPICard, Card, Spinner, ErrorMsg, Empty, PageHeader, SectionTitle, Select, BarList,
  CustomTooltip, fmt, fmtVolume, topNWithOthers,
  MIN_YEAR, MAX_YEAR, DEFAULT_YEAR,
} from '../components/ui'
import { ForecastPanel, type YearPoint } from '../components/charts'

type SummaryRow = {
  year: number
  country_short_name: string
  iso2: string | null
  continent: string | null
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
  total_dry_port_calls: number
  total_liquid_port_calls: number
}

type PortRow = { port_name: string; country_short_name: string; dry_volume?: number; liquid_volume?: number; rank: number }
type CommodityRow = { country_name: string; commodity_group: string; direction: string; total_volume: number }

const YEAR_OPTIONS = Array.from({ length: MAX_YEAR - MIN_YEAR + 1 }, (_, i) => MAX_YEAR - i)

export default function Country() {
  const { palette } = useTheme()
  const [country, setCountry] = useState('')
  const [year, setYear] = useState(DEFAULT_YEAR)

  // Distinct list of countries, and a reasonable default (largest total_volume in latest year).
  const countries = useQuery(async () => {
    const rows = await fetchAll<{ country_short_name: string; total_volume: number; year: number }>(
      (from, to) => supabase.from('xmv_country_summary')
        .select('country_short_name,total_volume,year')
        .order('country_short_name').order('year')
        .range(from, to),
      50000,
    )
    const names = Array.from(new Set(rows.map(r => r.country_short_name).filter(Boolean))).sort()
    const latestYear = Math.max(...rows.map(r => r.year))
    const top = rows.filter(r => r.year === latestYear).sort((a, b) => b.total_volume - a.total_volume)[0]
    return { names, defaultCountry: top?.country_short_name ?? names[0] ?? '' }
  }, [])

  useEffect(() => {
    if (!country && countries.data?.defaultCountry) setCountry(countries.data.defaultCountry)
  }, [countries.data, country])

  // All-year summary for the selected country (KPIs, trend, forecast).
  const summary = useQuery(async () => {
    const res = await supabase.from('xmv_country_summary')
      .select('*')
      .eq('country_short_name', country)
      .order('year')
    return unwrap(res) as SummaryRow[]
  }, [country], { skip: !country })

  // Top ports, top commodities, and partner countries for the selected country + year.
  const detail = useQuery(async () => {
    const [dryLoadPorts, dryDischargePorts, liqLoadPorts, liqDischargePorts, dryCommodities, liquidCommodities] =
      await Promise.all([
        supabase.from('xmv_global_ports_by_volume_dry__load')
          .select('port_name,country_short_name,dry_volume,rank')
          .eq('country_short_name', country).eq('year', year).order('rank').limit(15),
        supabase.from('xmv_global_ports_by_volume_dry__discharge')
          .select('port_name,country_short_name,dry_volume,rank')
          .eq('country_short_name', country).eq('year', year).order('rank').limit(15),
        supabase.from('xmv_global_ports_by_volume_liquid__load')
          .select('port_name,country_short_name,liquid_volume,rank')
          .eq('country_short_name', country).eq('year', year).order('rank').limit(15),
        supabase.from('xmv_global_ports_by_volume_liquid__discharge')
          .select('port_name,country_short_name,liquid_volume,rank')
          .eq('country_short_name', country).eq('year', year).order('rank').limit(15),
        supabase.from('xmv_country_commodities_by_volume_dry')
          .select('country_name,commodity_group,direction,total_volume')
          .eq('country_name', country).eq('year', year).order('total_volume', { ascending: false }).limit(40),
        supabase.from('xmv_country_commodities_by_volume_liquid')
          .select('country_name,commodity_group,direction,total_volume')
          .eq('country_name', country).eq('year', year).order('total_volume', { ascending: false }).limit(40),
      ])

    // Partner countries: xmv_port_pairs can be huge per country, so we take the
    // largest individual port-pair flows (ordered by total_volume) as a proxy
    // ranking rather than paging the entire slice.
    const [loadPairs, dischargePairs] = await Promise.all([
      supabase.from('xmv_port_pairs')
        .select('discharge_country,total_volume')
        .eq('load_country', country).eq('year', year)
        .order('total_volume', { ascending: false }).limit(1000),
      supabase.from('xmv_port_pairs')
        .select('load_country,total_volume')
        .eq('discharge_country', country).eq('year', year)
        .order('total_volume', { ascending: false }).limit(1000),
    ])

    return {
      dryLoadPorts: unwrap(dryLoadPorts) as PortRow[],
      dryDischargePorts: unwrap(dryDischargePorts) as PortRow[],
      liqLoadPorts: unwrap(liqLoadPorts) as PortRow[],
      liqDischargePorts: unwrap(liqDischargePorts) as PortRow[],
      dryCommodities: unwrap(dryCommodities) as CommodityRow[],
      liquidCommodities: unwrap(liquidCommodities) as CommodityRow[],
      loadPairs: (unwrap(loadPairs) as { discharge_country: string; total_volume: number }[]),
      dischargePairs: (unwrap(dischargePairs) as { load_country: string; total_volume: number }[]),
    }
  }, [country, year], { skip: !country })

  const row = useMemo(() => summary.data?.find(r => r.year === year), [summary.data, year])

  const byYear = summary.data ?? []

  const totalVolumeSeries: YearPoint[] = useMemo(
    () => byYear.map(r => ({ year: r.year, value: r.total_volume })), [byYear])

  const loadDischargeSeries = useMemo(
    () => byYear.map(r => ({
      year: r.year, Load: r.total_load_volume, Discharge: r.total_discharge_volume,
    })), [byYear])

  const partnerLoad = useMemo(() => {
    const m = new Map<string, number>()
    for (const p of detail.data?.loadPairs ?? []) {
      if (!p.discharge_country) continue
      m.set(p.discharge_country, (m.get(p.discharge_country) ?? 0) + p.total_volume)
    }
    return topNWithOthers(Array.from(m.entries()), 10, ([, v]) => v, ([k]) => k)
  }, [detail.data])

  const partnerDischarge = useMemo(() => {
    const m = new Map<string, number>()
    for (const p of detail.data?.dischargePairs ?? []) {
      if (!p.load_country) continue
      m.set(p.load_country, (m.get(p.load_country) ?? 0) + p.total_volume)
    }
    return topNWithOthers(Array.from(m.entries()), 10, ([, v]) => v, ([k]) => k)
  }, [detail.data])

  const dryLoadCommodities = useMemo(
    () => (detail.data?.dryCommodities ?? []).filter(c => c.direction === 'Load')
      .map(c => ({ label: c.commodity_group, value: c.total_volume })), [detail.data])
  const dryDischargeCommodities = useMemo(
    () => (detail.data?.dryCommodities ?? []).filter(c => c.direction === 'Discharge')
      .map(c => ({ label: c.commodity_group, value: c.total_volume })), [detail.data])
  const liquidLoadCommodities = useMemo(
    () => (detail.data?.liquidCommodities ?? []).filter(c => c.direction === 'Load')
      .map(c => ({ label: c.commodity_group, value: c.total_volume })), [detail.data])
  const liquidDischargeCommodities = useMemo(
    () => (detail.data?.liquidCommodities ?? []).filter(c => c.direction === 'Discharge')
      .map(c => ({ label: c.commodity_group, value: c.total_volume })), [detail.data])

  // Executive insights — computed live from the fetched summary/detail data.
  const insights = useMemo(() => {
    if (!row) return []
    const out: string[] = []
    const netVol = row.total_load_volume - row.total_discharge_volume
    if (row.total_load_volume > 0 || row.total_discharge_volume > 0) {
      out.push(
        netVol > 0
          ? `${country} is a net exporter in ${year}: load volume exceeds discharge volume by ${fmtVolume(Math.abs(netVol))} tonnes.`
          : `${country} is a net importer in ${year}: discharge volume exceeds load volume by ${fmtVolume(Math.abs(netVol))} tonnes.`
      )
    }
    if (row.total_volume > 0) {
      const dryShare = row.total_dry_volume / row.total_volume
      out.push(`Dry bulk accounts for ${(dryShare * 100).toFixed(1)}% of total volume, liquid bulk for ${((1 - dryShare) * 100).toFixed(1)}%.`)
    }
    const prev = byYear.find(r => r.year === year - 1)
    if (prev && prev.total_volume > 0) {
      const yoy = (row.total_volume - prev.total_volume) / prev.total_volume
      out.push(`Total volume moved ${yoy >= 0 ? 'up' : 'down'} ${Math.abs(yoy * 100).toFixed(1)}% year-on-year versus ${year - 1}.`)
    }
    const first = byYear[0]
    const last = byYear[byYear.length - 1]
    if (first && last && first.year !== last.year && first.total_volume > 0) {
      const years = last.year - first.year
      const cagr = (last.total_volume / first.total_volume) ** (1 / years) - 1
      out.push(`${cagr >= 0 ? 'Growth' : 'Decline'} CAGR of ${(cagr * 100).toFixed(1)}% across ${first.year}–${last.year}.`)
    }
    if (row.total_port_calls > 0) {
      out.push(`${fmt(row.total_port_calls)} total port calls recorded in ${year}, averaging ${fmt(row.total_volume / Math.max(1, row.total_port_calls))} tonnes per call.`)
    }
    const topDryPort = detail.data?.dryLoadPorts[0]
    if (topDryPort) {
      out.push(`Top dry-bulk loading port is ${topDryPort.port_name}, handling ${fmtVolume(topDryPort.dry_volume)} tonnes.`)
    }
    return out
  }, [row, byYear, country, year, detail.data])

  return (
    <div className="space-y-5">
      <PageHeader
        title={country ? `${country} — Country Overview` : 'Country Overview'}
        subtitle={row ? [row.continent, row.iso2].filter(Boolean).join(' · ') : undefined}
      >
        <Select value={country} onChange={setCountry} placeholder=""
                options={(countries.data?.names ?? []).map(n => ({ value: n, label: n }))} />
        <Select value={String(year)} onChange={v => setYear(Number(v))} placeholder=""
                options={YEAR_OPTIONS.map(y => ({ value: String(y), label: String(y) }))} />
      </PageHeader>

      {countries.loading || summary.loading ? <Spinner />
       : summary.error ? <ErrorMsg msg={summary.error} />
       : !country ? null
       : !row ? <Card><Empty msg={`No data for ${country} in ${year}.`} /></Card>
       : (
        <>
          {/* ---------- KPI grid ---------- */}
          <SectionTitle title="Key Metrics" note={String(year)} />
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
            <KPICard label="Total Volume" value={fmtVolume(row.total_volume)} accent />
            <KPICard label="Load Volume" value={fmtVolume(row.total_load_volume)} />
            <KPICard label="Discharge Volume" value={fmtVolume(row.total_discharge_volume)} />
            <KPICard label="Total Port Calls" value={fmt(row.total_port_calls)} />
            <KPICard label="Dry Volume" value={fmtVolume(row.total_dry_volume)} />
            <KPICard label="Load Dry Volume" value={fmtVolume(row.dry_load_volume)} />
            <KPICard label="Discharge Dry Volume" value={fmtVolume(row.dry_discharge_volume)} />
            <KPICard label="Dry Port Calls" value={fmt(row.total_dry_port_calls)} />
            <KPICard label="Liquid Volume" value={fmtVolume(row.total_liquid_volume)} />
            <KPICard label="Load Liquid Volume" value={fmtVolume(row.liquid_load_volume)} />
            <KPICard label="Discharge Liquid Volume" value={fmtVolume(row.liquid_discharge_volume)} />
            <KPICard label="Liquid Port Calls" value={fmt(row.total_liquid_port_calls)} />
          </div>

          {/* ---------- Executive insights ---------- */}
          <Card title="Executive Insights">
            {insights.length === 0 ? <Empty /> : (
              <ul className="space-y-1.5 text-xs leading-relaxed" style={{ color: 'var(--text-2)' }}>
                {insights.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span style={{ color: 'var(--accent)' }}>&bull;</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* ---------- Annual trend ---------- */}
          <SectionTitle title="Annual Volume Trend" note="load vs discharge, all years" />
          <Card>
            {loadDischargeSeries.length === 0 ? <Empty /> : (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={loadDischargeSeries} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="year" tick={{ fill: palette.axis, fontSize: 11 }}
                         axisLine={{ stroke: palette.grid }} tickLine={false} />
                  <YAxis tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false}
                         tickFormatter={fmtVolume} />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
                  <Bar dataKey="Load" fill={palette.dry} radius={[2, 2, 0, 0]} />
                  <Bar dataKey="Discharge" fill={palette.liquid} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>

          {/* ---------- Forecast ---------- */}
          <SectionTitle title="Volume Forecast" note="projected total volume" />
          <Card>
            <ForecastPanel history={totalVolumeSeries} />
          </Card>

          {/* ---------- Top ports ---------- */}
          <SectionTitle title="Top Ports" note={String(year)} />
          {detail.loading ? <Spinner /> : detail.error ? <ErrorMsg msg={detail.error} /> : (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <Card title="Top Dry Bulk Ports — Load">
                <BarList rows={(detail.data?.dryLoadPorts ?? []).map(p => ({ label: p.port_name, value: p.dry_volume ?? 0 }))}
                         color={palette.dry} />
              </Card>
              <Card title="Top Dry Bulk Ports — Discharge">
                <BarList rows={(detail.data?.dryDischargePorts ?? []).map(p => ({ label: p.port_name, value: p.dry_volume ?? 0 }))}
                         color={palette.dry} />
              </Card>
              <Card title="Top Liquid Bulk Ports — Load">
                <BarList rows={(detail.data?.liqLoadPorts ?? []).map(p => ({ label: p.port_name, value: p.liquid_volume ?? 0 }))}
                         color={palette.liquid} />
              </Card>
              <Card title="Top Liquid Bulk Ports — Discharge">
                <BarList rows={(detail.data?.liqDischargePorts ?? []).map(p => ({ label: p.port_name, value: p.liquid_volume ?? 0 }))}
                         color={palette.liquid} />
              </Card>
            </div>
          )}

          {/* ---------- Partner countries ---------- */}
          <SectionTitle title="Top Partner Countries" note="ranked by largest port-pair flows" />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Load Partners" subtitle={`countries receiving cargo loaded in ${country}`}>
              <BarList rows={partnerLoad} color={palette.accent} />
            </Card>
            <Card title="Discharge Partners" subtitle={`countries where cargo discharged in ${country} was loaded`}>
              <BarList rows={partnerDischarge} color={palette.neutralBar} />
            </Card>
          </div>

          {/* ---------- Top commodities ---------- */}
          <SectionTitle title="Top Commodities" note={String(year)} />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Dry Bulk — Load"><BarList rows={dryLoadCommodities} color={palette.dry} /></Card>
            <Card title="Dry Bulk — Discharge"><BarList rows={dryDischargeCommodities} color={palette.dry} /></Card>
            <Card title="Liquid Bulk — Load"><BarList rows={liquidLoadCommodities} color={palette.liquid} /></Card>
            <Card title="Liquid Bulk — Discharge"><BarList rows={liquidDischargeCommodities} color={palette.liquid} /></Card>
          </div>

          {/* ---------- Country information ---------- */}
          <SectionTitle title="Country Information" />
          <Card>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <div>
                <div style={{ color: 'var(--dim)' }}>Country</div>
                <div className="font-semibold mt-0.5" style={{ color: 'var(--text)' }}>{country}</div>
              </div>
              <div>
                <div style={{ color: 'var(--dim)' }}>Continent</div>
                <div className="font-semibold mt-0.5" style={{ color: 'var(--text)' }}>{row.continent ?? '—'}</div>
              </div>
              <div>
                <div style={{ color: 'var(--dim)' }}>ISO2</div>
                <div className="font-semibold mt-0.5" style={{ color: 'var(--text)' }}>{row.iso2 ?? '—'}</div>
              </div>
              <div>
                <div style={{ color: 'var(--dim)' }}>Year</div>
                <div className="font-semibold mt-0.5" style={{ color: 'var(--text)' }}>{year}</div>
              </div>
            </div>
          </Card>

          <p className="text-[10px] leading-relaxed" style={{ color: 'var(--faint)' }}>
            Data source: Supabase Materialized Views &middot; Data refreshed periodically &middot; Hover on charts for details.
          </p>
        </>
      )}
    </div>
  )
}
