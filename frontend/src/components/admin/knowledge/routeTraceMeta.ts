import type { AdminStatusTone } from '../AdminStatusBadge';

/** 路由状态码 → 中文标签 + 语义色调（后端 1 成功 / 2 低置信 / 3 失败） */
export const routeStatusMeta = (code?: string | number | null): { label: string; tone: AdminStatusTone } => {
  const value = String(code ?? '');
  if (value === '1') return { label: '成功', tone: 'success' };
  if (value === '2') return { label: '低置信', tone: 'warning' };
  if (value === '3') return { label: '失败', tone: 'destructive' };
  return { label: '未记录', tone: 'default' };
};

/** 置信度统一按百分比展示，后端给的是 0–1 的小数 */
export const formatConfidence = (value?: string | number | null, digits = 1): string => {
  if (value === null || value === undefined || value === '') return '未记录';
  const num = Number(value);
  if (!Number.isFinite(num)) return '未记录';
  return `${(num * 100).toFixed(digits)}%`;
};
/** 列表选中态用会话 + 轮次做唯一键 */
export const routeTraceKey = (row: { conversationId?: string | number | null; exchangeId?: string | number | null }): string =>
  `${row.conversationId ?? ''}_${row.exchangeId ?? ''}`;
