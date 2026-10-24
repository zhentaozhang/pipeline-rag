import { useCallback, useEffect, useRef, useState } from "react"
import { errorMessage } from "./utils"

export interface AsyncDataState<T> {
  data: T | null
  loading: boolean
  error: string
  /** 重新拉取；保留上一次数据，避免列表闪成空白 */
  refetch: () => void
  /** 局部更新（乐观更新/就地编辑后同步 UI） */
  setData: (updater: T | ((prev: T | null) => T)) => void
}

/**
 * 统一的异步取数状态机：loading / error / refetch / 卸载时 abort。
 * 之前后台 12 个页面各自写一遍 setLoading + try/catch，且请求回来还在 setState。
 */
export function useAsyncData<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: unknown[] = []
): AsyncDataState<T> {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string }>({
    data: null,
    loading: true,
    error: "",
  })
  const [tick, setTick] = useState(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  // 用序列化后的 key 作为依赖，避免 "spread element in dependency array" 以及
  // 每次渲染都新建的数组/对象造成无限循环。
  const depsKey = JSON.stringify(deps)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    setState((prev) => ({ data: prev.data, loading: true, error: "" }))

    fetcherRef
      .current(controller.signal)
      .then((data) => {
        if (cancelled) return
        setState({ data, loading: false, error: "" })
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted) return
        setState((prev) => ({
          data: prev.data,
          loading: false,
          error: errorMessage(error, "加载失败"),
        }))
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [depsKey, tick])

  const refetch = useCallback(() => setTick((t) => t + 1), [])

  const setData = useCallback((updater: T | ((prev: T | null) => T)) => {
    setState((prev) => ({
      ...prev,
      data:
        typeof updater === "function"
          ? (updater as (p: T | null) => T)(prev.data)
          : updater,
    }))
  }, [])

  return { ...state, refetch, setData }
}
