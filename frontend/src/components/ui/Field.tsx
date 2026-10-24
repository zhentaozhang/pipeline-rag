import * as React from "react"
import { cn } from "../../lib/utils"

interface FieldContextValue {
  id: string
  describedBy?: string
  invalid: boolean
}

const FieldContext = React.createContext<FieldContextValue | null>(null)

/**
 * 表单字段容器：自动把 label 的 htmlFor、错误提示的 aria-describedby、
 * aria-invalid 串到内部的 Input / Textarea / Select 上。
 * 之前全站 28 个输入控件没有一个带 label。
 */
export function Field({
  label,
  hint,
  error,
  required,
  className,
  children,
}: {
  label: React.ReactNode
  hint?: React.ReactNode
  error?: string
  required?: boolean
  className?: string
  children: React.ReactNode
}) {
  const id = React.useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = errorId ?? hintId

  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-xs font-medium text-muted-foreground">
        {label}
        {required ? (
          <span className="ml-0.5 text-destructive" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      <FieldContext.Provider value={{ id, describedBy, invalid: Boolean(error) }}>
        {children}
      </FieldContext.Provider>
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

function useFieldProps() {
  const ctx = React.useContext(FieldContext)
  if (!ctx) return {}
  return {
    id: ctx.id,
    "aria-describedby": ctx.describedBy,
    "aria-invalid": ctx.invalid || undefined,
  } as const
}

const CONTROL_CLASS =
  "w-full rounded-md border border-input bg-background px-3 text-sm text-foreground transition-colors " +
  "placeholder:text-muted-foreground " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:border-ring " +
  "disabled:cursor-not-allowed disabled:opacity-50 " +
  "aria-[invalid=true]:border-destructive aria-[invalid=true]:focus-visible:ring-destructive/40"

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} {...useFieldProps()} className={cn(CONTROL_CLASS, "h-9", className)} {...props} />
  )
)
Input.displayName = "Input"

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    {...useFieldProps()}
    className={cn(CONTROL_CLASS, "min-h-20 py-2 leading-relaxed resize-y", className)}
    {...props}
  />
))
Textarea.displayName = "Textarea"

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <select
    ref={ref}
    {...useFieldProps()}
    className={cn(CONTROL_CLASS, "h-9 pr-8", className)}
    {...props}
  >
    {children}
  </select>
))
Select.displayName = "Select"
