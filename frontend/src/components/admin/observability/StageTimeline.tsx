import React from 'react';
import { formatMs } from '../adminFormat';

export interface StageTrace {
  stageId?: string | number;
  stageName?: string;
  stageState?: string;
  startTime?: string;
  durationMs?: number;
  summaryText?: string;
}

const STATE_STYLE: Record<string, { chip: string; dot: string }> = {
  success: { chip: 'border-success/30 text-success', dot: 'bg-success' },
  completed: { chip: 'border-success/30 text-success', dot: 'bg-success' },
  running: { chip: 'border-primary/30 text-primary', dot: 'bg-primary animate-pulse' },
  failed: { chip: 'border-destructive/30 text-destructive', dot: 'bg-destructive' },
  error: { chip: 'border-destructive/30 text-destructive', dot: 'bg-destructive' },
  warning: { chip: 'border-warning/30 text-warning', dot: 'bg-warning' },
};

function styleOf(state: string | undefined) {
  return STATE_STYLE[String(state ?? '').toLowerCase()] ?? { chip: 'border-border text-muted-foreground', dot: 'bg-muted-foreground' };
}

/** 阶段时间线：把一轮问答拆成有序阶段，用耗时条的长短对比看出瓶颈在哪个阶段 */
export const StageTimeline: React.FC<{ stages: StageTrace[] }> = ({ stages }) => {
  if (stages.length === 0) {
    return (
      <p className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        这一轮没有记录阶段耗时。可能是较早的会话，或该轮在写阶段轨迹前就失败了。
      </p>
    );
  }

  const maxDuration = Math.max(...stages.map((stage) => Number(stage.durationMs ?? 0)), 1);

  return (
    <ol className="flex flex-col gap-2">
      {stages.map((stage, index) => {
        const style = styleOf(stage.stageState);
        const duration = Number(stage.durationMs ?? 0);
        const width = Math.max(2, Math.round((duration / maxDuration) * 100));
        return (
          <li key={String(stage.stageId ?? index)} className="rounded-lg border border-border bg-card px-3.5 py-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <span className="font-mono text-2xs text-muted-foreground">{String(index + 1).padStart(2, '0')}</span>
                <span className="text-xs font-medium text-foreground">{stage.stageName || '未命名阶段'}</span>
                <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-px text-2xs ${style.chip}`}>
                  <span aria-hidden="true" className={`h-1 w-1 rounded-full ${style.dot}`} />
                  {stage.stageState || '未知'}
                </span>
              </span>
              <span className="font-mono text-xs tabular-nums text-muted-foreground">{formatMs(duration)}</span>
            </div>
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-secondary" aria-hidden="true">
              <div
                className="h-full rounded-full bg-primary/70"
                style={{ width: `${width}%` }}
              />
            </div>
            {stage.summaryText ? (
              <p className="mt-1.5 text-2xs leading-relaxed text-muted-foreground">{stage.summaryText}</p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
};
