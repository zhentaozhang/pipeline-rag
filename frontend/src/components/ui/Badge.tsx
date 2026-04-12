import * as React from "react"
import { cn } from "../../lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "destructive" | "outline" | "success" | "warning"
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  let compClass = "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
  
  if (variant === "default") {
    compClass += " bg-primary text-primary-foreground hover:bg-primary/80"
  } else if (variant === "secondary") {
    compClass += " bg-secondary text-secondary-foreground hover:bg-secondary/80"
  } else if (variant === "destructive") {
    compClass += " bg-destructive text-destructive-foreground hover:bg-destructive/80"
  } else if (variant === "outline") {
    compClass += " text-foreground border border-input"
  } else if (variant === "success") {
    compClass += " bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
  } else if (variant === "warning") {
    compClass += " bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
  }

  return (
    <div className={cn(compClass, className)} {...props} />
  )
}

export { Badge }
