import { useEffect, useState, useRef } from 'react'

/**
 * Small data-fetching hook. Every page uses this so loading/error handling is
 * uniform and a failure on one page can never leave another page blank.
 *
 * Guards against two failure modes:
 *  - stale responses overwriting newer ones (tracked via a request sequence)
 *  - unhandled rejections escaping into a render and blanking the tree
 */
export function useQuery<T>(
  fn: () => Promise<T>,
  deps: unknown[],
  opts: { skip?: boolean } = {},
): { data: T | null; loading: boolean; error: string } {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(!opts.skip)
  const [error, setError] = useState('')
  const seq = useRef(0)

  useEffect(() => {
    if (opts.skip) { setLoading(false); return }
    const id = ++seq.current
    setLoading(true)
    setError('')
    fn()
      .then(res => {
        if (id !== seq.current) return   // a newer request has superseded this one
        setData(res)
      })
      .catch((e: unknown) => {
        if (id !== seq.current) return
        setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (id === seq.current) setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, loading, error }
}

/** Unwrap a Supabase response, turning its error into a thrown Error. */
export function unwrap<T>(res: { data: T | null; error: { message: string } | null }): T {
  if (res.error) throw new Error(res.error.message)
  return (res.data ?? []) as T
}

const PAGE = 1000  // PostgREST hard-caps a single response at 1000 rows

/**
 * Page through a PostgREST query until it is exhausted.
 *
 * Necessary because Supabase silently truncates at 1000 rows — a `.limit(5000)`
 * returns 1000 with no error. Prefer a server-side aggregate view when the goal
 * is a total; use this when you genuinely need every row (e.g. the port-pairs
 * or vessel-segment matviews, which can exceed 1000 rows per filtered slice).
 */
export async function fetchAll<T>(
  build: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>,
  maxRows = 20000,
): Promise<T[]> {
  const out: T[] = []
  for (let from = 0; from < maxRows; from += PAGE) {
    const res = await build(from, from + PAGE - 1)
    if (res.error) throw new Error(res.error.message)
    const batch = res.data ?? []
    out.push(...batch)
    if (batch.length < PAGE) break
  }
  return out
}
