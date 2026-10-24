import React from 'react';

interface AdminPageHeaderProps {
  /** 页面归属的上层栏目名，给面包屑感的弱化标签 */
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}

/**
 * 后台页面统一的头部：标题 + 一句话说明 + 右侧主操作。
 * 12 个页面此前各自拼 h1/p 与按钮行，间距与字号都不一致。
 */
export const AdminPageHeader: React.FC<AdminPageHeaderProps> = ({
  eyebrow,
  title,
  description,
  actions,
}) => (
  <div className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-start sm:justify-between">
    <div className="min-w-0">
      {eyebrow ? (
        <span className="block text-2xs font-medium uppercase tracking-widest text-muted-foreground">
          {eyebrow}
        </span>
      ) : null}
      <h1 className="mt-1 text-xl font-semibold text-foreground">{title}</h1>
      {description ? (
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted-foreground">{description}</p>
      ) : null}
    </div>
    {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
  </div>
);
