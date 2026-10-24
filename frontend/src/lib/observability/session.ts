import { sessionTitle as buildSessionTitle } from '../sessionUtils'

/** 后台列表用的会话标题：保留“未命名会话”文案与 28 字上限，标题来源与聊天侧一致。 */
export function sessionTitle(session) {
  return buildSessionTitle(session, { fallback: '未命名会话', maxLength: 28 })
}
