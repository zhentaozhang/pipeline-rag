import React from 'react';
import { cn } from '../../lib/utils';

export interface AdminStat {
  label: string;
  value: React.ReactNode;
  /** 数字口径说明：同一屏里的「总数」和「本页」混在一起最容易误读 */
  hint?: string;
  tone?: 'default' | 'primary' | 'success' | 'warning' | 'destructive';
}

const TONE_CLASS: Record<NonNullable<AdminStat['tone']>, string> = {
  default: 'text-foreground',
  primary: 'text-primary',
  success: 'text-success',
  warning: 'text-warning',
  destructive: 'text-destructive',
};

const COLUMN_CLASS: Record<number, string> = {
  2: 'grid-cols-2',
  3: 'grid-cols-2 md:grid-cols-3',
  4: 'grid-cols-2 md:grid-cols-4',
  5: 'grid-cols-2 md:grid-cols-3 lg:grid-cols-5',
};

/** 后台顶部的关键指标条：标签 + 大数字 + 口径说明 */
export const AdminStatGrid: React.FC<{ stats: AdminStat[]; columns?: number }> = ({
  stats,
  columns = 4,
}) => (
  <dl className={cn('grid gap-px overflow-hidden rounded-xl border border-border bg-border', COLUMN_CLASS[columns] ?? COLUMN_CLASS[4])}>
    {stats.map((stat) => (
      <div key={stat.label} className="flex flex-col gap-1 bg-card px-4 py-3.5">
        <dt className="text-2xs font-medium tracking-wide text-muted-foreground">{stat.label}</dt>
        <dd className={cn('font-mono text-2xl font-semibold tabular-nums', TONE_CLASS[stat.tone ?? 'default'])}>
          {stat.value}
        </dd>
        {stat.hint ? <p className="text-2xs leading-relaxed text-muted-foreground">{stat.hint}</p> : null}
      </div>
    ))}
  </dl>
);
