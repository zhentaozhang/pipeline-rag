import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatMessageItem } from './ChatMessageItem'
import type { Message } from './MessageList'

// Mock 依赖：store 与 markdown 渲染
vi.mock('../../store/chatStore', () => ({
  useChatStore: () => ({
    isStreaming: false,
    sendMessage: vi.fn(),
    rateExchange: vi.fn(),
  }),
}))

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

describe('ChatMessageItem', () => {
  it('renders message content', () => {
    render(<ChatMessageItem message={makeMessage()} />)
    expect(screen.getByTestId('md')).toHaveTextContent('答案')
  })

  it('renders sources with title', () => {
    const message = makeMessage({
      references: [{ id: 1, title: '部署手册', source_type: 'document' }],
    })
    render(<ChatMessageItem message={message} />)
    expect(screen.getByText('部署手册')).toBeInTheDocument()
  })

  it('expands source passage on click (P1-1 citation traceability)', () => {
    const message = makeMessage({
      references: [{ id: 1, title: '手册', content: '原文段落内容' }],
    })
    render(<ChatMessageItem message={message} />)
    // 初始不显示原文
    expect(screen.queryByText('原文段落内容')).not.toBeInTheDocument()
    // 点击引用卡片 → 展开原文
    fireEvent.click(screen.getByText('手册'))
    expect(screen.getByText('原文段落内容')).toBeInTheDocument()
  })

  it('does not expand source without content', () => {
    const message = makeMessage({
      references: [{ id: 1, title: '手册', url: 'https://example.com' }],
    })
    render(<ChatMessageItem message={message} />)
    const link = screen.getByText('手册').closest('a')
    expect(link).toHaveAttribute('href', 'https://example.com')
  })
})
