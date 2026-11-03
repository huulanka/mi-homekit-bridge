import { useEffect, useState } from 'react'
import { fetchJson } from './api'

export interface ApiState<T> {
  data: T | undefined
  error: Error | undefined
  /** True while a request is in flight; previous data stays visible meanwhile. */
  loading: boolean
}

/** Fetch `path` and refetch it every `refreshMs`. Keeps the previous data while
 * reloading so charts hold their frame instead of flashing. */
export function useApi<T>(path: string, refreshMs?: number): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ data: undefined, error: undefined, loading: true })

  useEffect(() => {
    let controller = new AbortController()
    const load = () => {
      controller.abort()
      controller = new AbortController()
      const { signal } = controller
      setState((previous) => ({ ...previous, loading: true }))
      fetchJson<T>(path, signal)
        .then((data) => setState({ data, error: undefined, loading: false }))
        .catch((error: unknown) => {
          if (signal.aborted) return
          setState((previous) => ({
            ...previous,
            error: error instanceof Error ? error : new Error(String(error)),
            loading: false,
          }))
        })
    }
    load()
    const timer = refreshMs ? window.setInterval(load, refreshMs) : undefined
    return () => {
      controller.abort()
      if (timer) window.clearInterval(timer)
    }
  }, [path, refreshMs])

  return state
}
