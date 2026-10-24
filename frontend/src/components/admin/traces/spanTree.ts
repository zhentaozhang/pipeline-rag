import type { TraceSpan } from '../../../types/api';

export interface SpanNode extends TraceSpan {
  depth: number;
}

/** 按 parentSpanId 还原调用树，并保留原始顺序做深度优先展开 */
export function buildSpanTree(spans: TraceSpan[]): SpanNode[] {
  const byParent = new Map<string | null, TraceSpan[]>();
  spans.forEach((span) => {
    const parent = span.parentSpanId ?? null;
    const list = byParent.get(parent) ?? [];
    list.push(span);
    byParent.set(parent, list);
  });

  const knownIds = new Set(spans.map((span) => span.spanId));
  const ordered: SpanNode[] = [];
  const walk = (parent: string | null, depth: number) => {
    (byParent.get(parent) ?? []).forEach((span) => {
      ordered.push({ ...span, depth });
      walk(span.spanId, depth + 1);
    });
  };
  // 根节点的 parent 为空或指向不存在的 span（被裁掉的父节点），都当根处理
  const roots = spans.filter((span) => !span.parentSpanId || !knownIds.has(span.parentSpanId));
  roots.forEach((root) => {
    ordered.push({ ...root, depth: 0 });
    walk(root.spanId, 1);
  });
  spans.forEach((span) => {
    if (!ordered.some((item) => item.spanId === span.spanId)) ordered.push({ ...span, depth: 0 });
  });
  return ordered;
}
