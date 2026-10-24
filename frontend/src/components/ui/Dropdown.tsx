import * as React from "react"
import { cn } from "../../lib/utils"

export interface DropdownItem {
  key: string
  label: React.ReactNode
  icon?: React.ReactNode
  onSelect: () => void
  danger?: boolean
  disabled?: boolean
}

interface DropdownProps {
  items: DropdownItem[]
  align?: "start" | "end"
  className?: string
  /** 菜单的无障碍名称 */
  menuLabel: string
  /** 触发器的渲染函数，Dropdown 负责把交互属性与 ref 传进去 */
  trigger: (props: {
    ref: React.Ref<HTMLButtonElement>
    onClick: (e: React.MouseEvent) => void
    "aria-expanded": boolean
    "aria-haspopup": "menu"
  }) => React.ReactNode
  /** 确认型菜单项：选中后不关闭，交由业务渲染确认区（如删除二次确认） */
  footer?: React.ReactNode
}

/**
 * 可键盘操作的弹出菜单。
 * 之前侧边栏是手写 div 菜单：没有 role、没有方向键、没有 Escape、焦点不回收。
 */
export function Dropdown({ items, align = "end", className, menuLabel, trigger, footer }: DropdownProps) {
  const [open, setOpen] = React.useState(false)
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const menuRef = React.useRef<HTMLDivElement>(null)

  const close = React.useCallback((restoreFocus = true) => {
    setOpen(false)
    if (restoreFocus) triggerRef.current?.focus()
  }, [])

  React.useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return
      close(false)
    }
    document.addEventListener("mousedown", onPointerDown)
    return () => document.removeEventListener("mousedown", onPointerDown)
  }, [open, close])

  React.useEffect(() => {
    if (!open) return
    const first = menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')
    first?.focus()
  }, [open])

  const onMenuKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation()
      close()
      return
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return
    const nodes = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? []
    )
    if (nodes.length === 0) return
    e.preventDefault()
    const current = nodes.indexOf(document.activeElement as HTMLElement)
    let next = 0
    if (e.key === "ArrowDown") next = current < 0 ? 0 : (current + 1) % nodes.length
    else if (e.key === "ArrowUp") next = current <= 0 ? nodes.length - 1 : current - 1
    else if (e.key === "End") next = nodes.length - 1
    nodes[next]?.focus()
  }

  return (
    <div className="relative" ref={menuRef}>
      {trigger({
        ref: triggerRef,
        onClick: (e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        },
        "aria-expanded": open,
        "aria-haspopup": "menu",
      })}
      {open && (
        <div
          role="menu"
          aria-label={menuLabel}
          onKeyDown={onMenuKeyDown}
          className={cn(
            "absolute top-full z-50 mt-1 min-w-40 rounded-lg border border-border bg-popover py-1 text-popover-foreground shadow-lg",
            align === "end" ? "right-0" : "left-0",
            className
          )}
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={(e) => {
                e.stopPropagation()
                item.onSelect()
                close()
              }}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors disabled:opacity-50",
                item.danger
                  ? "text-destructive hover:bg-destructive/10"
                  : "hover:bg-secondary focus-visible:bg-secondary"
              )}
            >
              {item.icon ? <span aria-hidden="true">{item.icon}</span> : null}
              {item.label}
            </button>
          ))}
          {footer ? <div className="mt-1 border-t border-border/60 pt-1">{footer}</div> : null}
        </div>
      )}
    </div>
  )
}
