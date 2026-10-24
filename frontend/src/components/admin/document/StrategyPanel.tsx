import React, { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, Check, RefreshCw } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import {
  STRATEGY_LIBRARY,
  STRATEGY_PIPELINE_LIBRARY,
  buildPipelineStepPayload,
  buildStrategyPreview,
  extractPipelineStrategyTypes,
} from '../../../lib/documentStrategyPipeline';
import type { StrategyPlanResponse } from '../../../types/api';
import { useAsyncData } from '../../../lib/useAsyncData';
import { toast } from '../../../lib/toast';
import { Alert } from '../../ui/Alert';
import { Button } from '../../ui/Button';
import { Skeleton } from '../../ui/Skeleton';
import { AdminPanel } from '../AdminPanel';
import { actionFailure, loadFailure } from '../adminFormat';

interface StrategyPanelProps {
  documentId: string;
  onConfirmed?: () => void;
}

/** 单个流水线的选择与排序：选中的顺序就是实际执行顺序，所以要允许上下移动 */
const PipelineEditor: React.FC<{
  label: string;
  description: string;
  selected: string[];
  recommended: string[];
  onChange: (next: string[]) => void;
}> = ({ label, description, selected, recommended, onChange }) => {
  const toggle = (type: string) => {
    onChange(selected.includes(type) ? selected.filter((item) => item !== type) : [...selected, type]);
  };
  const move = (index: number, delta: number) => {
    const next = [...selected];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <AdminPanel title={label} description={description}>
      <div className="flex flex-wrap gap-2">
        {STRATEGY_LIBRARY.map((strategy) => {
          const active = selected.includes(strategy.type);
          const isRecommended = recommended.includes(strategy.type);
          return (
            <button
              key={strategy.type}
              type="button"
              aria-pressed={active}
              onClick={() => toggle(strategy.type)}
              className={`rounded-md border px-3 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                active
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-card text-muted-foreground hover:bg-secondary'
              }`}
            >
              {active ? <Check size={12} aria-hidden="true" className="mr-1 inline" /> : null}
              {strategy.label}
              {isRecommended ? (
                <span className="ml-1.5 rounded-full bg-accent px-1.5 py-px text-2xs text-accent-foreground">
                  推荐
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div className="mt-4 rounded-lg border border-border bg-secondary/30 p-3">
        <p className="text-2xs font-medium tracking-wide text-muted-foreground">执行顺序</p>
        {selected.length === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">还没有选择切块策略。至少选一种才能提交。</p>
        ) : (
          <ol className="mt-2 flex flex-col gap-1.5">
            {selected.map((type, index) => {
              const strategy = STRATEGY_LIBRARY.find((item) => item.type === type);
              return (
                <li key={type} className="flex items-center gap-2 rounded-md bg-card px-2.5 py-1.5">
                  <span className="w-5 font-mono text-2xs tabular-nums text-muted-foreground">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs text-foreground">
                    {strategy?.label ?? type}
                  </span>
                  <Button variant="ghost" size="icon-sm" onClick={() => move(index, -1)} disabled={index === 0} aria-label="上移">
                    <ArrowUp size={13} aria-hidden="true" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => move(index, 1)}
                    disabled={index === selected.length - 1}
                    aria-label="下移"
                  >
                    <ArrowDown size={13} aria-hidden="true" />
                  </Button>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </AdminPanel>
  );
};

/** 策略确认面板：展示推荐方案，允许人工调整父子块流水线后提交 */
export const StrategyPanel: React.FC<StrategyPanelProps> = ({ documentId, onConfirmed }) => {
  const { data, loading, error, refetch } = useAsyncData<StrategyPlanResponse>(
    () => manageApi.queryStrategyPlan(documentId),
    [documentId]
  );
  const [parentTypes, setParentTypes] = useState<string[]>([]);
  const [childTypes, setChildTypes] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const plan = data?.plan ?? null;
  const planReady = Boolean(data?.planReady && plan);

  useEffect(() => {
    if (!plan) return;
    setParentTypes(extractPipelineStrategyTypes(plan, 'parent'));
    setChildTypes(extractPipelineStrategyTypes(plan, 'child'));
  }, [plan]);

  const submit = async () => {
    if (parentTypes.length === 0 && childTypes.length === 0) {
      toast({ title: '还不能提交', description: '请至少为父块或子块流水线选择一种切块策略。', variant: 'error' });
      return;
    }
    setSubmitting(true);
    try {
      await manageApi.confirmStrategy({
        documentId,
        basePlanId: String(plan?.planId ?? '0'),
        parentSteps: buildPipelineStepPayload(parentTypes),
        childSteps: buildPipelineStepPayload(childTypes),
      });
      toast({ title: '策略已确认', description: '可以继续在「构建」分区里触发索引构建了。', variant: 'success' });
      refetch();
      onConfirmed?.();
    } catch (submitError) {
      toast({
        title: '确认策略失败',
        description: actionFailure(submitError, '确认策略', '请确认文档解析已完成，然后重试。'),
        variant: 'error',
      });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <AdminPanel title="切块策略">
        <Skeleton lines={5} />
      </AdminPanel>
    );
  }

  if (error) {
    return (
      <Alert
        variant="destructive"
        title="加载策略方案失败"
        action={<Button size="sm" variant="outline" onClick={refetch}>重试</Button>}
      >
        {loadFailure(error, '策略方案')}
      </Alert>
    );
  }

  if (!planReady) {
    return (
      <Alert
        variant="info"
        title="策略方案还在生成"
        action={<Button size="sm" variant="outline" onClick={refetch}><RefreshCw size={13} aria-hidden="true" />刷新</Button>}
      >
        文档解析完成后系统会给出推荐方案。如果长时间没有结果，请回到列表确认解析状态是否失败。
      </Alert>
    );
  }

  const recommendedParent = extractPipelineStrategyTypes(plan, 'parent');
  const recommendedChild = extractPipelineStrategyTypes(plan, 'child');
  const preview = buildStrategyPreview(parentTypes, STRATEGY_LIBRARY).map((item) => item.label).filter(Boolean);

  return (
    <div className="flex flex-col gap-4">
      {plan?.recommendReason ? (
        <Alert variant="info" title="推荐理由">
          {plan.recommendReason}
        </Alert>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <PipelineEditor
          label={STRATEGY_PIPELINE_LIBRARY[0].label}
          description={STRATEGY_PIPELINE_LIBRARY[0].description}
          selected={parentTypes}
          recommended={recommendedParent}
          onChange={setParentTypes}
        />
        <PipelineEditor
          label={STRATEGY_PIPELINE_LIBRARY[1].label}
          description={STRATEGY_PIPELINE_LIBRARY[1].description}
          selected={childTypes}
          recommended={recommendedChild}
          onChange={setChildTypes}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-5 py-4">
        <p className="text-xs leading-relaxed text-muted-foreground">
          父块流水线：{preview.length ? preview.join(' → ') : '未选择'}
        </p>
        <Button size="sm" onClick={submit} loading={submitting}>
          确认策略
        </Button>
      </div>
    </div>
  );
};
