import type { StreamEvent } from '../../types/api';
import { APIError } from './client';

export interface StreamHandlers {
  onEvent?: (event: StreamEvent) => void;
  onReconnect?: (attempt: number, maxRetries: number) => void;
}

export function dispatchStreamPayload(rawPayload: string, handlers: StreamHandlers) {
  if (!rawPayload) {
    return;
  }

  const payload = rawPayload.trim();
  if (!payload || payload === '[DONE]') {
    return;
  }

  try {
    handlers.onEvent?.(JSON.parse(payload) as StreamEvent);
  } catch (error) {
    throw new APIError(`无法解析后端流式事件: ${payload}`, 500, error);
  }
}

export function consumeEventBlock(block: string, handlers: StreamHandlers) {
  const normalizedBlock = block.trim();
  if (!normalizedBlock) {
    return;
  }

  if (normalizedBlock.startsWith('data:')) {
    const payload = normalizedBlock
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n');
    dispatchStreamPayload(payload, handlers);
    return;
  }

  normalizedBlock
    .split(/\r?\n/)
    .filter(Boolean)
    .forEach((line) => dispatchStreamPayload(line, handlers));
}

export async function consumeEventStream(stream: ReadableStream<Uint8Array>, handlers: StreamHandlers) {
  const reader = stream.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundaryIndex = buffer.search(/\r?\n\r?\n/);
    while (boundaryIndex !== -1) {
      const block = buffer.slice(0, boundaryIndex);
      const separatorMatch = buffer.slice(boundaryIndex).match(/^\r?\n\r?\n/);
      const separatorLength = separatorMatch ? separatorMatch[0].length : 2;
      buffer = buffer.slice(boundaryIndex + separatorLength);
      consumeEventBlock(block, handlers);
      boundaryIndex = buffer.search(/\r?\n\r?\n/);
    }

    if (done) {
      const tail = decoder.decode();
      if (tail) {
        buffer += tail;
      }
      if (buffer.trim()) {
        consumeEventBlock(buffer, handlers);
      }
      return;
    }
  }
}
