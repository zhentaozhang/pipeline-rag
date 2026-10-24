/**
 * Manage 域 API 类型：文档管理 / 策略方案
 * 与后端 VO 对齐，CamelModel 输出 camelCase
 */

/** 文档视图（DocumentVO） */
export interface ManageDocument {
  documentId: string;
  documentName: string;
  originalFileName: string;
  fileType: number | null;
  fileTypeName: string | null;
  fileSize: number | null;
  charCount: number | null;
  tokenCount: number | null;
  parseStatus: number | null;
  parseStatusName: string | null;
  strategyStatus: number | null;
  strategyStatusName: string | null;
  indexStatus: number | null;
  indexStatusName: string | null;
  parseErrorMsg: string | null;
  knowledgeScopeCode: string | null;
  knowledgeScopeName: string | null;
  businessCategory: string | null;
  documentTags: string | null;
  currentPlanId: number | null;
  lastIndexTaskId: string | null;
  latestTaskId: string | null;
  latestTaskType: number | null;
  latestTaskTypeName: string | null;
  latestTaskStatus: number | null;
  latestTaskStatusName: string | null;
  editTime: string | null;
  status: number | null;
}

/** 文档分页响应（DocumentPageResponse） */
export interface DocumentPageResponse {
  records: ManageDocument[];
  total: number;
  pageNo: number;
  pageSize: number;
}

/** 策略步骤（StrategyPlanStepVO） */
export interface StrategyPlanStep {
  planStepId: string;
  stepNo: number;
  strategyType: number;
  strategyRole: number;
  strategyName?: string | null;
  strategyRoleName?: string | null;
  recommendReason?: string | null;
}

/** 策略流水线（StrategyPipelineVO） */
export interface StrategyPipeline {
  steps: StrategyPlanStep[];
}

/** 策略方案（StrategyPlanVO） */
export interface StrategyPlan {
  planId: string;
  planStatus: number;
  recommendReason?: string | null;
  parentPipeline?: StrategyPipeline | null;
  childPipeline?: StrategyPipeline | null;
}

/** 策略方案响应（StrategyPlanResponse） */
export interface StrategyPlanResponse {
  planReady: boolean;
  documentId?: string | null;
  parseStatus?: string | null;
  plan?: StrategyPlan | null;
}
