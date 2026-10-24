import type {
  KnowledgeScope,
  KnowledgeTopic,
  RouteTracePage,
  TopicDocument,
} from '../../../types/api';
import { requestApiEnvelope, stringifyManageValue } from '../../http/client';

/** manageApi 的知识域/主题/画像/路由分组（被 api/manage.ts 用 spread 合回 manageApi） */
export const knowledgeApi = {
  saveKnowledgeScope(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/scope/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  deleteKnowledgeScope(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/scope/delete', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listKnowledgeScopes(): Promise<KnowledgeScope[]> {
    return requestApiEnvelope('/manage/knowledge/scope/list', {
      method: 'POST',
      body: {}
    });
  },

  saveKnowledgeTopic(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/topic/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  deleteKnowledgeTopic(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/topic/delete', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listKnowledgeTopics(payload: Record<string, unknown> = {}): Promise<KnowledgeTopic[]> {
    return requestApiEnvelope('/manage/knowledge/topic/list', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryDocumentProfile(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/document/profile/detail', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  regenerateDocumentProfile(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/document/profile/regenerate', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  batchRegenerateDocumentProfiles(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/document/profile/batch/regenerate', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listTopicDocuments(payload: Record<string, unknown> = {}): Promise<TopicDocument[]> {
    return requestApiEnvelope('/manage/knowledge/topic/document/list', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  saveTopicDocumentRelation(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/topic/document/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  removeTopicDocumentRelation(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/topic/document/remove', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryKnowledgeRouteTracePage(payload: Record<string, unknown> = {}): Promise<RouteTracePage> {
    return requestApiEnvelope<RouteTracePage>('/manage/knowledge/route/trace/page/query', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  }
};
