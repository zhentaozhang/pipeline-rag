import React from 'react';
import { cn } from '../../lib/utils';

interface AdminPanelProps {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}

/** 后台的分区卡片：标题栏 + 内容区，圆角与边框走语义令牌 */
export const AdminPanel: React.FC<AdminPanelProps> = ({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
}) => (
  <section className={cn('overflow-hidden rounded-xl border border-border bg-card', className)}>
    {title || actions ? (
      <header className="flex flex-col gap-2 border-b border-border px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          {description ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </header>
    ) : null}
    <div className={cn('p-5', bodyClassName)}>{children}</div>
  </section>
);
