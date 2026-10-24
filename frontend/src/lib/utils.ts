import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 统一从 catch 变量提取错误信息（TS6 catch 变量为 unknown） */
export function errorMessage(e: unknown, fallback = ''): string {
  if (e instanceof Error) {
    return e.message || fallback;
  }
  const text = String(e ?? '');
  return text && text !== 'undefined' ? text : fallback;
}

/** 超长文本截断，统一追加省略号；空值原样返回空串 */
export function truncate(value: string, maxLength: number): string {
  if (!value) {
    return '';
  }
  return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value;
}
