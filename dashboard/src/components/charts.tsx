import { useMemo, useState } from 'react'
import {
  PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer,
  Treemap, Sankey, Rectangle, Layer,
  LineChart, Line, XAxis, YAxis, CartesianGrid, ReferenceLine,
} from 'recharts'
import { useTheme } from '../lib/theme'
import { CustomTooltip, Tabs, fmtVolume, fmt, MAX_YEAR } from './ui'

const DONUT_PALETTE = [
  '#00C2CB', '#3E7CA6', '#C68B3E', '#5BA4CF', '#7A8699',
  '#4156C8', '#B98A1A', '#059669', '#DC2626', '#8B5CF6',
]

/** Donut chart for a topN+"Others" bucketed series. */
export function Donut({ rows, height = 260 }: { rows: { label: string; value: number }[]; height?: number }) {
  const { palette } = useTheme()
  const total = rows.reduce((s, r) => s + r.value, 0)
  if (!rows.length || total === 0) return <div className="text-sm text-center py-8" style={{ color: 'var(--dim)' }}>No data</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie data={rows} dataKey="value" nameKey="label" innerRadius="45%" outerRadius="80%" paddingAngle={1}>
          {rows.map((r, i) => (
            <Cell key={i} fill={r.label === 'Others' ? palette.muted : DONUT_PALETTE[i % DONUT_PALETTE.length]} />
          ))}
        </Pie>
        <Tooltip content={<CustomTooltip />} />
        <Legend
          layout="vertical" align="right" verticalAlign="middle"
          wrapperStyle={{ fontSize: 11, color: palette.muted }}
          formatter={(value: string) => {
            const row = rows.find(r => r.label === value)
            const pct = row && total ? ((row.value / total) * 100).toFixed(1) : '0'
            return `${value}: ${pct}%`
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}

type TreemapNode = { name: string; size?: number; children?: TreemapNode[]; fill?: string }

function TreemapCell(props: {
  x?: number; y?: number; width?: number; height?: number; name?: string; size?: number; depth?: number; fill?: string
}) {
  const { x = 0, y = 0, width = 0, height = 0, name, size, depth = 0, fill } = props
  const { palette } = useTheme()
  const showLabel = width > 60 && height > 24
  return (
    <Layer>
      <Rectangle
        x={x} y={y} width={width} height={height}
        fill={fill ?? (depth === 1 ? palette.accent : palette.neutralBar)}
        fillOpacity={depth === 1 ? 0.85 : 0.6}
        stroke={palette.tooltipBg}
        strokeWidth={1}
      />
      {showLabel && (
        <>
          <text x={x + 6} y={y + 16} fontSize={11} fill="#fff" fillOpacity={0.95}>
            {name}
          </text>
          {height > 40 && size !== undefined && (
            <text x={x + 6} y={y + 32} fontSize={10} fill="#fff" fillOpacity={0.75}>
              {fmtVolume(size)}
            </text>
          )}
        </>
      )}
    </Layer>
  )
}

/** Two-level treemap (e.g. Region -> Country, or Commodity Type -> Group). */
export function TwoLevelTreemap({ data, height = 320 }: { data: TreemapNode[]; height?: number }) {
  if (!data.length) return <div className="text-sm text-center py-8" style={{ color: 'var(--dim)' }}>No data</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <Treemap data={data as any} dataKey="size" aspectRatio={4 / 3} content={<TreemapCell />} />
    </ResponsiveContainer>
  )
}

/** Builds Recharts Sankey {nodes, links} from flat source->target flow rows,
 *  deduping node names into indices (Sankey needs numeric source/target). */
export function buildSankey(rows: { source: string; target: string; value: number }[]) {
  const names: string[] = []
  const idx = new Map<string, number>()
  const nameOf = (n: string) => {
    if (!idx.has(n)) { idx.set(n, names.length); names.push(n) }
    return idx.get(n)!
  }
  const links = rows
    .filter(r => r.value > 0 && r.source && r.target)
    .map(r => ({ source: nameOf(`${r.source} `), target: nameOf(` ${r.target}`), value: r.value }))
  return { nodes: names.map(name => ({ name })), links }
}

export function FlowSankey({ rows, height = 380 }: {
  rows: { source: string; target: string; value: number }[]
  height?: number
}) {
  const { palette } = useTheme()
  const data = useMemo(() => buildSankey(rows), [rows])
  if (!data.links.length) return <div className="text-sm text-center py-8" style={{ color: 'var(--dim)' }}>No data</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <Sankey
        data={data}
        nodePadding={14}
        nodeWidth={10}
        link={{ stroke: palette.accent, strokeOpacity: 0.25 }}
        node={{ stroke: palette.tooltipBorder, fill: palette.accent }}
      >
        <Tooltip content={<CustomTooltip />} />
      </Sankey>
    </ResponsiveContainer>
  )
}

// ---------------------------------------------------------------------------
// Forecast panel — 5 algorithms, matching the existing bolt.host dashboard.
// ---------------------------------------------------------------------------

export type YearPoint = { year: number; value: number }

const ALGORITHMS = ['All', 'Linear Trend', 'CAGR (3Y)', 'CAGR (5Y)', "Holt's Exponential", 'Moving Average'] as const
type Algorithm = typeof ALGORITHMS[number]

function linearTrend(hist: YearPoint[], toYear: number): YearPoint[] {
  const n = hist.length
  if (n < 2) return []
  const xBar = hist.reduce((s, h) => s + h.year, 0) / n
  const yBar = hist.reduce((s, h) => s + h.value, 0) / n
  const num = hist.reduce((s, h) => s + (h.year - xBar) * (h.value - yBar), 0)
  const den = hist.reduce((s, h) => s + (h.year - xBar) ** 2, 0)
  const b = den === 0 ? 0 : num / den
  const a = yBar - b * xBar
  const lastYear = hist[n - 1].year
  const out: YearPoint[] = []
  for (let y = lastYear + 1; y <= toYear; y++) out.push({ year: y, value: Math.max(0, a + b * y) })
  return out
}

function cagrForecast(hist: YearPoint[], windowYears: number, toYear: number): YearPoint[] {
  const n = hist.length
  if (n < 2) return []
  const lastIdx = n - 1
  const startIdx = Math.max(0, lastIdx - windowYears)
  const startVal = hist[startIdx].value
  const endVal = hist[lastIdx].value
  const years = hist[lastIdx].year - hist[startIdx].year
  const cagr = years > 0 && startVal > 0 ? (endVal / startVal) ** (1 / years) - 1 : 0
  const out: YearPoint[] = []
  let val = endVal
  for (let y = hist[lastIdx].year + 1; y <= toYear; y++) {
    val = val * (1 + cagr)
    out.push({ year: y, value: Math.max(0, val) })
  }
  return out
}

function holtsForecast(hist: YearPoint[], toYear: number, alpha = 0.3, beta = 0.15): YearPoint[] {
  const n = hist.length
  if (n < 2) return []
  let level = hist[0].value
  let trend = hist[1].value - hist[0].value
  for (let i = 1; i < n; i++) {
    const prevLevel = level
    level = alpha * hist[i].value + (1 - alpha) * (level + trend)
    trend = beta * (level - prevLevel) + (1 - beta) * trend
  }
  const lastYear = hist[n - 1].year
  const out: YearPoint[] = []
  let h = 1
  for (let y = lastYear + 1; y <= toYear; y++) {
    out.push({ year: y, value: Math.max(0, level + h * trend) })
    h++
  }
  return out
}

function movingAverageForecast(hist: YearPoint[], toYear: number, window = 3): YearPoint[] {
  const n = hist.length
  if (n < 2) return []
  const recent = hist.slice(Math.max(0, n - window))
  const rates: number[] = []
  for (let i = 1; i < recent.length; i++) {
    if (recent[i - 1].value > 0) rates.push(recent[i].value / recent[i - 1].value - 1)
  }
  const avgGrowth = rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : 0
  const lastYear = hist[n - 1].year
  let val = hist[n - 1].value
  const out: YearPoint[] = []
  for (let y = lastYear + 1; y <= toYear; y++) {
    val = val * (1 + avgGrowth)
    out.push({ year: y, value: Math.max(0, val) })
  }
  return out
}

const ALGO_COLOR: Record<string, string> = {
  'Linear Trend': '#5BA4CF',
  'CAGR (3Y)': '#C68B3E',
  'CAGR (5Y)': '#B98A1A',
  "Holt's Exponential": '#059669',
  'Moving Average': '#8B5CF6',
}

/** Forecast panel: historical actuals + a chosen (or all) projection algorithm
 *  out to `toYear`. Ports the 5-algorithm logic already validated on the live
 *  bolt.host build, generalized to any yearly volume series. */
export function ForecastPanel({ history, toYear = MAX_YEAR + 5, height = 280 }: {
  history: YearPoint[]
  toYear?: number
  height?: number
}) {
  const { palette } = useTheme()
  const [algo, setAlgo] = useState<Algorithm>('All')

  const forecasts = useMemo(() => {
    const sorted = [...history].sort((a, b) => a.year - b.year)
    return {
      'Linear Trend': linearTrend(sorted, toYear),
      'CAGR (3Y)': cagrForecast(sorted, 3, toYear),
      'CAGR (5Y)': cagrForecast(sorted, 5, toYear),
      "Holt's Exponential": holtsForecast(sorted, toYear),
      'Moving Average': movingAverageForecast(sorted, toYear),
    } as Record<string, YearPoint[]>
  }, [history, toYear])

  const shown: Algorithm[] = algo === 'All'
    ? ['Linear Trend', 'CAGR (3Y)', 'CAGR (5Y)', "Holt's Exponential", 'Moving Average']
    : [algo]

  const merged = useMemo(() => {
    const sorted = [...history].sort((a, b) => a.year - b.year)
    const rows = new Map<number, Record<string, number>>()
    for (const h of sorted) rows.set(h.year, { year: h.year, actual: h.value })
    for (const key of shown) {
      for (const p of forecasts[key] ?? []) {
        const row = rows.get(p.year) ?? { year: p.year }
        row[key] = p.value
        rows.set(p.year, row)
      }
    }
    return Array.from(rows.values()).sort((a, b) => a.year - b.year)
  }, [history, forecasts, shown])

  if (history.length < 2) return <div className="text-sm text-center py-8" style={{ color: 'var(--dim)' }}>Not enough history to forecast.</div>

  const lastActualYear = history.length ? Math.max(...history.map(h => h.year)) : undefined

  return (
    <div>
      <div className="mb-3"><Tabs value={algo} onChange={v => setAlgo(v as Algorithm)} options={[...ALGORITHMS]} size="sm" /></div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={merged} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="year" tick={{ fill: palette.axis, fontSize: 11 }} axisLine={{ stroke: palette.grid }} tickLine={false} />
          <YAxis tick={{ fill: palette.axis, fontSize: 11 }} width={48} axisLine={false} tickLine={false} tickFormatter={fmtVolume} />
          <Tooltip content={<CustomTooltip />} />
          {lastActualYear !== undefined && (
            <ReferenceLine x={lastActualYear} stroke={palette.muted} strokeDasharray="3 3" />
          )}
          <Line type="monotone" dataKey="actual" name="Actual" stroke={palette.accent} strokeWidth={2.5} dot={false} connectNulls />
          {shown.map(key => (
            <Line key={key} type="monotone" dataKey={key} name={key}
                  stroke={ALGO_COLOR[key]} strokeWidth={1.75} strokeDasharray="5 3" dot={false} connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <p className="text-[10px] mt-2" style={{ color: 'var(--faint)' }}>
        {fmt(lastActualYear)} is the last actual year; lines beyond it are projections to {toYear}.
      </p>
    </div>
  )
}
