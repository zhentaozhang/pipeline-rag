import * as React from "react"
import { cn } from "../../lib/utils"

interface TabsContextValue {
  value: string
  onValueChange: (value: string) => void
  /** 用于生成 tab / tabpanel 的 id 关联 */
  baseId: string
}

const TabsContext = React.createContext<TabsContextValue | undefined>(undefined)

export function Tabs({
  value,
  onValueChange,
  children,
  className,
}: {
  value: string
  onValueChange: (value: string) => void
  children: React.ReactNode
  className?: string
}) {
  const baseId = React.useId()
  const ctx = React.useMemo(() => ({ value, onValueChange, baseId }), [value, onValueChange, baseId])
  return (
    <TabsContext.Provider value={ctx}>
      <div className={cn("w-full", className)}>{children}</div>
    </TabsContext.Provider>
  )
}

const tabId = (baseId: string, value: string) => `${baseId}-tab-${value}`
const panelId = (baseId: string, value: string) => `${baseId}-panel-${value}`

/**
 * 一组选项切换内容面板：需要 tablist/tab/tabpanel 语义与左右方向键，
 * 否则读屏只会念出一串普通按钮，也不知道当前选中哪个、面板在哪。
 */
export const TabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, onKeyDown, ...props }, ref) => {
    const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
      onKeyDown?.(e)
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") return
      const tabs = Array.from(
        e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]:not([disabled])')
      )
      if (tabs.length === 0) return
      e.preventDefault()
      const current = tabs.indexOf(document.activeElement as HTMLElement)
      let next = 0
      if (e.key === "ArrowRight") next = current < 0 ? 0 : (current + 1) % tabs.length
      else if (e.key === "ArrowLeft") next = current <= 0 ? tabs.length - 1 : current - 1
      else if (e.key === "End") next = tabs.length - 1
      tabs[next]?.focus()
      tabs[next]?.click()
    }
    return (
      <div
        ref={ref}
        role="tablist"
        onKeyDown={handleKeyDown}
        className={cn("mt-6 mb-6 flex flex-shrink-0 overflow-x-auto border-b border-border", className)}
        {...props}
      />
    )
  }
)
TabsList.displayName = "TabsList"

export const TabsTrigger = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    value: string
    step?: string
    hint?: string
  }
>(({ className, value, step, hint, children, ...props }, ref) => {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error("TabsTrigger must be used within Tabs")

  const isActive = context.value === value

  return (
    <button
      ref={ref}
      type="button"
      role="tab"
      id={tabId(context.baseId, value)}
      aria-selected={isActive}
      aria-controls={panelId(context.baseId, value)}
      // 只有当前 tab 在 Tab 序列里，其余用方向键移动（WAI-ARIA tabs 模式）
      tabIndex={isActive ? 0 : -1}
      onClick={() => context.onValueChange(value)}
      className={cn(
        "group relative flex min-w-[200px] flex-1 flex-col px-6 py-4 text-left transition-all",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className
      )}
      {...props}
    >
      <div className="mb-1 flex items-center gap-2">
        {step ? (
          <span
            aria-hidden="true"
            className={cn(
              "rounded-full px-2 py-0.5 text-xs font-bold transition-colors",
              isActive ? "bg-primary/20 text-primary" : "bg-secondary text-muted-foreground group-hover:bg-secondary/80"
            )}
          >
            {step}
          </span>
        ) : null}
        <span
          className={cn(
            "text-sm font-bold transition-colors",
            isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
          )}
        >
          {children}
        </span>
      </div>
      {hint ? (
        <p className={cn("text-xs transition-colors", isActive ? "text-primary/80" : "text-muted-foreground")}>
          {hint}
        </p>
      ) : null}
      {isActive ? (
        <span aria-hidden="true" className="absolute bottom-0 left-0 h-0.5 w-full rounded-t-full bg-primary" />
      ) : null}
    </button>
  )
})
TabsTrigger.displayName = "TabsTrigger"

export const TabsContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { value: string }
>(({ className, value, children, ...props }, ref) => {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error("TabsContent must be used within Tabs")

  if (context.value !== value) return null

  return (
    <div
      ref={ref}
      role="tabpanel"
      id={panelId(context.baseId, value)}
      aria-labelledby={tabId(context.baseId, value)}
      tabIndex={0}
      className={cn(
        "flex flex-1 flex-col focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
})
TabsContent.displayName = "TabsContent"
