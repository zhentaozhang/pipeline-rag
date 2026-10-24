import { getAdminToken, clearAdminAuth } from '../adminAuth';
import type { SessionPageResponse } from '../../types/api';

/** 前端会话列表分页结果（listSessionsPage 映射后的 shape，字段为字符串形态） */
export interface SessionPageResult {
  pageNo: string;
  pageSize: string;
  totalSize: string;
  totalPages: string;
  sessions: SessionPageResponse['sessions'];
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const REQUEST_TIMEOUT = 30000;

export class APIError extends Error {
  status?: number;
  cause?: unknown;

  constructor(message: string, status?: number, cause?: unknown) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.cause = cause;
  }
}

export function buildApiUrl(path: string): string {
  return API_BASE_URL ? new URL(path, API_BASE_URL).toString() : path;
}

export type ApiRequestBody = Record<string, unknown> | unknown[] | string | null | undefined;

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: ApiRequestBody;
}

function getVisitorId(): string {
  if (typeof window === 'undefined' || !window.localStorage) {
    return '';
  }
  let vid = localStorage.getItem('pipeline_visitor_id');
  if (!vid) {
    vid = typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : 'v_' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
    localStorage.setItem('pipeline_visitor_id', vid);
  }
  return vid;
}

export function buildAuthHeaders(headers: Record<string, string> = {}): Record<string, string> {
  const visitorId = getVisitorId();
  const baseHeaders: Record<string, string> = { ...headers };
  if (visitorId && !baseHeaders['X-Visitor-Id']) {
    baseHeaders['X-Visitor-Id'] = visitorId;
  }
  const token = getAdminToken();
  if (!token) {
    return baseHeaders;
  }
  return {
    Authorization: `Bearer ${token}`,
    ...baseHeaders
  };
}

function handleUnauthorized(response: Response) {
  if (response.status !== 401) {
    return;
  }
  clearAdminAuth();
  if (window.location.pathname.startsWith('/admin') && window.location.pathname !== '/admin/login') {
    window.location.href = '/admin/login';
  }
}

export function stringifyManageValue<T>(value: T): T {
  return stringifyValue(value as unknown) as T;
}

export function stringifyValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => stringifyValue(item));
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        stringifyValue(item),
      ])
    );
  }

  if (typeof value === 'number' || typeof value === 'bigint') {
    return String(value);
  }

  return value;
}

export async function parseJsonResponse(response: Response): Promise<unknown> {
  const rawText = await response.text();
  if (!rawText) {
    return null;
  }

  try {
    return JSON.parse(rawText) as unknown;
  } catch (error) {
    throw new APIError(`无法解析后端响应: ${rawText}`, response.status, error);
  }
}

export async function readResponseMessage(response: Response): Promise<string> {
  const rawText = await response.text();
  if (!rawText) {
    return `请求失败，状态码 ${response.status}`;
  }

  try {
    const payload = JSON.parse(rawText) as { message?: string; error?: string };
    return payload.message || payload.error || rawText;
  } catch {
    return rawText;
  }
}

export async function requestJson<T = unknown>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const response = await fetch(buildApiUrl(path), {
      method: options.method || 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...buildAuthHeaders(options.headers as Record<string, string> || {})
      },
      body: options.body ? (typeof options.body === 'string' ? options.body : JSON.stringify(options.body)) : undefined,
      signal: controller.signal
    });

    if (!response.ok) {
      handleUnauthorized(response);
      throw new APIError(await readResponseMessage(response), response.status);
    }

    if (response.status === 204) {
      return null as unknown as T;
    }

    return parseJsonResponse(response) as Promise<T>;
  } finally {
    clearTimeout(timeoutId);
  }
}

export function unwrapApiResponse<T>(payload: unknown, fallbackMessage = '请求失败'): T {
  const envelope = payload as { code?: unknown; message?: unknown; data?: unknown } | null;
  const code = String(envelope?.code ?? '');
  if (code !== '0') {
    throw new APIError(
      String(envelope?.message || fallbackMessage),
      Number(envelope?.code || 500),
      payload
    );
  }
  return (envelope?.data ?? null) as unknown as T;
}

export async function requestApiEnvelope<T = unknown>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const response = await fetch(buildApiUrl(path), {
      method: options.method || 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...buildAuthHeaders(options.headers as Record<string, string> || {})
      },
      body: options.body ? (typeof options.body === 'string' ? options.body : JSON.stringify(options.body)) : undefined,
      signal: controller.signal
    });

    if (!response.ok) {
      handleUnauthorized(response);
      throw new APIError(await readResponseMessage(response), response.status);
    }

    const payload = await parseJsonResponse(response);
    return unwrapApiResponse(payload) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function requestMultipartApiEnvelope<T = unknown>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const response = await fetch(buildApiUrl(path), {
      method: options.method || 'POST',
      headers: {
        ...buildAuthHeaders(options.headers as Record<string, string> || {})
      },
      body: formData,
      signal: controller.signal
    });

    if (!response.ok) {
      handleUnauthorized(response);
      throw new APIError(await readResponseMessage(response), response.status);
    }

    const payload = await parseJsonResponse(response);
    return unwrapApiResponse(payload) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function normalizePageString(value: unknown, fallbackValue: string): string {
  const normalized = String(value ?? fallbackValue).trim();
  return normalized || String(fallbackValue);
}
