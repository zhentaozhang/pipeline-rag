import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { useAsyncData } from "./useAsyncData"

describe("useAsyncData", () => {
  it("拉取成功后给出 data 并结束 loading", async () => {
    const { result } = renderHook(() => useAsyncData(async () => ({ total: 3 })))
    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toEqual({ total: 3 })
    expect(result.current.error).toBe("")
  })

  it("失败时把异常收敛成可读错误串", async () => {
    const { result } = renderHook(() =>
      useAsyncData(async () => {
        throw new Error("网络错误")
      })
    )
    await waitFor(() => expect(result.current.error).toBe("网络错误"))
    expect(result.current.loading).toBe(false)
    expect(result.current.data).toBeNull()
  })

  it("refetch 会重新调用取数函数", async () => {
    const fetcher = vi.fn(async () => "v")
    const { result } = renderHook(() => useAsyncData(fetcher))
    await waitFor(() => expect(result.current.data).toBe("v"))
    act(() => {
      result.current.refetch()
    })
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  })

  it("卸载时中止请求，不再回写状态", async () => {
    let captured: AbortSignal | undefined
    const { unmount } = renderHook(() =>
      useAsyncData(async (signal) => {
        captured = signal
        return new Promise<string>(() => {})
      })
    )
    await waitFor(() => expect(captured).toBeDefined())
    unmount()
    expect(captured?.aborted).toBe(true)
  })
})
