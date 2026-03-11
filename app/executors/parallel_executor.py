"""
并行执行器 — 多 Worker 按拓扑依赖分层并行执行（层内 asyncio.gather），
最终由 AggregatorExecutor 综合输出。

层内并行设计：每个 Worker 共享 self.task.references 追加写入（asyncio 单线程安全），
层结束后将本层新增的 refs 按 worker 均分（最终由 _merge_references 去重）。
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schema import ExecutionPlan, SubPlan, WorkerResult
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.common.sse import SSEEventType, sse_event
from app.executors._labels import mode_label
from app.executors.aggregator_executor import AggregatorExecutor
from app.executors.base import ConversationExecutor
from app.executors.registry import ExecutorRegistry

logger = structlog.get_logger(__name__)


def _topological_layers(sub_plans: list[SubPlan]) -> list[list[SubPlan]]:
    plan_map = {sp.id: sp for sp in sub_plans}
    in_degree = {sp.id: len(sp.depends_on) for sp in sub_plans}
    dependents: dict[str, list[str]] = defaultdict(list)
    for sp in sub_plans:
        for dep_id in sp.depends_on:
            dependents[dep_id].append(sp.id)

    layers: list[list[SubPlan]] = []
    queue = [sp.id for sp in sub_plans if in_degree[sp.id] == 0]

    while queue:
        layers.append([plan_map[pid] for pid in queue])
        next_queue = []
        for pid in queue:
            for did in dependents.get(pid, []):
                in_degree[did] -= 1
                if in_degree[did] == 0:
                    next_queue.append(did)
        queue = next_queue

    planned = sum(len(layer) for layer in layers)
    if planned != len(sub_plans):
        raise ValueError(f"子计划存在循环依赖或孤立节点: planned={planned}, total={len(sub_plans)}")
    return layers


class ParallelExecutor(ConversationExecutor):
    """
    并行执行器 — 将 ExecutionPlan.sub_plans 按拓扑依赖分层，
    层内 asyncio.gather 并行执行，最终由 AggregatorExecutor 综合输出。
    """

    mode = ExecutionMode.MULTI_AGENT

    def __init__(self, db: AsyncSession, task: ChatTaskInfo, registry: ExecutorRegistry) -> None:
        self.db = db
        self.task = task
        self.registry = registry

    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        if not plan.sub_plans:
            yield sse_event(
                SSEEventType.TEXT,
                "无需并行处理。",
                conversation_id=self.task.conversation_id,
                exchange_id=self.task.exchange_id,
            )
            return

        self.task.executor_type = self.mode

        conv_id = self.task.conversation_id
        exch_id = self.task.exchange_id

        try:
            layers = _topological_layers(plan.sub_plans)
        except ValueError as e:
            logger.warning("sub_plan_topology_error", error=str(e))
            yield self._emit(SSEEventType.TEXT, f"子任务分解存在循环依赖，无法并行执行：{e}")
            return
        yield self._emit(
            SSEEventType.THINKING,
            f"正在并行处理 {len(plan.sub_plans)} 个子任务（共 {len(layers)} 层）…",
        )

        all_results: list[WorkerResult] = []

        for layer_idx, layer in enumerate(layers):
            yield self._emit(
                SSEEventType.THINKING, f"第 {layer_idx + 1} 层：{len(layer)} 个 Worker"
            )

            # 层内并行执行
            refs_before = len(self.task.references)
            layer_results = await asyncio.gather(*[self._run_single(sp) for sp in layer])
            layer_refs = self.task.references[refs_before:]

            for sp, result in zip(layer, layer_results, strict=True):
                label = mode_label(sp.mode)
                result.sub_plan_id = sp.id
                result.references = layer_refs

                question_preview = sp.question[:80]
                if result.error:
                    yield self._emit(SSEEventType.THINKING, f"[{label}] 执行失败：{result.error}")
                else:
                    summary = (
                        result.text[:120].replace("\n", " ").strip()
                        if result.text and result.text.strip()
                        else "无返回内容"
                    )
                    yield self._emit(
                        SSEEventType.THINKING, f"[{label}] ✅ {question_preview} → {summary}"
                    )
                all_results.append(result)

        yield self._emit(SSEEventType.THINKING, "正在综合多源信息…")

        aggregator = AggregatorExecutor()
        async for chunk in aggregator.synthesize_streaming(
            results=all_results,
            question=plan.original_question,
            style=plan.aggregation_style,
            conversation_id=conv_id,
            exchange_id=exch_id,
        ):
            yield chunk

        if aggregator.last_refs:
            self.task.references = aggregator.last_refs  # service.py will emit the reference SSE event

    async def _run_single(self, sp: SubPlan) -> WorkerResult:
        executor = self.registry.get(sp.mode)
        worker_plan = ExecutionPlan(
            mode=sp.mode,
            original_question=sp.question,
            rewritten_question=sp.question,
            sub_questions=sp.sub_questions,
            retrieval_document_ids=sp.doc_ids,
        )
        try:
            return await executor.execute_structured(worker_plan)
        except Exception as e:
            logger.exception("worker_failed", sub_plan_id=sp.id, mode=sp.mode)
            return WorkerResult(sub_plan_id=sp.id, mode=sp.mode, error=str(e))
