import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ConfirmDialog } from "./ConfirmDialog"

describe("ConfirmDialog", () => {
  it("打开时是可访问的模态对话框", () => {
    render(
      <ConfirmDialog open title="切换模式？" description="当前对话会被清空" onConfirm={() => {}} onCancel={() => {}} />
    )
    const dialog = screen.getByRole("dialog", { name: "切换模式？" })
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(dialog).toHaveAccessibleDescription("当前对话会被清空")
  })

  it("默认焦点落在取消按钮上，Escape 触发取消", () => {
    const onCancel = vi.fn()
    render(<ConfirmDialog open title="删除？" onConfirm={() => {}} onCancel={onCancel} />)
    expect(screen.getByRole("button", { name: "取消" })).toHaveFocus()
    fireEvent.keyDown(document, { key: "Escape" })
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it("点击确认回调一次；关闭时不渲染", () => {
    const onConfirm = vi.fn()
    const { rerender } = render(
      <ConfirmDialog open title="删除？" confirmLabel="删除" onConfirm={onConfirm} onCancel={() => {}} />
    )
    fireEvent.click(screen.getByRole("button", { name: "删除" }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    rerender(<ConfirmDialog open={false} title="删除？" onConfirm={onConfirm} onCancel={() => {}} />)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })
})
