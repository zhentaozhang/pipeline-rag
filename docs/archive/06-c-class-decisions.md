# 06 · C 类修改计划 — 待决策清单

> **归档状态**：📦 历史过程文档（2026-08）。C 类 8 项已全部按决策实施，决策结果见演进记录 001，本文件不再更新。

> 用途：C 类 8 项均为"模棱两可/需决策"问题，修改前必须先由项目方拍板。
> 每项给出【现状】【推荐方案】【备选方案】【风险/工作量】【我的推荐】。
> 决策方式：对每项选择「推荐 / 备选 / 暂不处理」，勾选后即可进入执行。

---

## C1 · 双可观测性体系并存（OTEL vs 自研 MySQL Trace）

- **现状**：OTEL 默认禁用（`OTEL_ENABLED=false`）；自研 Trace（MySQL 落盘）+ LLM-as-Judge 默认启用（`sample_rate=1.0`）；指标在 `app/infra/metrics.py` 与 `app/observability/metrics/` 两处定义。
- **推荐方案 A（我推荐）**：明确「自研体系为生产标准」。动作：① `app/infra/tracing.py` 与 `OTelSettings` 标注为 deprecated/预留，不删代码但停止维护；② 清理两处 metrics 定义中**重复的计数器**（执行时逐一核对，保留 app/observability 为准）；③ README 技术栈标注 OTEL 为"可选，默认关闭"。
  - 工作量：S-M；风险：低（纯标注+去重）。
- **备选方案 B**：彻底移除 OTEL（删依赖、删 tracing.py、删配置）——更干净，但若未来要接 Collector 需重写。
- **备选方案 C**：接入真实 OTEL（部署 Collector）——大工程，当前无收益，不推荐。
- **需要你决策**：选 A / B / C / 暂不处理。

---

## C2 · 业务异常默认返回 HTTP 200（监控失明）

- **现状**：普通业务异常（含 login 密码错误）返回 **HTTP 200 + body.code**，仅 Auth/429/400 有真实状态码；4xx/5xx 监控告警失明。
- **推荐方案 A（我推荐）**：把异常处理器的**默认状态码 200 改为 400**（业务失败至少是 4xx），保留 Auth=401 / RateLimit=429 / Argument=400 的特例；前端 `requestApiEnvelope`/`requestJson` 的 `!response.ok` 分支已读 body message，**兼容性需实测**（重点验证：401 时 `handleUnauthorized` 只对 /admin 路径跳转，chat 接口用 API Key 不受影响）。
  - 工作量：S-M；风险：中（前端行为变化，需跑一遍前端链路验证）。
- **备选方案 B**：保持 200 约定，仅在文档中记录"业务错误用 body.code 判断"——监控盲区继续存在。
- **备选方案 C**：细化到每个业务场景的真实状态码（409/422/403 等）——最正确但改动面大。
- **需要你决策**：选 A / B / C / 暂不处理。

---

## C3 · SSE 协议语义未文档化（契约只在代码里）

- **现状**：`TEXT` 与 `MESSAGE` 是同一事件别名；`text` 事件 content 可为 str 或 dict；取消/超时路径的 DONE 语义不一致（超时已修，取消有 DONE）。
- **推荐方案 A（我推荐）**：① 输出《SSE 协议规范》文档（docs/protocol/sse-protocol.md）：事件类型表、payload 结构、时序、错误约定；② 代码层清理：`SSEEventType.MESSAGE` 标记 deprecated（保留兼容）、`text` content 统一为 str（dict 场景走专用事件）；③ 在协议文档中明确 DONE 的三种到达路径（正常/取消/超时失败）。
  - 工作量：S；风险：低。
- **备选方案 B**：只写文档不动代码（契约文档化即可）。
- **需要你决策**：选 A / B / 暂不处理。

---

## C4 · README/注释与实现漂移

- **现状**：README 架构图称 Vue 前端（实际 React）；Neo4j/MySQL/ES 并列为"核心"（实际 NEO4J_ENABLED=false）；未反映 Celery beat 等新组件。
- **推荐方案 A（我推荐）**：更新 README：① 前端改为 React 19 描述；② Neo4j 标注"可选组件，默认关闭"；③ 架构图补充 celery-beat；④ 同步 B 类已完成的改动说明。
  - 工作量：S；风险：无。
- **需要你决策**：选 A / 暂不处理。

---

## C5 · 静默降级无观测上报

- **现状**：chatMode 未知→回退 AUTO_DOCUMENT、记忆策略未知→回退 sliding_window、检索通道失败/子问题超时→静默忽略；无统一降级告警。
- **推荐方案 A（我推荐）**：新增 `DEGRADATION_TOTAL` Prometheus 计数器（reason label），在三处降级点 inc：`normalize_chat_mode` 回退、`create_memory_strategy` 回退、RAG 通道失败/子问题超时（复用现有 `RETRIEVAL_EMPTY_TOTAL` 判定处）；保留现有 logger 日志。
  - 工作量：S；风险：低（纯增量观测）。
- **备选方案 B**：只加结构化日志，不加指标。
- **需要你决策**：选 A / B / 暂不处理。

---

## C6 · 配置默认值打架（需你确认调参意图）

- **现状**：`.env` 实际值 `RAG_CANDIDATE_TOP_K=30`（代码默认 6）、`RAG_VECTOR_TOP_K=20`/`RAG_KEYWORD_TOP_K=20`（默认 5/5）；`.env` 未设 `RAG_EVALUATION_SAMPLE_RATE` → 走代码默认 0.0，而 `.env.example` 写 1.0（照抄示例将全量评估）；`quality_*` 系列未进 `.env.example`。
- **推荐方案 A（我推荐）**：① 我先产出《.env vs 代码默认 差异对照表》（逐项列出当前生效值/代码默认值/示例值）；② 请你逐项确认「有意调参」还是「测试残留」；③ 有意的→固化到 `.env.example` 并加用途注释；残留的→删除/还原；④ `RAG_QUALITY_*`、`RAG_CORRECTIVE_*` 等缺失配置补进 `.env.example`。
  - 工作量：S（取决于你的确认速度）；风险：无。
- **需要你决策**：是否同意先出差异对照表 + 你逐项确认？（本项必须人工确认意图，无法代决）

---

## C7 · Redis 锁续期/判定阈值不对称（潜在双实例窗口）

- **现状**：续期 5 次连续失败即放弃（锁在 Redis 侧过期，他人可抢占）；`is_owned()` 需 10 次连续失败才判丢，且每 30 chunk 才检查一次 → 存在短暂双实例并发窗口。
- **推荐方案 A（我推荐）**：续期放弃时**立即置本地标志** `self._lease_give_up = True`，`is_owned()` 优先检查该标志（命中即返回 False）→ 续期失败即刻触发本侧停止，窗口收敛为"单次检查间隔"。
  - 工作量：S；风险：低；需补单测。
- **备选方案 B**：统一 FAILURE_THRESHOLD=5（与续期一致）——简单但依赖检查频率，窗口仍存。
- **备选方案 C**：接受现状，文档化说明窗口宽度与触发条件。
- **需要你决策**：选 A / B / C / 暂不处理。

---

## C8 · APP_SECRET_KEY 职责不清（零引用）

- **现状**：`APP_SECRET_KEY` 与 `JWT_SECRET_KEY` 双密钥并存；grep 确认 `APP_SECRET_KEY` 在 app/ 内仅定义、无任何引用（纯死配置）。
- **推荐方案 A（我推荐）**：删除 `APP_SECRET_KEY`（`app/config/app.py` 字段、`.env`、`.env.example`），`JWT_SECRET_KEY` 成为唯一密钥。
  - 工作量：XS；风险：无（已确认零引用）。
- **备选方案 B**：保留并文档化为"预留用途"（如未来 CSRF/会话签名）——不推荐，YAGNI。
- **需要你决策**：选 A / B / 暂不处理。

---

## 决策汇总表（请逐项勾选）

| # | 问题 | 我的推荐 | 你的选择 |
|---|------|---------|---------|
| C1 | 双可观测性 | A（自研为准，OTEL 标 deprecated，去重指标） | ☐ A ☐ B ☐ C ☐ 暂缓 |
| C2 | 业务异常 HTTP 200 | A（默认改 400，前端实测兼容） | ☐ A ☐ B ☐ C ☐ 暂缓 |
| C3 | SSE 协议未文档化 | A（文档 + 清理别名/类型） | ☐ A ☐ B ☐ 暂缓 |
| C4 | README 漂移 | A（更新 README） | ☐ A ☐ 暂缓 |
| C5 | 静默降级无观测 | A（新增 DEGRADATION 指标） | ☐ A ☐ B ☐ 暂缓 |
| C6 | 配置打架 | A（先出差异表，你逐项确认意图） | ☐ 同意出表 ☐ 暂缓 |
| C7 | 锁阈值不对称 | A（续期放弃即标记，is_owned 立即判失） | ☐ A ☐ B ☐ C ☐ 暂缓 |
| C8 | APP_SECRET_KEY | A（删除） | ☐ A ☐ B ☐ 暂缓 |

> 说明：C1 执行时需先核对两处 metrics 是否真有重复（避免误删）；C2 需在改后实测前端登录/管理页全链路；C6 必须你人工确认，其余各项按你的选择执行。


---

### 附录：C6 配置差异对照表（脱敏，2026-08-15）

| 配置项 | 代码字面默认 | .env | .env.example | 差异 |
|---|---|---|---|---|
| `APP_DEBUG` | `False` | `true` | `true` | .env≠默认、ex≠默认 |
| `PREVIEW_ENABLED` | `False` | `—` | `false` | ex≠默认 |
| `MYSQL_DB` | `pipeline_rag` | `agentic_rag` | `pipeline_rag` | .env≠默认、env≠ex |
| `MYSQL_PASSWORD` | `5656` | `5656` | `your****` | ex≠默认、env≠ex |
| `MYSQL_USER` | `root` | `agentic_rag_app` | `root` | .env≠默认、env≠ex |
| `POSTGRES_DB` | `pipeline_rag_vector` | `agentic_rag_vector` | `pipeline_rag_vector` | .env≠默认、env≠ex |
| `POSTGRES_PASSWORD` | `5656` | `5656` | `your****` | ex≠默认、env≠ex |
| `ES_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `ES_INDEX_PREFIX` | `pipeline_rag` | `agentic_rag` | `pipeline_rag` | .env≠默认、env≠ex |
| `MINIO_BUCKET` | `pipeline-rag-document` | `agentic-rag` | `pipeline-rag-document` | .env≠默认、env≠ex |
| `MINIO_SECURE` | `False` | `false` | `false` | .env≠默认、ex≠默认 |
| `NEO4J_ENABLED` | `False` | `true` | `false` | .env≠默认、ex≠默认、env≠ex |
| `NEO4J_PASSWORD` | `neo4j` | `password` | `neo4j` | .env≠默认、env≠ex |
| `LLM_API_KEY` | `` | `sk-8****` | `your****` | .env≠默认、ex≠默认、env≠ex |
| `LLM_BASE_URL` | `https://api.deepseek.com` | `https://api.deepseek.com` | `https://dashscope.aliyuncs.com/compat...` | ex≠默认、env≠ex |
| `LLM_EMBEDDING_API_KEY` | `` | `sk-a****` | `your****` | .env≠默认、ex≠默认、env≠ex |
| `LLM_EMBEDDING_BASE_URL` | `https://dashscope.aliyuncs.com/compat...` | `https://api.siliconflow.cn/v1` | `https://dashscope.aliyuncs.com/compat...` | .env≠默认、env≠ex |
| `LLM_EMBEDDING_MODEL` | `text-embedding-v3` | `BAAI/bge-m3` | `text-embedding-v4` | .env≠默认、ex≠默认、env≠ex |
| `LLM_MODEL` | `deepseek-v4-flash` | `deepseek-v4-flash` | `qwen-plus-latest` | ex≠默认、env≠ex |
| `LLM_TEMPERATURE` | `0.5` | `0.5` | `0.7` | ex≠默认、env≠ex |
| `RERANK_API_KEY` | `` | `sk-a****` | `your****` | .env≠默认、ex≠默认、env≠ex |
| `RERANK_ENABLED` | `False` | `true` | `false` | .env≠默认、ex≠默认、env≠ex |
| `TAVILY_API_KEY` | `` | `your****` | `your****` | .env≠默认、ex≠默认 |
| `CHUNK_LLM_ENABLED` | `False` | `—` | `false` | ex≠默认 |
| `CHUNK_RECOMMEND_LLM_WHEN_LOW_QUALITY` | `True` | `—` | `true` | ex≠默认 |
| `MEMORY_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `RAG_ANSWER_SYSTEM_PROMPT` | `` | `你是一个严谨的文档知识库问答助手。严格遵循：1. 只基于"证据材料"回答，...` | `—` | .env≠默认 |
| `RAG_CANDIDATE_TOP_K` | `6` | `30` | `—` | .env≠默认 |
| `RAG_EVALUATION_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `RAG_EVALUATION_SAMPLE_RATE` | `0.0` | `—` | `1.0` | ex≠默认 |
| `RAG_KEYWORD_TOP_K` | `5` | `20` | `8` | .env≠默认、ex≠默认、env≠ex |
| `RAG_MIN_VECTOR_SIMILARITY` | `0.55` | `—` | `0.45` | ex≠默认 |
| `RAG_RERANK_MIN_SCORE` | `0.0` | `0.1` | `—` | .env≠默认 |
| `RAG_REWRITE_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `RAG_REWRITE_THINKING` | `False` | `—` | `false` | ex≠默认 |
| `RAG_SUPERVISOR_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `RAG_VECTOR_TOP_K` | `5` | `20` | `8` | .env≠默认、ex≠默认、env≠ex |
| `RATE_LIMIT_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `RECOMMEND_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `STRUCTURE_AMBIGUITY_CONFIDENCE_CEIL` | `0.8` | `—` | `0.80` | ex≠默认 |
| `STRUCTURE_LLM_DISAMBIGUATION_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `JWT_EXPIRE_MINUTES` | `480` | `720` | `720` | .env≠默认、ex≠默认 |
| `JWT_SECRET_KEY` | `pipe****` | `agen****` | `chan****` | .env≠默认、ex≠默认、env≠ex |
| `CB_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `SAFETY_INPUT_INJECTION_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `SAFETY_INPUT_PII_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `SAFETY_OUTPUT_PII_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `SAFETY_OUTPUT_SENSITIVE_ENABLED` | `True` | `—` | `true` | ex≠默认 |
| `SAFETY_TOOL_APPROVAL_ENABLED` | `True` | `—` | `true` | ex≠默认 |

共 49 项。**待你确认的关键决策**：
1. **检索参数调大**：`RAG_VECTOR_TOP_K=20`/`RAG_KEYWORD_TOP_K=20`/`RAG_CANDIDATE_TOP_K=30`（代码默认 5/5/6）——有意调参还是测试残留？
2. **`agentic_rag` 前缀系列**：`MYSQL_DB`/`POSTGRES_DB`/`ES_INDEX_PREFIX`/`MINIO_BUCKET`/`MYSQL_USER` 均为 `agentic_rag*`（代码/示例默认 `pipeline_rag*`）——疑似项目改名残留，是否统一回 `pipeline_rag`？
3. **`RAG_EVALUATION_SAMPLE_RATE`**：.env 未设置（实际生效 0.0），`.env.example` 写 1.0——照抄示例会全量评估，确认期望值（0.0/1.0/采样比）？
4. **LLM 配置漂移**：`.env` 用 deepseek-v4-flash + BGE-M3(siliconflow)，`.env.example` 仍是 qwen-plus-latest + text-embedding-v4(dashscope)——示例是否更新为 .env 实际方案？
5. **`RERANK_ENABLED`/`NEO4J_ENABLED`**：.env=true（本地启用）vs 示例 false——确认示例默认值是否改为 true。
---

## 附录：C6 决策确认与执行记录（2026-08-15）

| 决策 | 你的确认 | 执行结果 |
|------|---------|----------|
| 1. Top-K | 你询问标准 → 建议保留 20/20/30（宽召回+窄精排，业界标准） | ✅ `.env.example` 固化 20/20/30 + 注释；`.env` 保持 |
| 2. agentic_rag 前缀 | 统一 | ✅ `.env` 的 `MYSQL_DB`/`POSTGRES_DB`/`ES_INDEX_PREFIX`/`MINIO_BUCKET` 统一为 `pipeline_rag*`（`MYSQL_USER` 保留——是数据库账户名非前缀残留） |
| 3. 评估采样率 | 你询问建议 → 建议 0.1（10%，全量会让成本翻倍） | ✅ `.env.example` 1.0→0.1 + 注释 |
| 4. LLM 配置漂移 | 示例更新为实际方案 | ✅ `.env.example`：deepseek-v4-flash / BGE-M3(siliconflow) / temperature 0.5 |
| 5. RERANK/NEO4J | 示例改为实际 | ✅ `.env.example`：两者 `=true` |

**顺带修复（决策 4 的延伸）**：`.env` 使用 BGE-M3（1024 维）但未设 `LLM_EMBEDDING_DIMENSIONS` → 代码按默认 1536 走；已补 `LLM_EMBEDDING_DIMENSIONS=1024` 并清理旧死变量 `EMBEDDING_MODEL`/`EMBEDDING_DIMENSIONS`。

### ⚠️ 数据库迁移提示（决策 2 的副作用）
`.env` 的库名/桶名已改为 `pipeline_rag*`，**本地已有 `agentic_rag*` 数据的需要手动迁移**：

```bash
# MySQL：新建库并授权（如有存量数据需 mysqldump 导入）
mysql -uroot -p -e "CREATE DATABASE pipeline_rag CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON pipeline_rag.* TO 'agentic_rag_app'@'%';"

# Postgres：新建库 + pgvector
psql -U postgres -c "CREATE DATABASE pipeline_rag_vector;"
psql -U postgres -d pipeline_rag_vector -c "CREATE EXTENSION IF NOT EXISTS vector;"

# ES：新前缀索引会由启动时 route sync 自动创建，旧 agentic_rag_* 索引可手动删除
# MinIO：应用启动会自动创建 pipeline-rag-document 桶，旧桶可手动清理
```

> 若不想迁移本地数据，可临时在 `.env` 保留旧库名——两个库名仅影响连接目标，代码/示例已全部统一为 `pipeline_rag*`。
