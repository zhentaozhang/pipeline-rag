import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatMessageItem } from './ChatMessageItem'
import type { Message } from './MessageList'

// store 是用选择器订阅的，mock 必须真的把选择器跑一遍；
// 否则「返回整个 state 对象」会让断言假通过（任何字段都 truthy）
const storeMock = vi.hoisted(() => ({
  state: {
    isStreaming: false,
    currentConversationId: 'conv-1',
    sendMessage: vi.fn(),
    regenerate: vi.fn(),
    editAndResend: vi.fn(),
  },
}))

vi.mock('../../store/chatStore', () => ({
  useChatStore: (selector?: (state: unknown) => unknown) =>
    selector ? selector(storeMock.state) : storeMock.state,
}))

vi.mock('../../lib/toast', () => ({ toast: vi.fn() }))

vi.mock('./MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div data-testid="md">{content}</div>,
}))

function makeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: 'm1',
    role: 'assistant',
    content: '答案',
    createdAt: new Date().toISOString(),
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  storeMock.state.isStreaming = false
})

describe('ChatMessageItem', () => {
  it('渲染回答内容', () => {
    render(<ChatMessageItem message={makeMessage()} />)
    expect(screen.getByTestId('md')).toHaveTextContent('答案')
  })

  it('渲染来源标题', () => {
    const message = makeMessage({
      references: [{ id: 1, title: '部署手册', source_type: 'document' }],
    })
    render(<ChatMessageItem message={message} />)
    expect(screen.getByText('部署手册')).toBeInTheDocument()
    expect(screen.getByLabelText('参考来源')).toBeInTheDocument()
  })

  it('引用是可展开的按钮：aria-expanded 正确，Escape 收起（P1-5）', () => {
    const message = makeMessage({
      references: [{ id: 1, title: '手册', content: '原文段落内容' }],
    })
    render(<ChatMessageItem message={message} />)

    expect(screen.queryByText('原文段落内容')).not.toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: /手册/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    const controlled = toggle.getAttribute('aria-controls')
    expect(controlled).toBeTruthy()

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('原文段落内容')).toBeInTheDocument()
    // aria-controls 指向的确实是展开出来的那块区域
    expect(document.getElementById(controlled as string)).toBeInTheDocument()

    fireEvent.keyDown(toggle, { key: 'Escape' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('原文段落内容')).not.toBeInTheDocument()
  })

  it('没有正文但有链接的引用渲染成外链', () => {
    const message = makeMessage({
      references: [{ id: 1, title: '手册', url: 'https://example.com' }],
    })
    render(<ChatMessageItem message={message} />)
    const link = screen.getByRole('link', { name: /打开外部来源/ })
    expect(link).toHaveAttribute('href', 'https://example.com')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('失败气泡的重试直接调 store.regenerate，账号不再自己扫描消息数组（P1-2）', () => {
    const message = makeMessage({ id: 'exchange-7-assistant', content: '', status: 'FAILED', errorMessage: '连接中断' })
    render(<ChatMessageItem message={message} />)

    expect(screen.getByText('这一轮回答失败了')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(storeMock.state.regenerate).toHaveBeenCalledWith('exchange-7-assistant')
  })

  it('用户消息可以编辑后重发，走 store.editAndResend（P1-2）', () => {
    const message = makeMessage({ id: 'exchange-7-user', role: 'user', content: '旧问题' })
    render(<ChatMessageItem message={message} />)

    fireEvent.click(screen.getByRole('button', { name: '编辑这条提问并重新发送' }))
    const textarea = screen.getByLabelText('修改提问内容')
    fireEvent.change(textarea, { target: { value: '改写后的问题' } })
    fireEvent.click(screen.getByRole('button', { name: '重新发送' }))

    expect(storeMock.state.editAndResend).toHaveBeenCalledWith('exchange-7-user', '改写后的问题')
  })
})
