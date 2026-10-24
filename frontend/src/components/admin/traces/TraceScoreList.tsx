import React from 'react';
import type { TraceScore } from '../../../types/api';
import { ScoreCell } from '../evaluation/ScoreCell';

const METRIC_LABELS: Record<string, string> = {
  faithfulness: '忠实度',
  context_recall: '上下文召回率',
  context_precision: '上下文精确率',
  answer_relevancy: '答案相关性',
  answer_correctness: '答案正确性',
};

/** 链路打分：指标名统一翻成中文，没有分数时引导去看评估看板 */
export const TraceScoreList: React.FC<{ scores: TraceScore[] }> = ({ scores }) => {
  if (scores.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
        这条链路还没有在线打分。到「评估看板」跑一次离线评估，或者等采样打分的任务命中它。
      </p>
    );
  }

  return (
    <dl className="flex flex-col gap-2">
      {scores.map((score) => (
        <div key={score.scoreId} className="rounded-lg border border-border bg-card px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <dt className="text-xs font-medium text-foreground">{METRIC_LABELS[score.metricName] ?? score.metricName}</dt>
            <dd>
              <ScoreCell value={score.value} />
            </dd>
          </div>
          {score.reason ? (
            <dd className="mt-1 text-2xs leading-relaxed text-muted-foreground">{score.reason}</dd>
          ) : null}
        </div>
      ))}
    </dl>
  );
};
