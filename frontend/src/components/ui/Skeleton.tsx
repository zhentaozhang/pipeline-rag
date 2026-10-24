import * as React from "react"
import { cn } from "../../lib/utils"

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 骨架行数，>1 时自动按行堆叠 */
  lines?: number
}

/** 加载骨架：纯装饰，读屏靠外层 aria-busy，因此这里 aria-hidden。 */
export function Skeleton({ className, lines = 1, ...props }: SkeletonProps) {
  if (lines <= 1) {
    return (
      <div
        aria-hidden="true"
        className={cn("animate-pulse rounded-md bg-secondary/70", className)}
        {...props}
      />
    )
  }
  return (
    <div aria-hidden="true" className={cn("space-y-2", className)} {...props}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-3 animate-pulse rounded-md bg-secondary/70"
          style={{ width: i === lines - 1 ? "60%" : "100%" }}
        />
      ))}
    </div>
  )
}

export function SkeletonRows({ rows, columns }: { rows: number; columns: number }) {
  return (
    <div aria-hidden="true" className="space-y-2 p-4">
      <Skeleton className="h-8 w-full" />
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="grid gap-3" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
          {Array.from({ length: columns }).map((__, c) => (
            <div key={c} className="h-4 animate-pulse rounded bg-secondary/60" />
          ))}
        </div>
      ))}
    </div>
  )
}
