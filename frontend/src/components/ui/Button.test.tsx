import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { Button } from "./Button"

describe("Button", () => {
  it("默认渲染 type=button，避免在表单里误触发提交", () => {
    render(<Button>保存</Button>)
    expect(screen.getByRole("button", { name: "保存" })).toHaveAttribute("type", "button")
  })

  it("loading 时禁用、标记 aria-busy 且点击不生效", () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        提交
      </Button>
    )
    const btn = screen.getByRole("button", { name: /提交/ })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute("aria-busy", "true")
    fireEvent.click(btn)
    expect(onClick).not.toHaveBeenCalled()
  })

  it("显式传入 type=submit 时保持不变", () => {
    render(<Button type="submit">提交</Button>)
    expect(screen.getByRole("button")).toHaveAttribute("type", "submit")
  })
})
