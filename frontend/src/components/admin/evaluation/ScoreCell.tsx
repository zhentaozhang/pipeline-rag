import React from 'react';

/** RAGAS 分数：≥0.8 视为好、0.6~0.8 需要观察、<0.6 明显偏低；颜色之外一律带文字，避免只靠颜色传达 */
export const ScoreCell: React.FC<{ value: number | null | undefined }> = ({ value }) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return <span className="text-2xs text-muted-foreground">未评估</span>;
  }
  const score = Number(value);
  const view =
    score >= 0.8
      ? { label: '好', className: 'border-success/30 bg-success/10 text-success' }
      : score >= 0.6
        ? { label: '中', className: 'border-warning/30 bg-warning/10 text-warning' }
        : { label: '低', className: 'border-destructive/30 bg-destructive/10 text-destructive' };
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-flex rounded-md border px-1.5 py-px font-mono text-2xs tabular-nums ${view.className}`}>
        {score.toFixed(2)}
      </span>
      <span className="text-2xs text-muted-foreground">{view.label}</span>
    </span>
  );
};
