import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { SessionItem } from './SessionItem';
import type { ChatSession } from '../../types/api';

const NOW = new Date(2026, 2, 10, 15, 0, 0, 0).getTime();

function makeSession(overrides: Partial<ChatSession> = {}): ChatSession {
  return {
    id: 1,
    conversationId: 'c-1',
    title: '季度报告复盘',
    createdAt: new Date(NOW - 3 * 86_400_000).toISOString(),
    chatMode: 'OPEN_CHAT',
    exchangeCount: 1,
    memorySummary: '',
    running: false,
    checkpointCount: 0,
    messageCount: 2,
    latestUserMessage: '',
    latestAssistantMessage: '',
    latestExchangeId: null,
    latestTurnStatus: 'SUCCESS',
    latestTurnErrorMessage: '',
    selectedDocumentId: '',
    selectedDocumentName: '',
    updatedAt: new Date(NOW - 2 * 60_000).toISOString(),
    isPinned: false,
    ...overrides,
  };
}

function renderItem(
  session: ChatSession = makeSession(),
  props: Partial<Parameters<typeof SessionItem>[0]> = {}
) {
  const handlers = {
    onSelect: vi.fn(),
    onRename: vi.fn(),
    onTogglePin: vi.fn(),
    onDelete: vi.fn(),
    ...props,
  };
  render(
    <ul>
      <SessionItem
        session={session}
        active={false}
        now={NOW}
        onSelect={handlers.onSelect}
        onRename={handlers.onRename}
        onTogglePin={handlers.onTogglePin}
        onDelete={handlers.onDelete}
        {...props}
      />
    </ul>
  );
  return handlers;
}

// 行按钮的无障碍名称以标题开头；操作按钮是「会话操作：标题」，用它排除掉
const rowButton = (name = '季度报告复盘') =>
  screen.getByRole('button', { name: new RegExp(`^${name}`) });

describe('SessionItem', () => {
  it('当前会话带 aria-current="page"，并用左侧主色条标出选中态', () => {
    renderItem(makeSession(), { active: true });
    const row = rowButton();

    expect(row).toHaveAttribute('aria-current', 'page');
    expect(row.closest('li')?.querySelector('.bg-primary')).not.toBeNull();
    // 时间也要显示出来：列表里只有标题的话，用户分不清哪个是刚聊的
    expect(screen.getByText('2 分钟前')).toBeInTheDocument();
  });

  it('非当前会话没有 aria-current，也没有主色条', () => {
    renderItem();
    const row = rowButton();

    expect(row).not.toHaveAttribute('aria-current');
    expect(row.closest('li')?.querySelector('.bg-primary')).toBeNull();
  });

  it('点击条目回调会话 id', () => {
    const { onSelect } = renderItem(makeSession({ conversationId: 'abc' }));
    fireEvent.click(rowButton());
    expect(onSelect).toHaveBeenCalledWith('abc');
  });

  it('流式生成中禁用跳转，避免打断正在输出的回答', () => {
    const { onSelect } = renderItem(makeSession(), { disabled: true });
    const row = rowButton();

    expect(row).toBeDisabled();
    fireEvent.click(row);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('操作菜单是可访问的 menu，含三项，且删除是危险项', () => {
    renderItem();
    fireEvent.click(screen.getByRole('button', { name: /会话操作/ }));

    const menu = screen.getByRole('menu', { name: /会话操作/ });
    expect(within(menu).getAllByRole('menuitem')).toHaveLength(3);
    expect(within(menu).getByRole('menuitem', { name: '置顶' })).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: '删除' })).toHaveClass('text-destructive');
  });

  it('置顶项按当前状态显示，点击后回调相反的置顶值', () => {
    const { onTogglePin } = renderItem(makeSession({ isPinned: true }));
    fireEvent.click(screen.getByRole('button', { name: /会话操作/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: '取消置顶' }));

    expect(onTogglePin).toHaveBeenCalledWith('c-1', false);
  });

  it('删除要先过二次确认，文案说明不可恢复；取消则不删除', () => {
    const { onDelete } = renderItem();
    fireEvent.click(screen.getByRole('button', { name: /会话操作/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: '删除' }));

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('无法恢复');

    fireEvent.click(within(dialog).getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /会话操作/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: '删除' }));
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: '删除' })
    );
    expect(onDelete).toHaveBeenCalledWith('c-1');
  });

  it('重命名是行内输入：带 label、自动聚焦、Enter 提交', () => {
    const { onRename } = renderItem();
    fireEvent.click(screen.getByRole('button', { name: /会话操作/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: '重命名' }));

    const input = screen.getByLabelText('会话标题');
    expect(input).toHaveFocus();
    expect(input).toHaveValue('季度报告复盘');

    fireEvent.change(input, { target: { value: '  季度报告复盘 v2  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRename).toHaveBeenCalledWith('c-1', '季度报告复盘 v2');
    expect(screen.queryByLabelText('会话标题')).not.toBeInTheDocument();
  });

  it('失焦提交，Esc 取消（不提交）', () => {
    const { onRename } = renderItem();
    fireEvent.click(screen.getByRole('button', { name: /会话操作/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: '重命名' }));

    const input = screen.getByLabelText('会话标题');
    fireEvent.change(input, { target: { value: '失焦提交' } });
    fireEvent.blur(input);
    expect(onRename).toHaveBeenCalledWith('c-1', '失焦提交');

    fireEvent.click(screen.getByRole('button', { name: /会话操作/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: '重命名' }));
    const again = screen.getByLabelText('会话标题');
    fireEvent.change(again, { target: { value: '不该提交' } });
    fireEvent.keyDown(again, { key: 'Escape' });

    expect(screen.queryByLabelText('会话标题')).not.toBeInTheDocument();
    expect(onRename).toHaveBeenCalledTimes(1);
  });

  it('空标题不提交（避免把会话改成无名）', () => {
    const { onRename } = renderItem();
    fireEvent.click(screen.getByRole('button', { name: /会话操作/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: '重命名' }));

    const input = screen.getByLabelText('会话标题');
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('会话标题')).not.toBeInTheDocument();
  });
});
