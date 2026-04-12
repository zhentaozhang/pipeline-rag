import * as React from "react"
import { cn } from "../../lib/utils"

interface TabsContextValue {
  value: string
  onValueChange: (value: string) => void
}

const TabsContext = React.createContext<TabsContextValue | undefined>(undefined)

export function Tabs({ 
  value, 
  onValueChange, 
  children, 
  className 
}: { 
  value: string
  onValueChange: (value: string) => void
  children: React.ReactNode
  className?: string
}) {
  return (
    <TabsContext.Provider value={{ value, onValueChange }}>
      <div className={cn("w-full", className)}>
        {children}
      </div>
    </TabsContext.Provider>
  )
}

export const TabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "flex overflow-x-auto border-b border-border mt-6 mb-6 flex-shrink-0",
        className
      )}
      {...props}
    />
  )
)
TabsList.displayName = "TabsList"

export const TabsTrigger = React.forwardRef<
  HTMLButtonElement, 
  React.ButtonHTMLAttributes<HTMLButtonElement> & { 
    value: string; 
    step?: string; 
    hint?: string 
  }
>(({ className, value, step, hint, children, ...props }, ref) => {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error("TabsTrigger must be used within Tabs")
  
  const isActive = context.value === value

  return (
    <button
      ref={ref}
      onClick={() => context.onValueChange(value)}
      className={cn(
        "flex flex-1 flex-col relative px-6 py-4 text-left transition-all group focus:outline-none min-w-[200px]",
        className
      )}
      {...props}
    >
      <div className="flex items-center gap-2 mb-1">
        {step && (
          <span className={cn(
            "text-xs font-bold px-2 py-0.5 rounded-full transition-colors",
            isActive 
              ? "bg-primary/20 text-primary" 
              : "bg-secondary text-muted-foreground group-hover:bg-secondary/80"
          )}>
            {step}
          </span>
        )}
        <span className={cn(
          "font-bold text-sm transition-colors",
          isActive 
            ? "text-primary" 
            : "text-muted-foreground group-hover:text-foreground"
        )}>
          {children}
        </span>
      </div>
      {hint && (
        <p className={cn(
          "text-xs transition-colors",
          isActive ? "text-primary/80" : "text-muted-foreground"
        )}>
          {hint}
        </p>
      )}
      {isActive && (
        <div className="absolute bottom-0 left-0 w-full h-0.5 bg-primary rounded-t-full"></div>
      )}
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
      className={cn(
        "flex-1 flex flex-col focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
})
TabsContent.displayName = "TabsContent"
