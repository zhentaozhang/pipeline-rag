import { useSyncExternalStore } from "react"
import { AlertCircle, CheckCircle2, Info } from "lucide-react"
import type { ReactNode } from "react"
import { dismissToast, getToastsSnapshot, subscribeToasts, type ToastVariant } from "../../lib/toast"
import { cn } from "../../lib/utils"

const VARIANT_CLASS: Record<ToastVariant, string> = {
  info: "border-border bg-card text-card-foreground",
  success: "border-success/30 bg-card text-foreground",
  error: "border-destructive/30 bg-card text-foreground",
}

const ICON: Record<ToastVariant, ReactNode> = {
  info: <Info size={16} className="text-muted-foreground" />,
  success: <CheckCircle2 size={16} className="text-success" />,
  error: <AlertCircle size={16} className="text-destructive" />,
}

/** 挂在应用根节点一次即可，配合 lib/toast 的 toast() 使用。 */
export function Toaster() {
  const list = useSyncExternalStore(subscribeToasts, getToastsSnapshot, getToastsSnapshot)
  if (list.length === 0) return null
  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-4 z-[100] flex flex-col items-center gap-2 px-4 sm:items-end"
      aria-live="polite"
      aria-atomic="false"
    >
      {list.map((t) => (
        <div
          key={t.id}
          role={t.variant === "error" ? "alert" : "status"}
          className={cn(
            "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border px-4 py-3 shadow-lg",
            VARIANT_CLASS[t.variant ?? "info"]
          )}
        >
          <span aria-hidden="true" className="mt-0.5 shrink-0">
            {ICON[t.variant ?? "info"]}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{t.title}</p>
            {t.description ? (
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{t.description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => dismissToast(t.id)}
            aria-label="关闭通知"
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  )
}
