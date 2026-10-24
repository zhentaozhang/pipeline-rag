export type ToastVariant = "info" | "success" | "error"

export interface ToastOptions {
  title: string
  description?: string
  variant?: ToastVariant
  /** 毫秒；0 表示不自动关闭 */
  duration?: number
}

export interface ToastRecord extends ToastOptions {
  id: number
}

let counter = 0
let toasts: ToastRecord[] = []
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

export function subscribeToasts(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 供 useSyncExternalStore 使用，必须返回稳定引用 */
export function getToastsSnapshot(): ToastRecord[] {
  return toasts
}

export function dismissToast(id: number) {
  toasts = toasts.filter((t) => t.id !== id)
  emit()
}

/**
 * 全局轻提示。用于「操作结果」类反馈（保存成功、复制完成、请求失败），
 * 与页面级错误提示、表单内联错误分工不同：
 *   - 表单内联错误 → Field 的 error
 *   - 消息级错误   → 聊天气泡内的状态
 *   - 操作结果     → toast
 *   - 页面加载失败 → 页面内 Alert / DataTable 的 error 态
 */
export function toast(options: ToastOptions): number {
  const id = ++counter
  toasts = [...toasts, { ...options, id }]
  emit()
  const duration = options.duration ?? 4000
  if (duration > 0) {
    setTimeout(() => dismissToast(id), duration)
  }
  return id
}
