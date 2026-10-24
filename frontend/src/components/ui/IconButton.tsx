import * as React from "react"
import { cn } from "../../lib/utils"

export interface IconButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "children"> {
  /** 必填：纯图标按钮没有可见文字，无障碍名称只能来自这里。 */
  label: string
  icon: React.ReactNode
  size?: "sm" | "md"
  variant?: "ghost" | "outline" | "solid"
  /** 可选的视觉提示文案（同时作为原生 title） */
  hint?: string
}

const VARIANT_CLASS: Record<NonNullable<IconButtonProps["variant"]>, string> = {
  ghost: "text-muted-foreground hover:bg-secondary hover:text-foreground",
  outline: "border border-border text-muted-foreground hover:bg-secondary hover:text-foreground",
  solid: "bg-primary text-primary-foreground hover:bg-primary/90",
}

const SIZE_CLASS: Record<NonNullable<IconButtonProps["size"]>, string> = {
  sm: "h-7 w-7",
  md: "h-8 w-8",
}

export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ label, icon, hint, size = "md", variant = "ghost", className, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={hint ?? label}
      className={cn(
        "inline-flex items-center justify-center rounded-md transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:pointer-events-none disabled:opacity-50",
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        className
      )}
      {...props}
    >
      {icon}
    </button>
  )
)
IconButton.displayName = "IconButton"
