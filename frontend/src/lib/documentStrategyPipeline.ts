import { normalizeCode } from './manageFormat';

export const STRATEGY_LIBRARY = [
  {
    type: '1',
    label: '基于文档结构切块',
    description: '优先保留标题和章节边界'
  },
  {
    type: '2',
    label: '递归分块',
    description: '对超长内容继续裁剪兜底'
  },
  {
    type: '3',
    label: '语义分块',
    description: '优化主题边界和段落完整性'
  },
  {
    type: '4',
    label: '大模型智能切块',
    description: '处理复杂内容和低质量文本'
  }
];

export const STRATEGY_PIPELINE_LIBRARY = [
  {
    key: 'parent',
    code: 'PARENT',
    label: '父块流水线',
    description: '决定回答阶段看到的父块边界'
  },
  {
    key: 'child',
    code: 'CHILD',
    label: '子块流水线',
    description: '决定检索召回使用的子块边界'
  }
];

export function normalizeStrategyTypeList(selectedTypes: string[], strategyLibrary = STRATEGY_LIBRARY) {
  const seen = new Set<string>();
  const availableTypes = new Set(strategyLibrary.map((item) => item.type));
  const orderedTypes: string[] = [];

  (selectedTypes || []).forEach((item) => {
    const strategyType = normalizeCode(item);
    if (!strategyType || seen.has(strategyType) || !availableTypes.has(strategyType)) {
      return;
    }
    seen.add(strategyType);
    orderedTypes.push(strategyType);
  });

  return orderedTypes;
}

export function buildStrategyPreview(selectedTypes: string[], strategyLibrary = STRATEGY_LIBRARY) {
  return normalizeStrategyTypeList(selectedTypes, strategyLibrary)
    .map((type, index) => {
      const strategy = strategyLibrary.find((item) => item.type === type);
      return strategy ? { ...strategy, index, order: String(index + 1).padStart(2, '0') } : null;
    })
    .filter(Boolean) as any[];
}

export function buildStrategySignature(selectedTypes: string[], strategyLibrary = STRATEGY_LIBRARY) {
  return normalizeStrategyTypeList(selectedTypes, strategyLibrary).join('|');
}

export function resolvePlanPipeline(plan: any, pipelineKey: string) {
  if (!plan || !pipelineKey) {
    return null;
  }
  return pipelineKey === 'parent' ? plan.parentPipeline || null : plan.childPipeline || null;
}

export function extractPipelineStrategyTypes(plan: any, pipelineKey: string, strategyLibrary = STRATEGY_LIBRARY) {
  const pipeline = resolvePlanPipeline(plan, pipelineKey);
  return Array.isArray(pipeline?.steps)
    ? normalizeStrategyTypeList(pipeline.steps.map((item: any) => item.strategyType), strategyLibrary)
    : [];
}

export function buildPipelineStepPayload(selectedTypes: string[], strategyLibrary = STRATEGY_LIBRARY) {
  return buildStrategyPreview(selectedTypes, strategyLibrary).map((item, index) => ({
    stepNo: String(index + 1),
    strategyType: item.type
  }));
}
