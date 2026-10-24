import * as React from "react"
import { Search, X } from "lucide-react"
import { cn } from "../../lib/utils"

export function FilterBar({
  children,
  actions,
  className,
}: {
  children: React.ReactNode
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card px-4 py-3",
        className
      )}
    >
      <div className="flex flex-1 flex-wrap items-end gap-3">{children}</div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function FilterField({
  label,
  children,
  className,
}: {
  label: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <label className={cn("flex min-w-32 flex-col gap-1", className)}>
      <span className="text-2xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}

const CONTROL =
  "h-8 w-full rounded-md border border-input bg-background px-2.5 text-fine text-foreground transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"

export function FilterSelect({
  label,
  value,
  onChange,
  options,
  className,
}: {
  label: React.ReactNode
  value: string
  onChange: (value: string) => void
  options: Array<{ value: string; label: string }>
  className?: string
}) {
  return (
    <FilterField label={label} className={className}>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cn(CONTROL, "pr-7")}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FilterField>
  )
}

export function FilterSearch({
  label = "搜索",
  value,
  onChange,
  placeholder = "搜索…",
  className,
}: {
  label?: React.ReactNode
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}) {
  return (
    <FilterField label={label} className={cn("min-w-56 flex-1", className)}>
      <div className="relative">
        <Search
          size={13}
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
        />
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cn(CONTROL, "pl-7 pr-7")}
        />
        {value ? (
          <button
            type="button"
            onClick={() => onChange("")}
            aria-label="清除搜索"
            className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X size={12} />
          </button>
        ) : null}
      </div>
    </FilterField>
  )
}
