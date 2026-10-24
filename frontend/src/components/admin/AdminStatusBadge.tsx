import React from 'react';
import { normalizeCode } from '../../lib/manageFormat';

export type AdminStatusTone = 'success' | 'warning' | 'destructive' | 'primary' | 'default';

interface AdminStatusBadgeProps {
  label?: string | null;
  type?: 'parse' | 'strategy' | 'index' | 'task' | 'default';
  code?: string | number | null;
  /** 调用方已知语气（例如观测页 statusTone 的结果）时直接指定，优先于 code 映射 */
  tone?: AdminStatusTone;
  className?: string;
}

// 颜色之外再给圆点形状，色觉障碍用户也能区分状态（颜色不是唯一信息载体）
const TONE_STYLE: Record<AdminStatusTone, { box: string; dot: string }> = {
  success: { box: 'border-success/30 text-success', dot: 'bg-success' },
  warning: { box: 'border-warning/30 text-warning', dot: 'bg-warning' },
  destructive: { box: 'border-destructive/30 text-destructive', dot: 'bg-destructive' },
  primary: { box: 'border-primary/30 text-primary', dot: 'bg-primary animate-pulse' },
  default: { box: 'border-border text-muted-foreground', dot: 'bg-muted-foreground' },
};

function toneFromCode(code: unknown): AdminStatusTone {
  const normalized = normalizeCode(code);
  if (normalized === '3') return 'success';
  if (normalized === '4') return 'destructive';
  if (normalized === '2') return 'primary';
  if (normalized === '1') return 'warning';
  return 'default';
}

export const AdminStatusBadge: React.FC<AdminStatusBadgeProps> = ({
  label = '',
  type = 'default',
  code = '',
  tone,
  className = '',
}) => {
  const variant = tone ?? toneFromCode(code);
  const style = TONE_STYLE[variant];

  return (
    <span
      data-status-type={type}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border bg-transparent px-2.5 py-0.5 text-2xs font-medium text-foreground ${style.box} ${className}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {label || '未设置'}
    </span>
  );
};
