import { useCallback, useMemo } from "react"
import { useSearchParams } from "react-router-dom"

/**
 * 把列表页的过滤条件放到 URL 里：刷新、后退、分享链接都不再丢筛选状态。
 * 之前后台页面用 useState，切页/刷新就重置。
 */
export function useUrlFilters<T extends Record<string, string>>(
  defaults: T
): [T, (patch: Partial<T>) => void, () => void] {
  const [searchParams, setSearchParams] = useSearchParams()

  const values = useMemo(() => {
    const next = { ...defaults }
    for (const key of Object.keys(defaults) as Array<keyof T>) {
      const raw = searchParams.get(String(key))
      if (raw !== null) next[key] = raw as T[keyof T]
    }
    return next
  }, [searchParams, defaults])

  const setValues = useCallback(
    (patch: Partial<T>) => {
      const next = new URLSearchParams(searchParams)
      for (const [key, value] of Object.entries(patch)) {
        if (value === "" || value == null) next.delete(key)
        else next.set(key, String(value))
      }
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  const reset = useCallback(() => setSearchParams(new URLSearchParams(), { replace: true }), [setSearchParams])

  return [values, setValues, reset]
}
