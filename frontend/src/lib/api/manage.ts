import { documentApi } from './manage/documents';
import { knowledgeApi } from './manage/knowledge';
import { observabilityApi } from './manage/observability';

/** 管理端接口集合：分组对象 spread 组合，方法签名与拆分前完全一致 */
export const manageApi = {
  ...observabilityApi,
  ...documentApi,
  ...knowledgeApi,
};
