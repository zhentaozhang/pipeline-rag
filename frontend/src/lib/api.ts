/**
 * 前端 API 层 barrel：实现已按职责拆到 ./http 与 ./api 下各模块。
 * 本文件只做 re-export，保证原有 import 路径（'../lib/api' / '../../lib/api'）不变。
 */

export { chatApi, createConversationId } from './api/chat';

export { adminAuthApi } from './api/admin-auth';

export { manageApi } from './api/manage';

export { APIError } from './http/client';

export type { SessionPageResult } from './http/client';

export type { StreamHandlers } from './http/stream';
