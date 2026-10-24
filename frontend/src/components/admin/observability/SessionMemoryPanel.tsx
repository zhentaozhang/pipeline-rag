import React from 'react';
import { RefreshCw } from 'lucide-react';
import { AdminPanel } from '../AdminPanel';
import { Button } from '../../ui/Button';

interface MemoryMeta {
  compressionApplied?: boolean;
  coveredExchangeCount?: number;
  summaryVersion?: string | number;
  compressionCount?: number;
  summaryText?: string;
}

/** 后端可能把摘要元信息塞进 memorySummary 的 JSON 字符串里，解析失败就当成纯文本展示 */
function parseMemory(raw: string): MemoryMeta {
  if (!raw) return {};
  const trimmed = raw.trim();
  if (!trimmed.startsWith('{')) return { summaryText: raw };
  try {
    return JSON.parse(trimmed) as MemoryMeta;
  } catch {
    return { summaryText: raw };
  }
}

/** 会话记忆摘要：长会话被压缩过时，要看得到压缩了几次、覆盖了几轮 */
export const SessionMemoryPanel: React.FC<{
  memorySummary: string;
  rebuilding: boolean;
  onRebuild: () => void;
}> = ({ memorySummary, rebuilding, onRebuild }) => {
  const meta = parseMemory(memorySummary || '');
  const summaryText = meta.summaryText || memorySummary || '';
  const facts = [
    { label: '是否压缩', value: meta.compressionApplied ? '已压缩' : '未压缩' },
    { label: '覆盖轮次', value: meta.coveredExchangeCount ?? 0 },
    { label: '摘要版本', value: meta.summaryVersion ?? '—' },
    { label: '压缩次数', value: meta.compressionCount ?? 0 },
  ];

  return (
    <AdminPanel
      title="会话记忆摘要"
      description="压缩后的历史上下文，问答时会作为背景注入"
      actions={
        <Button size="sm" variant="outline" onClick={onRebuild} loading={rebuilding}>
          <RefreshCw size={13} aria-hidden="true" />
          重建摘要
        </Button>
      }
    >
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {facts.map((fact) => (
          <div key={fact.label} className="rounded-lg bg-secondary/40 px-3 py-2">
            <dt className="text-2xs text-muted-foreground">{fact.label}</dt>
            <dd className="mt-0.5 font-mono text-sm tabular-nums text-foreground">{fact.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-secondary/20 p-3 text-xs leading-relaxed text-muted-foreground">
        {summaryText || '这个会话还没有生成摘要。轮次多了之后系统会自动压缩。'}
      </p>
    </AdminPanel>
  );
};
