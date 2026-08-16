# 07 · SSE 流式对话协议规范

> **演进状态**：✅ 有效（2026-08 核对）。006 新增断线续传（`?resume=N` 重放 Redis 缓冲，见演进记录 006）；超时/失败/完成三态语义见 001。

> 状态：正式文档（2026-08-15，体检 C3 输出）
> 端点：`POST /api/chat/stream`，响应 `Content-Type: text/event-stream;charset=UTF-8`
> 后端实现：`app/common/sse.py`；前端解析：`frontend/src/lib/api.ts::consumeEventStream`

## 1. 传输格式

- 每条事件为一行 `data: {json}` + 空行分隔（`\n\n`），**不使用** `event:` / `id:` / `retry:` 行。
- 结束标记：正常结束由服务端关闭连接（前端以流关闭为准）；`done` 事件是协议层完成通知。
- 编码：UTF-8，JSON `ensure_ascii=False`。

## 2. 通用 Payload 结构

```jsonc
{
  "type": "text",              // 事件类型（必填）
  "content": "…",              // 事件载荷（类型见下表）
  "timestamp": "2026-08-15T00:00:00Z",
  "conversationId": "…",       // 有值时携带
  "exchangeId": 123,           // >0 时携带
  "count": 3                   // 仅 reference / recommend 列表事件携带
}
```

## 3. 事件类型表

| type | content 类型 | 语义 |
|------|-------------|------|
| `thinking` | str | 中间思考/阶段提示，前端去重后展示 |
| `text` | **str** | 正文增量。**约定 content 恒为 str**；`MESSAGE` 为历史别名（deprecated，勿用于新代码） |
| `reference` | list\<dict\> | 引用列表（文档/URL），携带 `count` |
| `recommend` | list\<str\> | 推荐追问列表，携带 `count` |
| `status` | str | 状态提示（如"⏹ 已停止生成"） |
| `error` | str | 错误信息，前端置 FAILED |
| `done` | null | 本轮结束通知 |
| `review` | dict | 质量自审进行中：`{round, maxRounds, score, message}` |
| `review_result` | dict | 质量自审结果：`{passed, score, message}` |

## 4. 时序约定

```
正常路径:   thinking → (text)* → reference? → recommend? → done
拒绝路径:   thinking → text(refusal) → done
取消路径:   status("已停止") → error → done
失败路径:   error → done
超时路径:   error("生成超时") → done        ← 2026-08-15 修复（原为静默截断无 done）
质量自审:   text 流中插入 review* → review_result
```

- `done` 之后服务端不再发任何事件，并关闭连接。
- 前端不应依赖 `done` 才能结束渲染——以流关闭为最终判定（服务端超时/断连时会关闭流）。

## 5. 消费方约束（前端/其他客户端）

1. 解析：按空行切块，仅取 `data:` 行（允许多行 `data:` 拼接）；`[DONE]` 字符串按空事件忽略。
2. `text` content 若历史版本曾出现 dict（防御性兼容），一律按 `content.content` 取值；新代码只发 str。
3. `reference` / `recommend` 用 `content` 数组，判空用 `count` 或数组长度。
4. `review` / `review_result` 用于展示审核状态（前端 chatStore 已支持），不应中断正文渲染。

## 6. 常见坑（历史问题记录）

| 问题 | 状态 |
|------|------|
| 超时路径静默截断、无 done、被记为成功 | ✅ 已修复（A4）：抛 `StreamChunkTimeoutError` → error + done + turn_status=3 |
| `TEXT` 与 `MESSAGE` 同值别名 | ✅ 已标注 deprecated（C3），保留兼容 |
| `text` content 出现 dict | 历史防御逻辑（service_executor 保留兼容分支），新代码禁止 |
| 前端不处理 review 事件 | ✅ 已修复（A8）：chatStore 展示审核状态 |
