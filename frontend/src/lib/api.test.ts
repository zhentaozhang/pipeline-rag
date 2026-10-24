import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { chatApi } from './api';

/**
 * 回归保护：最近几轮改动集中在「visitor-id 请求头」。
 * 这里锁定两个契约：
 *   1. 每个请求都带上 X-Visitor-Id，且同浏览器内稳定复用（写入 localStorage）
 *   2. 已存在的 visitor id 不被重新生成（否则每次请求都会被当作新访客）
 */

const VISITOR_KEY = 'pipeline_visitor_id';

function mockFetchOk(data: unknown = null) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ code: '0', data }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

function headersOf(init: RequestInit): Record<string, string> {
  return (init.headers || {}) as Record<string, string>;
}

describe('api visitor id header', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('首次请求生成并持久化 visitor id，后续请求复用同一个值', async () => {
    const calls = mockFetchOk();

    await chatApi.checkConnection();
    const first = localStorage.getItem(VISITOR_KEY);

    expect(first).toBeTruthy();
    expect(headersOf(calls[0].init)['X-Visitor-Id']).toBe(first);

    await chatApi.checkConnection();
    const second = localStorage.getItem(VISITOR_KEY);

    expect(second).toBe(first);
    expect(headersOf(calls[1].init)['X-Visitor-Id']).toBe(first);
  });

  it('已存在的 visitor id 不被重新生成', async () => {
    localStorage.setItem(VISITOR_KEY, 'fixed-visitor-id');
    const calls = mockFetchOk();

    await chatApi.checkConnection();

    expect(localStorage.getItem(VISITOR_KEY)).toBe('fixed-visitor-id');
    expect(headersOf(calls[0].init)['X-Visitor-Id']).toBe('fixed-visitor-id');
  });

  it('POST 请求同样携带 X-Visitor-Id，且不覆盖 Content-Type', async () => {
    localStorage.setItem(VISITOR_KEY, 'post-visitor-id');
    const calls = mockFetchOk({ pageNo: 1, pageSize: 20, total: 0, sessions: [] });

    await chatApi.listSessionsPage({ pageNo: '1', pageSize: '20' });

    const headers = headersOf(calls[0].init);
    expect(calls[0].init.method).toBe('POST');
    expect(headers['X-Visitor-Id']).toBe('post-visitor-id');
    expect(headers['Content-Type']).toBe('application/json');
  });
});

/**
 * 回归保护：checkConnection 曾经是 .catch(() => null)，
 * 调用方用 `res !== undefined` 判断，null !== undefined 恒为 true，
 * 于是「后端已断开」这个状态永远不可达，健康指示灯永远是绿的。
 * 现在它必须只是一个布尔值。
 */
describe('checkConnection 返回布尔值', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('后端正常时返回 true', async () => {
    mockFetchOk();
    await expect(chatApi.checkConnection()).resolves.toBe(true);
  });

  it('网络不可达时返回 false', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    await expect(chatApi.checkConnection()).resolves.toBe(false);
  });

  it('后端返回非 0 code 时返回 false', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ code: '500', message: 'boom' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )));
    await expect(chatApi.checkConnection()).resolves.toBe(false);
  });
});

