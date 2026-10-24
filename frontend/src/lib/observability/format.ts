import { truncate } from '../utils'
import {
  EXECUTION_MODE_LABELS,
  RELATION_TYPE_LABELS,
  RETRIEVAL_MODE_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
  mapLabel
} from './labels'

/** 字符串截断，统一从 lib/utils 复用（避免多份实现）。 */
export { truncate }

export function formatDateTime(value) {
  if (!value) {
    return '无'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '无'
  }
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(date)
}

export function formatChatMode(value) {
  if (value === 'DOCUMENT') {
    return '当前文档问答'
  }
  if (value === 'AUTO_DOCUMENT') {
    return '自动知识问答'
  }
  if (value === 'OPEN_CHAT') {
    return '开放式提问'
  }
  return value || '未知模式'
}

export function formatStatusLabel(value) {
  return STATUS_LABELS[value] || value || '未知状态'
}

export function statusTone(value) {
  return STATUS_TONES[value] || 'idle'
}

export function formatExecutionMode(value) {
  return mapLabel(value, EXECUTION_MODE_LABELS)
}

export function formatRelationType(value) {
  return mapLabel(value, RELATION_TYPE_LABELS)
}

export function formatRetrievalMode(value) {
  return mapLabel(value, RETRIEVAL_MODE_LABELS)
}
