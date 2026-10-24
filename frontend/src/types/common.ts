/**
 * 跨域共用的 API 包裹类型（与后端 VO 对齐，CamelModel 输出 camelCase）
 */

/** 后端统一响应包裹：{ code, data, message } */
export interface ApiEnvelope<T = unknown> {
  code: number | string;
  message: string | null;
  data: T;
}
