/**
 * Evaluation 域 API 类型：评估数据集
 * 与后端 VO 对齐，CamelModel 输出 camelCase
 */

/** 评估数据集项 */
export interface EvaluationDataset {
  id: number;
  question?: string;
  groundTruth?: string;
  status?: number;
  evalMessage?: string | null;
  faithfulnessScore?: number | null;
  answerRelevancyScore?: number | null;
  contextPrecisionScore?: number | null;
  contextRecallScore?: number | null;
  answerCorrectnessScore?: number | null;
  createdAt?: string | null;
  description?: string;
  [key: string]: unknown;
}
