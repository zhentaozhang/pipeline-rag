import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 统一从 catch 变量提取错误信息（TS6 catch 变量为 unknown） */
export function errorMessage(e: unknown, fallback = ''): string {
  if (e instanceof Error) {
    return e.message;
  }
  const text = String(e ?? '');
  return text && text !== 'undefined' ? text : fallback;
}
