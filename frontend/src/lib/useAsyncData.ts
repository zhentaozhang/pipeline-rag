import { useCallback, useEffect, useEffectEvent, useState } from "react"
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

interface Snapshot<T> {
  data: T | null
  error: string
  /** 产生这份结果的请求 key；和当前 key 不一致就说明还在加载 */
  settledKey: string
}

/**
 * 统一的异步取数状态机：loading / error / refetch / 卸载时 abort。
 * 之前后台 12 个页面各自写一遍 setLoading + try/catch，且请求回来还在 setState。
 *
 * 两个约束（react-hooks 编译器规则）：
 * 1. 不在渲染期写 ref —— 取数函数用 useEffectEvent 取最新值；
 * 2. 不在 effect 里同步 setState —— loading 由「已完成的请求 key 是否落后」派生。
 */
export function useAsyncData<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: unknown[] = []
): AsyncDataState<T> {
  const [snapshot, setSnapshot] = useState<Snapshot<T>>({
    data: null,
    error: "",
    settledKey: "",
  })
  const [tick, setTick] = useState(0)

  // 用序列化后的 key 作为依赖，避免 "spread element in dependency array" 以及
  // 每次渲染都新建的数组/对象造成无限循环。
  const depsKey = JSON.stringify(deps)
  const requestKey = `${depsKey}#${tick}`
  const loading = snapshot.settledKey !== requestKey
  // 重新拉取期间不展示上一次的错误，等新结果回来再决定
  const error = loading ? "" : snapshot.error

  const runFetcher = useEffectEvent((signal: AbortSignal) => fetcher(signal))

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    runFetcher(controller.signal)
      .then((data) => {
        if (cancelled) return
        setSnapshot({ data, error: "", settledKey: requestKey })
      })
      .catch((caught: unknown) => {
        if (cancelled || controller.signal.aborted) return
        setSnapshot((prev) => ({
          data: prev.data,
          error: errorMessage(caught, "加载失败"),
          settledKey: requestKey,
        }))
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [requestKey])

  const refetch = useCallback(() => setTick((t) => t + 1), [])

  const setData = useCallback((updater: T | ((prev: T | null) => T)) => {
    setSnapshot((prev) => ({
      ...prev,
      data:
        typeof updater === "function"
          ? (updater as (p: T | null) => T)(prev.data)
          : updater,
    }))
  }, [])

  return { data: snapshot.data, loading, error, refetch, setData }
}
