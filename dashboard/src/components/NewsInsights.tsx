import { supabase } from '../lib/supabase'
import { useQuery } from '../lib/useQuery'
import { Card, SectionTitle } from './ui'

type ScopeType = 'global' | 'region' | 'coastal_region' | 'country' | 'port'

type InsightSource = { title: string; url: string }
type Insight = { text: string; tone: 'up' | 'down' | 'neutral' | 'info'; sources: InsightSource[] }
type NewsInsightsRow = { insights: Insight[]; search_query: string | null; generated_at: string }

const TONE_COLOR: Record<Insight['tone'], string> = {
  up: '#1E9E6C',
  down: '#D64545',
  neutral: 'var(--dim)',
  info: '#8B5CF6',
}
const TONE_ICON: Record<Insight['tone'], string> = {
  up: '▲', down: '▼', neutral: '●', info: 'ℹ',
}

/**
 * Renders cached news-informed executive insights for one dashboard entity
 * (populated by the generate-insights edge function via the weekly
 * refresh_insights.yml GH Actions workflow, not fetched live). Silently
 * renders nothing if no cached row exists yet for this scope/year — the
 * page's own data-only "Executive Insights" panel covers that case.
 */
export function NewsInsights({
  scopeType, scopeKey, year,
}: {
  scopeType: ScopeType
  scopeKey: string
  year: number
}) {
  const { data, loading } = useQuery(async () => {
    const res = await supabase
      .from('news_insights')
      .select('insights, search_query, generated_at')
      .eq('scope_type', scopeType)
      .eq('scope_key', scopeKey)
      .eq('year', year)
      .maybeSingle()
    if (res.error) throw new Error(res.error.message)
    return res.data as NewsInsightsRow | null
  }, [scopeType, scopeKey, year])

  if (loading || !data || !data.insights?.length) return null

  return (
    <>
      <SectionTitle
        title="Market Intelligence"
        note={`updated ${new Date(data.generated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}`}
      />
      <Card>
        <ul className="space-y-2.5 text-sm">
          {data.insights.map((ins, i) => (
            <li key={i} className="flex gap-2.5">
              <span className="shrink-0 mt-0.5" style={{ color: TONE_COLOR[ins.tone] ?? TONE_COLOR.neutral }}>
                {TONE_ICON[ins.tone] ?? TONE_ICON.neutral}
              </span>
              <span style={{ color: 'var(--text-2)' }}>
                {ins.text}
                {ins.sources?.length > 0 && (
                  <span className="ml-1.5 whitespace-nowrap">
                    {ins.sources.map((s, si) => (
                      <a
                        key={si}
                        href={s.url}
                        target="_blank"
                        rel="noreferrer"
                        title={s.title}
                        className="text-[11px] no-underline hover:underline"
                        style={{ color: 'var(--accent)' }}
                      >
                        [{si + 1}]
                      </a>
                    ))}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  )
}
