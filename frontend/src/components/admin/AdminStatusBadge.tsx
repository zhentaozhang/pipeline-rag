import React from 'react';
import { normalizeCode } from '../../lib/manageFormat';

interface AdminStatusBadgeProps {
  label?: string | null;
  type?: 'parse' | 'strategy' | 'index' | 'task' | 'default';
  code?: string | number | null;
}

export const AdminStatusBadge: React.FC<AdminStatusBadgeProps> = ({ 
  label = '', 
  code = '' 
}) => {
  const normalizedCode = normalizeCode(code);

  const getVariant = () => {
    if (normalizedCode === '3') return 'success';
    if (normalizedCode === '4') return 'destructive';
    if (normalizedCode === '2') return 'primary';
    if (normalizedCode === '1') return 'warning';
    return 'default';
  };

  const variant = getVariant();

  const dotColor = {
    success: 'bg-success',
    destructive: 'bg-destructive',
    primary: 'bg-primary animate-pulse',
    warning: 'bg-warning',
    default: 'bg-muted-foreground'
  }[variant];

  const borderColor = {
    success: 'border-success/30',
    destructive: 'border-destructive/30',
    primary: 'border-primary/30',
    warning: 'border-warning/30',
    default: 'border-border'
  }[variant];

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11px] font-medium border whitespace-nowrap bg-transparent text-foreground ${borderColor}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      {label || '未设置'}
    </span>
  );
};
