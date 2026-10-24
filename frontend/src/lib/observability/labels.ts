export const STATUS_LABELS = {
  RUNNING: '进行中',
  COMPLETED: '已完成',
  FAILED: '失败',
  STOPPED: '已停止',
  SKIPPED: '跳过',
  WARNING: '警告'
}

export const STATUS_TONES = {
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  STOPPED: 'stopped',
  SKIPPED: 'idle',
  WARNING: 'warning'
}

export const EXECUTION_MODE_LABELS = {
  RAG_CHAT: '文档检索问答',
  REACT_AGENT: 'Agent 自主执行',
  CLARIFICATION: '路由澄清'
}

export const RELATION_TYPE_LABELS = {
  FOLLOW_UP: '承接上文追问',
  TOPIC_SWITCH: '切换到新主题',
  FRESH_TOPIC: '独立新问题',
  UNKNOWN: '未识别'
}

export const RETRIEVAL_MODE_LABELS = {
  DIRECT_QUERY: '直接检索',
  SECTION_FOCUSED: '定向查章节',
  ANALYTIC_DECOMPOSITION: '拆成多个子问题',
  UNKNOWN: '未识别'
}

export function mapLabel(value, mapping, fallback = '未识别') {
  if (!value) {
    return fallback
  }
  return mapping[value] || value
}
