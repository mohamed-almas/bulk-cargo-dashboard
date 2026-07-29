import { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { supabase } from '../lib/supabase'
import { useQuery, unwrap } from '../lib/useQuery'
import { useTheme } from '../lib/theme'
import {
  KPICard, Card, Spinner, ErrorMsg, Empty, PageHeader, SectionTitle, Select, BarList,
  CustomTooltip, fmtVolume, fmtPct, topNWithOthers, MIN_YEAR, MAX_YEAR, DEFAULT_YEAR,
} from '../components/ui'
import { Donut, TwoLevelTreemap, ForecastPanel, type YearPoint } from '../components/charts'

type GroupYearRow = {
  year: number
  commodity_type: 'Dry' | 'Liquid'
  commodity_group_short: string
  volume: number
  voyages: number
}

type CommodityRow = {
  year: number
  commodity_group_short: string
  commodity_short: string
  volume: number
  voyages: number
}

type CountryRow = {
  year: number
  direction: string
  country_short_name: string
  commodity_group_short: string
  total_volume: number
}

export default function Commodity() {
  const { palette } = useTheme()
  const [group, setGroup] = useState('')
  const [year, setYear] = useState(DEFAULT_YEAR)

  // All group-year volumes (small table) — drives group list, default, KPIs, trend, ranking.
  const allGroups = useQuery(async () => {
    const res = await supabase.from('xmv_global_commodities_by_volume_total')
      .select('year,commodity_type,commodity_group_short,volume,voyages')
      .gte('year', MIN_YEAR).lte('year', MAX_YEAR)
    return unwrap(res) as GroupYearRow[]
  }, [])

  const groupOptions = useMemo(() => {
    if (!allGroups.data) return []
    return Array.from(new Set(allGroups.data.map(r => r.commodity_group_short))).sort()
  }, [allGroups.data])

  // Default to the highest-volume group in the latest available year.
  useEffect(() => {
    if (group || !allGroups.data?.length) return
    const latestYear = Math.max(...allGroups.data.map(r => r.year))
    const inLatest = allGroups.data.filter(r => r.year === latestYear)
    const top = [...inLatest].sort((a, b) => b.volume - a.volume)[0]
    if (top) setGroup(top.commodity_group_short)
  }, [allGroups.data, group])

  const cargoType = useMemo(() => {
    const row = allGroups.data?.find(r => r.commodity_group_short === group)
    return row?.commodity_type ?? 'Dry'
  }, [allGroups.data, group])

  const q = useQuery(async () => {
    const [dryRes, liquidRes, countryRes] = await Promise.all([
      supabase.from('xmv_global_commodities_by_volume_dry')
        .select('year,commodity_group_short,commodity_short,volume,voyages')
        .eq('year', year),
      supabase.from('xmv_global_commodities_by_volume_liquid')
        .select('year,commodity_group_short,commodity_short,volume,voyages')
        .eq('year', year),
      supabase.from('xmv_country_top_commodities_v2')
        .select('year,direction,country_short_name,commodity_group_short,total_volume')
        .eq('year', year).eq('commodity_group_short', group).eq('direction', 'load'),
    ])
    return {
      dry: unwrap(dryRes) as CommodityRow[],
      liquid: unwrap(liquidRes) as CommodityRow[],
      countries: unwrap(countryRes) as CountryRow[],
    }
  }, [year, group], { skip: !group })

  // --- Derived data ---

  const trend: YearPoint[] = useMemo(() => {
    if (!allGroups.data || !group) return []
    return allGroups.data
      .filter(r => r.commodity_group_short === group)
      .sort((a, b) => a.year - b.year)
      .map(r => ({ year: r.year, value: r.volume }))
  }, [allGroups.data, group])

  const yearRows = useMemo(
    () => (allGroups.data ?? []).filter(r => r.year === year),
    [allGroups.data, year],
  )

  const selectedRow = yearRows.find(r => r.commodity_group_short === group)
  const totalVolume = selectedRow?.volume ?? 0

  const cargoTotal = yearRows
    .filter(r => r.commodity_type === cargoType)
    .reduce((s, r) => s + r.volume, 0)
  const share = cargoTotal > 0 ? totalVolume / cargoTotal : null

  const rankedGroups = [...yearRows].sort((a, b) => b.volume - a.volume)
  const rank = rankedGroups.findIndex(r => r.commodity_group_short === group) + 1

  const top10 = useMemo(
    () => topNWithOthers(rankedGroups, 10, r => r.volume, r => r.commodity_group_short),
    [rankedGroups],
  )

  const hierarchyData = useMemo(() => {
    const rows = [...(q.data?.dry ?? []), ...(q.data?.liquid ?? [])]
    const byGroup = new Map<string, { name: string; children: { name: string; size: number }[] }>()
    for (const r of rows) {
      if (!r.volume) continue
      if (!byGroup.has(r.commodity_group_short)) {
        byGroup.set(r.commodity_group_short, { name: r.commodity_group_short, children: [] })
      }
      byGroup.get(r.commodity_group_short)!.children.push({ name: r.commodity_short, size: r.volume })
    }
    return Array.from(byGroup.values())
  }, [q.data])

  const countryRows = useMemo(
    () => (q.data?.countries ?? [])
      .map(r => ({ label: r.country_short_name, value: r.total_volume }))
      .sort((a, b) => b.value - a.value),
    [q.data],
  )

  const years = Array.from({ length: MAX_YEAR - MIN_YEAR + 1 }, (_, i) => MIN_YEAR + i).reverse()

  const loading = allGroups.loading || q.loading
  const error = allGroups.error || q.error

  return (
    <div className="space-y-5">
      <PageHeader title="Commodity Overview" subtitle={group ? `${group} · ${cargoType}` : undefined}>
        <Select
          value={group} onChange={setGroup} placeholder="Select commodity group..."
          options={groupOptions.map(g => ({ value: g, label: g }))}
        />
        <Select
          value={String(year)} onChange={v => setYear(Number(v))}
          options={years.map(y => ({ value: String(y), label: String(y) }))}
        />
      </PageHeader>

      {loading ? <Spinner /> : error ? <ErrorMsg msg={error} /> : !group ? null : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KPICard label={`Total Volume (${year})`} value={fmtVolume(totalVolume)} accent sub="tonnes carried" />
            <KPICard label={`Share of Global ${cargoType}`} value={share !== null ? fmtPct(share) : '—'} sub={`vs. all ${cargoType} commodities`} />
            <KPICard label="Rank" value={rank || '—'} sub={`of ${rankedGroups.length} commodity groups`} />
            <KPICard label="Voyages" value={fmtVolume(selectedRow?.voyages)} sub={`carrying ${group} in ${year}`} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Annual Volume Trend" subtitle={`${group} · ${MIN_YEAR}–${MAX_YEAR}`}>
              {trend.length === 0 ? <Empty /> : (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={trend} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <XAxis dataKey="year" tick={{ fill: palette.axis, fontSize: 11 }} axisLine={{ stroke: palette.grid }} tickLine={false} />
                    <YAxis tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false} tickFormatter={fmtVolume} />
                    <Tooltip content={<CustomTooltip />} cursor={{ fill: palette.grid, fillOpacity: 0.25 }} />
                    <Bar dataKey="value" name="Volume" fill={cargoType === 'Dry' ? palette.dry : palette.liquid} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>

            <Card title="Volume Forecast" subtitle={`${group} projected to ${MAX_YEAR + 5}`}>
              <ForecastPanel history={trend} />
            </Card>
          </div>

          <SectionTitle title="Commodity Hierarchy" note={`Group → Commodity · ${year}`} />
          <Card>
            <TwoLevelTreemap
              data={hierarchyData.map(g => ({ name: g.name, children: g.children }))}
            />
          </Card>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Card title="Top 10 Commodity Groups" subtitle={`global, by volume in ${year}`}>
              <Donut rows={top10} />
            </Card>

            <Card title={`Top Load Countries — ${group}`} subtitle={`by volume in ${year}`}>
              {countryRows.length === 0 ? <Empty msg="No country breakdown available." /> : (
                <BarList rows={countryRows} color={cargoType === 'Dry' ? palette.dry : palette.liquid} maxRows={10} />
              )}
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
