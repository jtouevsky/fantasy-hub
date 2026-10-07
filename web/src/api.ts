import { QueryClient, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

// Cached data is shown instantly (memory first, then localStorage from the last visit) and refreshed in the background.
// The server only recomputes on Refresh / TTL expiry, so a data version bump (bootstrap.version) is the only thing that clears client caches.
export const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 5 * 60_000, gcTime: 60 * 60_000, refetchOnWindowFocus: false, retry: 1 } },
})

const LS = 'fh:q:'
type Cached<T> = { data: T; at: number }

function readLS<T>(key: string): Cached<T> | undefined {
  try {
    const s = localStorage.getItem(LS + key)
    return s ? (JSON.parse(s) as Cached<T>) : undefined
  } catch {
    return undefined
  }
}

export function clearPersisted() {
  try {
    Object.keys(localStorage).filter((k) => k.startsWith(LS)).forEach((k) => localStorage.removeItem(k))
  } catch { /* ignore */ }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, msg: string) {
    super(msg)
    this.status = status
  }
}

export async function http<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) {
    let msg = r.statusText
    try {
      const j = await r.json()
      msg = j.detail || j.error || msg
    } catch { /* ignore */ }
    throw new ApiError(r.status, msg)
  }
  return r.json()
}
export const post = <T = any>(path: string, body?: unknown) => http<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
export const put = <T = any>(path: string, body?: unknown) => http<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })

export function fetchPersisted<T>(path: string): Promise<T> {
  return http<T>(path).then((d) => {
    try { localStorage.setItem(LS + path, JSON.stringify({ data: d, at: Date.now() })) } catch { /* quota */ }
    return d
  })
}

export function prefetch(path: string, stale = 5 * 60_000) {
  return qc.prefetchQuery({ queryKey: [path], queryFn: () => fetchPersisted(path), staleTime: stale })
}

export function useApi<T = any>(path: string | null, opts: { stale?: number } = {}) {
  const cached = useMemo(() => (path ? readLS<T>(path) : undefined), [path])
  return useQuery<T>({
    queryKey: [path],
    queryFn: () => fetchPersisted<T>(path as string),
    enabled: !!path,
    initialData: cached?.data,
    initialDataUpdatedAt: cached?.at,
    staleTime: opts.stale,
  })
}
