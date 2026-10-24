import * as React from "react"
import { AlertCircle, CheckCircle2, Info, TriangleAlert } from "lucide-react"
import { cn } from "../../lib/utils"

export type AlertVariant = "info" | "success" | "warning" | "destructive"

const VARIANT: Record<AlertVariant, { cls: string; icon: React.ReactNode }> = {
  info: { cls: "bg-secondary/60 text-foreground border-border", icon: <Info size={16} /> },
  success: {
    cls: "bg-success/10 text-success border-success/30",
    icon: <CheckCircle2 size={16} />,
  },
  warning: { cls: "bg-warning/10 text-warning border-warning/30", icon: <TriangleAlert size={16} /> },
  destructive: {
    cls: "bg-destructive/10 text-destructive border-destructive/30",
    icon: <AlertCircle size={16} />,
  },
}

interface AlertProps {
  variant?: AlertVariant
  title?: React.ReactNode
  children?: React.ReactNode
  action?: React.ReactNode
  className?: string
  onDismiss?: () => void
}

export function Alert({ variant = "info", title, children, action, className, onDismiss }: AlertProps) {
  const { cls, icon } = VARIANT[variant]
  return (
    <div
      role={variant === "destructive" || variant === "warning" ? "alert" : "status"}
      className={cn("flex items-start gap-3 rounded-lg border px-4 py-3 text-sm", cls, className)}
    >
      <span aria-hidden="true" className="mt-0.5 shrink-0">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className={cn("leading-relaxed", title && "mt-0.5 opacity-90")}>{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="关闭提示"
          className="shrink-0 rounded p-0.5 opacity-60 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
          </svg>
        </button>
      ) : null}
    </div>
  )
}
