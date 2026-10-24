import type { StreamRequest } from '../../types/api';
import type { StreamHandlers } from '../http/stream';
import { APIError, buildApiUrl, buildAuthHeaders, readResponseMessage, sleep } from '../http/client';
import { consumeEventStream } from '../http/stream';

/** chatApi 的流式部分（被 api/chat.ts 用 spread 合回 chatApi） */
export const chatStreamApi = {
  openStream(payload: StreamRequest, handlers: StreamHandlers = {}) {
    const controller = new AbortController();

    // 断线重连（第二轮架构评审·可以优化 4）：
    // - 计数已消费事件，断线重连时通过 ?resume=N 让服务端重放未消费缓冲（避免重复渲染）
    // - 收到 done/error 事件或用户 abort 即停止重试
    // - 服务端已完成（缓冲含 done）→ 正常收尾；原流仍在执行 → 服务端返回「执行中」提示
    const MAX_RETRIES = 3;
    const RETRY_DELAYS_MS = [1000, 2000, 4000];

    const done = (async () => {
      let consumed = 0;
      let sawDone = false;
      let sawError = false;
      let attempt = 0;

      const wrappedHandlers: StreamHandlers = {
        onEvent: (event) => {
          consumed += 1;
          if (event.type === 'done') sawDone = true;
          if (event.type === 'error') sawError = true;
          handlers.onEvent?.(event);
        }
      };

      while (true) {
        if (controller.signal.aborted) {
          return;
        }

        const url = buildApiUrl(
          `/api/chat/stream${consumed > 0 ? `?resume=${consumed}` : ''}`
        );
        let response: Response;
        try {
          response = await fetch(url, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Accept: 'text/event-stream',
              ...buildAuthHeaders()
            },
            body: JSON.stringify(payload),
            signal: controller.signal
          });

          if (!response.ok) {
            throw new APIError(await readResponseMessage(response), response.status);
          }
          if (!response.body) {
            throw new APIError('当前浏览器不支持流式响应', 500);
          }

          await consumeEventStream(response.body, wrappedHandlers);

          // 正常收尾条件：收到 done / error，或用户主动中断
          if (sawDone || sawError || controller.signal.aborted) {
            return;
          }
        } catch (error) {
          if (controller.signal.aborted) {
            return;
          }
          // 客户端错误（4xx，如 400 参数校验失败、401 未认证、403 禁止访问、404、422、429 等）非网络/服务端抖动，不应重试，立即向上抛出
          if (error instanceof APIError && error.status >= 400 && error.status < 500) {
            throw error;
          }
          if (attempt >= MAX_RETRIES) {
            throw error instanceof APIError ? error : new APIError('网络连接中断，请稍后重试', 0, error);
          }
          handlers.onReconnect?.(attempt + 1, MAX_RETRIES);
          await sleep(RETRY_DELAYS_MS[attempt]);
          attempt += 1;
          continue;
        }

        // 流被截断（服务端断开但未完成且未抛出错误）：退避重连续传
        if (attempt >= MAX_RETRIES) {
          throw new APIError('连接中断，未能恢复完整回答', 0);
        }
        handlers.onReconnect?.(attempt + 1, MAX_RETRIES);
        await sleep(RETRY_DELAYS_MS[attempt]);
        attempt += 1;
      }
    })();

    return {
      controller,
      done
    };
  }
};
