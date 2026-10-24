import { useEffect, useState } from 'react'

/**
 * 输入框 → 请求之间的节流。
 * 后台列表的筛选一改就写回 URL 并重新取数，中文输入法下每敲一个字母
 * 就打一次接口既浪费也会让列表闪烁，这里统一延迟 350ms 再提交。
 */
export function useDebouncedValue<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])

  return debounced
}
