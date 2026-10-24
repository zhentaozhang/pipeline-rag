import * as React from "react"
import { AlertCircle, Inbox } from "lucide-react"
import { cn } from "../../lib/utils"
import { SkeletonRows } from "./Skeleton"
import { EmptyState } from "./EmptyState"
import { Button } from "./Button"

export interface DataTableColumn<T> {
  key: string
  header: React.ReactNode
  render: (row: T, index: number) => React.ReactNode
  align?: "left" | "right" | "center"
  className?: string
  width?: string
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  rowKey: (row: T, index: number) => string
  /** 表格的无障碍名称，必填 */
  caption: string
  loading?: boolean
  error?: string
  onRetry?: () => void
  emptyTitle?: React.ReactNode
  emptyDescription?: React.ReactNode
  emptyAction?: React.ReactNode
  dense?: boolean
  footer?: React.ReactNode
  skeletonRows?: number
  /**
   * 行点击只作鼠标增强；键盘用户必须靠行内的链接或按钮操作，
   * 因此不要把关键操作只挂在行点击上。
   */
  onRowClick?: (row: T) => void
  className?: string
  highlightRow?: (row: T) => boolean
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  loading = false,
  error = "",
  onRetry,
  emptyTitle = "暂无数据",
  emptyDescription,
  emptyAction,
  dense = false,
  footer,
  skeletonRows = 5,
  onRowClick,
  className,
  highlightRow,
}: DataTableProps<T>) {
  const cellPad = dense ? "px-3 py-2" : "px-4 py-3"

  let body: React.ReactNode
  if (loading && rows.length === 0) {
    body = (
      <tr>
        <td colSpan={columns.length} className="p-0">
          <SkeletonRows rows={skeletonRows} columns={Math.min(columns.length, 5)} />
        </td>
      </tr>
    )
  } else if (error && rows.length === 0) {
    body = (
      <tr>
        <td colSpan={columns.length} className="p-0">
          <EmptyState
            compact
            icon={<AlertCircle size={24} />}
            title="数据加载失败"
            description={error}
            action={
              onRetry ? (
                <Button size="sm" variant="outline" onClick={onRetry}>
                  重新加载
                </Button>
              ) : undefined
            }
          />
        </td>
      </tr>
    )
  } else if (rows.length === 0) {
    body = (
      <tr>
        <td colSpan={columns.length} className="p-0">
          <EmptyState compact icon={<Inbox size={24} />} title={emptyTitle} description={emptyDescription} action={emptyAction} />
        </td>
      </tr>
    )
  } else {
    body = rows.map((row, index) => (
      <tr
        key={rowKey(row, index)}
        onClick={onRowClick ? () => onRowClick(row) : undefined}
        className={cn(
          "border-b border-border/60 last:border-0 transition-colors",
          onRowClick && "cursor-pointer hover:bg-secondary/60",
          highlightRow?.(row) && "bg-accent/40"
        )}
      >
        {columns.map((col) => (
          <td
            key={col.key}
            className={cn(
              cellPad,
              "align-middle text-fine text-foreground",
              col.align === "right" && "text-right",
              col.align === "center" && "text-center",
              col.className
            )}
          >
            {col.render(row, index)}
          </td>
        ))}
      </tr>
    ))
  }

  return (
    <div className={cn("overflow-hidden rounded-xl border border-border bg-card", className)}>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-border bg-secondary/50">
              {columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  style={col.width ? { width: col.width } : undefined}
                  className={cn(
                    "px-4 py-2.5 text-left text-2xs font-medium tracking-wide text-muted-foreground",
                    dense && "px-3",
                    col.align === "right" && "text-right",
                    col.align === "center" && "text-center"
                  )}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody aria-busy={loading || undefined}>{body}</tbody>
        </table>
      </div>
      {footer ? <div className="border-t border-border px-4 py-2.5">{footer}</div> : null}
    </div>
  )
}

export function TablePagination({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  if (total === 0) return null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
      <span aria-live="polite">
        第 {from}–{to} 条，共 {total} 条
      </span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="outline" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>
          上一页
        </Button>
        <span className="px-1 tabular-nums">
          {page} / {pageCount}
        </span>
        <Button size="sm" variant="outline" onClick={() => onPageChange(page + 1)} disabled={page >= pageCount}>
          下一页
        </Button>
      </div>
    </div>
  )
}
