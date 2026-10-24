import { errorMessage } from '../../lib/utils'

/**
 * 后台错误提示统一成「发生了什么。可以怎么做」两句式。
 * 第一句必须说清是哪一步坏了，第二句给出用户能立刻执行的下一步；
 * 后端返回的原始原因放在括号里补充，避免整句被技术信息淹没。
 */
function requestFailure(error: unknown, symptom: string, remedy: string): string {
  const detail = errorMessage(error).trim()
  if (!detail) return `${symptom}。${remedy}`
  return `${symptom}。${remedy}（错误详情：${detail}）`
}

/** 加载失败的说法：加载{what}失败 + 检查后端后重试 */
export function loadFailure(error: unknown, what: string): string {
  return requestFailure(error, `加载${what}失败`, '请检查后端服务是否在线，然后重试。')
}

/** 操作失败的说法：{action}失败 + 用户可执行的下一步 */
export function actionFailure(
  error: unknown,
  action: string,
  remedy = '请稍后重试；如果一直失败，请联系管理员查看服务日志。'
): string {
  return requestFailure(error, `${action}失败`, remedy)
}

export function formatMs(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) && num > 0 ? `${Math.round(num)} ms` : '—'
}

export function formatRatio(value: unknown, digits = 1): string {
  const num = Number(value)
  return Number.isFinite(num) ? `${(num * 100).toFixed(digits)}%` : '—'
}

export function formatNumber(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? num.toLocaleString('zh-CN') : '—'
}

/** 后端成本字段是美元计价，这里只做展示格式化，不做汇率换算 */
export function formatCost(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? `$${num.toFixed(4)}` : '—'
}

