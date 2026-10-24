import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { DataTable } from "./DataTable"

interface Row {
  id: string
  name: string
}

const columns = [
  { key: "name", header: "名称", render: (row: Row) => row.name },
]

describe("DataTable", () => {
  it("渲染表格名称与列头，供读屏识别", () => {
    render(
      <DataTable caption="文档列表" columns={columns} rows={[{ id: "1", name: "年报" }]} rowKey={(r) => r.id} />
    )
    expect(screen.getByRole("table", { name: "文档列表" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "名称" })).toBeInTheDocument()
    expect(screen.getByRole("cell", { name: "年报" })).toBeInTheDocument()
  })

  it("加载中标记 aria-busy 并渲染骨架", () => {
    const { container } = render(
      <DataTable caption="文档列表" columns={columns} rows={[]} rowKey={(r: Row) => r.id} loading />
    )
    expect(container.querySelector("tbody")).toHaveAttribute("aria-busy", "true")
  })

  it("空数据给出空态文案", () => {
    render(<DataTable caption="文档列表" columns={columns} rows={[]} rowKey={(r: Row) => r.id} />)
    expect(screen.getByText("暂无数据")).toBeInTheDocument()
  })

  it("错误态提供重试入口", () => {
    render(
      <DataTable
        caption="文档列表"
        columns={columns}
        rows={[]}
        rowKey={(r: Row) => r.id}
        error="接口 500"
        onRetry={() => {}}
      />
    )
    expect(screen.getByText("接口 500")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument()
  })
})
