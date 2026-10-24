import * as React from "react"
import { cn } from "../../lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "destructive" | "outline" | "success" | "warning"
  /** 左侧状态点：颜色之外再给一层形状信号，不只靠色相区分状态 */
  dot?: boolean
}

const VARIANT_CLASS: Record<NonNullable<BadgeProps["variant"]>, string> = {
  default: "bg-primary text-primary-foreground",
  secondary: "bg-secondary text-secondary-foreground",
  destructive: "border border-destructive/25 bg-destructive/10 text-destructive",
  outline: "border border-border text-foreground",
  success: "border border-success/25 bg-success/10 text-success",
  warning: "border border-warning/25 bg-warning/10 text-warning",
}

function Badge({ className, variant = "default", dot = false, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium leading-4",
        VARIANT_CLASS[variant],
        className
      )}
      {...props}
    >
      {dot ? <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  )
}

export { Badge }
