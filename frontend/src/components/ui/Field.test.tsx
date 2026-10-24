import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { Field, Input, Select, Textarea } from "./Field"

describe("Field", () => {
  it("label 与控件通过 id 关联，可被 getByLabelText 找到", () => {
    render(
      <Field label="文档名称">
        <Input defaultValue="年报" />
      </Field>
    )
    expect(screen.getByLabelText("文档名称")).toHaveValue("年报")
  })

  it("错误状态串上 aria-invalid 与 aria-describedby", () => {
    render(
      <Field label="分片大小" error="必须是正整数">
        <Input />
      </Field>
    )
    const input = screen.getByLabelText("分片大小")
    expect(input).toHaveAttribute("aria-invalid", "true")
    const describedBy = input.getAttribute("aria-describedby")
    expect(describedBy).toBeTruthy()
    expect(screen.getByRole("alert")).toHaveTextContent("必须是正整数")
    expect(document.getElementById(describedBy!)).toHaveTextContent("必须是正整数")
  })

  it("hint 走 aria-describedby，且在有错误时不重复播报", () => {
    const { rerender } = render(
      <Field label="名称" hint="最多 50 字">
        <Input />
      </Field>
    )
    const input = screen.getByLabelText("名称")
    expect(document.getElementById(input.getAttribute("aria-describedby")!)).toHaveTextContent("最多 50 字")

    rerender(
      <Field label="名称" hint="最多 50 字" error="超长了">
        <Input />
      </Field>
    )
    expect(screen.getAllByRole("alert")).toHaveLength(1)
    expect(screen.getByLabelText("名称")).toHaveAttribute("aria-invalid", "true")
  })

  it("Textarea 与 Select 同样继承字段关联", () => {
    render(
      <>
        <Field label="描述">
          <Textarea />
        </Field>
        <Field label="模式">
          <Select>
            <option value="a">A</option>
          </Select>
        </Field>
      </>
    )
    expect(screen.getByLabelText("描述").tagName).toBe("TEXTAREA")
    expect(screen.getByLabelText("模式").tagName).toBe("SELECT")
  })
})
