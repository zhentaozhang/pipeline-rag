import { formatExecutionMode, formatRelationType, formatRetrievalMode } from './format'

/** 一轮 exchange 的自然语言摘要，用在观测详情页顶部。 */
export function buildExchangeStatusNarrative(exchange) {
  if (!exchange) {
    return ''
  }
  const trace = exchange.debugTrace || {}
  const intent = trace.intentResolution || null
  const parts = [
    `当前查看的是 exchange ${exchange.exchangeId}。`,
    `执行路径是“${formatExecutionMode(trace.executionMode)}”。`
  ]

  if (intent?.relationType) {
    parts.push(`系统把这句判定为“${formatRelationType(intent.relationType)}”。`)
  }
  if (intent?.retrievalMode) {
    parts.push(`检索策略是“${formatRetrievalMode(intent.retrievalMode)}”。`)
  }
  if (exchange.status === 'FAILED' && exchange.errorMessage) {
    parts.push(`当前结束原因：${exchange.errorMessage}`)
  } else if (exchange.status === 'COMPLETED') {
    parts.push('这轮已经成功完成，默认先看“结果与诊断”和“执行过程”两块。')
  }
  return parts.join(' ')
}
