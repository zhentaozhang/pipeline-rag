import * as React from "react"
import { cn } from "../../lib/utils"

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link"
  size?: "default" | "sm" | "lg" | "icon"
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    
    // Base styles
    let compClass = "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
    
    // Variant styles
    if (variant === "default") {
      compClass += " bg-primary text-primary-foreground shadow hover:bg-primary/90"
    } else if (variant === "destructive") {
      compClass += " bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90"
    } else if (variant === "outline") {
      compClass += " border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground"
    } else if (variant === "secondary") {
      compClass += " bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80"
    } else if (variant === "ghost") {
      compClass += " hover:bg-accent hover:text-accent-foreground"
    } else if (variant === "link") {
      compClass += " text-primary underline-offset-4 hover:underline"
    }

    // Size styles
    if (size === "default") {
      compClass += " h-9 px-4 py-2"
    } else if (size === "sm") {
      compClass += " h-8 rounded-md px-3 text-xs"
    } else if (size === "lg") {
      compClass += " h-10 rounded-md px-8"
    } else if (size === "icon") {
      compClass += " h-9 w-9"
    }

    return (
      <button
        className={cn(compClass, className)}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button }
