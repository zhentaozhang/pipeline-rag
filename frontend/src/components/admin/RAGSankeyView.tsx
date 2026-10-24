import React from 'react';
import type { ChannelExecution, RetrievalResult } from '../../types/api';
import { formatNumber } from './adminFormat';

interface RAGSankeyViewProps {
  channelExecutions: ChannelExecution[];
  retrievalResults: RetrievalResult[];
  activeExchange: Record<string, unknown> | null;
}

interface FunnelNode {
  key: string;
  label: string;
  value: number;
  /** 用语义令牌而不是硬编码色值，暗色主题下才不会糊成一片 */
  color: string;
}

function countChannels(executions: ChannelExecution[]) {
  const lower = (value: unknown) => String(value ?? '').toLowerCase();
  return executions.reduce<{ vector: number; keyword: number }>(
    (acc, item) => {
      const count = Number(item?.recalled_count ?? item?.recalledCount ?? 0);
      if (lower(item?.channel).includes('vector')) acc.vector += count;
      else if (lower(item?.channel).includes('keyword')) acc.keyword += count;
      return acc;
    },
    { vector: 0, keyword: 0 }
  );
}

function countPhases(results: RetrievalResult[]) {
  const phaseOf = (item: RetrievalResult) => String(item?.phase ?? '').toUpperCase();
  const fusion = results.filter((item) => phaseOf(item) === 'FUSION').length;
  const rerank = results.filter((item) => phaseOf(item) === 'RERANK').length;
  // 老数据没有 phase 字段，用门禁与分数兜底，避免漏斗永远显示 0
  const passed = results.filter((item) => item?.gate_passed === true || Number(item?.score ?? 0) > 0).length;
  return { fusion: fusion || passed, rerank: rerank || passed };
}

const WIDTH = 900;
const HEIGHT = 300;
const COLUMNS = [40, 300, 580, 800];
const NODE_WIDTH = 14;

/** 检索漏斗：两路召回 → 融合 → 重排 → 最终引用，条形宽度与数量成正比 */
export const RAGSankeyView: React.FC<RAGSankeyViewProps> = ({
  channelExecutions,
  retrievalResults,
  activeExchange,
}) => {
  const channels = countChannels(channelExecutions);
  const phases = countPhases(retrievalResults);
  const references = Array.isArray(activeExchange?.references) ? activeExchange!.references as unknown[] : [];
  const finalCount = references.length;

  const nodes: FunnelNode[] = [
    { key: 'vector', label: '向量召回', value: channels.vector, color: 'var(--color-primary)' },
    { key: 'keyword', label: '关键词召回', value: channels.keyword, color: 'var(--color-warning)' },
    { key: 'fusion', label: '融合', value: phases.fusion, color: 'var(--color-success)' },
    { key: 'rerank', label: '重排', value: phases.rerank, color: 'var(--color-accent)' },
    { key: 'final', label: '最终引用', value: finalCount, color: 'var(--color-primary)' },
  ];

  const total = nodes.reduce((sum, node) => sum + node.value, 0);

  if (total === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-secondary/30 px-5 py-8 text-center">
        <p className="text-sm font-medium text-foreground">这一轮没有召回数据</p>
        <p className="mt-1 text-xs text-muted-foreground">
          可能是开放对话模式，或检索通道没有返回结果。切换到文档问答模式再试一次。
        </p>
      </div>
    );
  }

  const maxValue = Math.max(...nodes.map((node) => node.value), 1);
  const yOf = (node: FunnelNode, index: number) => {
    const spread = HEIGHT - 80;
    return 40 + (index / Math.max(nodes.length - 1, 1)) * spread * 0.2 + (1 - node.value / maxValue) * 40;
  };

  const summary = nodes.map((node) => `${node.label} ${formatNumber(node.value)}`).join('，');

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto">
        <svg
          role="img"
          aria-label={`检索漏斗：${summary}`}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-[260px] w-full min-w-[640px]"
        >
          <title>检索漏斗</title>
          {nodes.slice(0, nodes.length - 1).map((from, index) => {
            const to = nodes[index + 1];
            const x1 = COLUMNS[Math.min(index, COLUMNS.length - 1)] + NODE_WIDTH;
            const x2 = COLUMNS[Math.min(index + 1, COLUMNS.length - 1)];
            const y1 = yOf(from, index);
            const y2 = yOf(to, index + 1);
            const stroke = Math.max(2, (from.value / maxValue) * 26);
            return (
              <path
                key={`link-${from.key}`}
                d={`M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`}
                fill="none"
                stroke={from.color}
                strokeOpacity={0.25}
                strokeWidth={stroke}
                strokeLinecap="round"
              />
            );
          })}
          {nodes.map((node, index) => {
            const x = COLUMNS[Math.min(index, COLUMNS.length - 1)];
            const y = yOf(node, index);
            return (
              <g key={node.key}>
                <rect
                  x={x}
                  y={y - 14}
                  width={NODE_WIDTH}
                  height={`${Math.max(16, (node.value / maxValue) * 40)}`}
                  rx={4}
                  fill={node.color}
                  fillOpacity={0.85}
                />
                <text x={x + NODE_WIDTH + 8} y={y - 2} className="fill-current text-2xs" fill="currentColor">
                  {node.label}
                </text>
                <text x={x + NODE_WIDTH + 8} y={y + 12} className="fill-current text-2xs" fill="currentColor" fillOpacity={0.65}>
                  {formatNumber(node.value)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* 关键数字再以文本给一遍，不依赖图形传达信息 */}
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {nodes.map((node) => (
          <div key={`fact-${node.key}`} className="rounded-lg border border-border bg-card px-3 py-2">
            <dt className="flex items-center gap-1.5 text-2xs text-muted-foreground">
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: node.color }} />
              {node.label}
            </dt>
            <dd className="mt-0.5 font-mono text-sm tabular-nums text-foreground">{formatNumber(node.value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
};
