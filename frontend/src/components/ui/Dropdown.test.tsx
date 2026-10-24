import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Dropdown } from './Dropdown';

function renderDropdown(onSelect = vi.fn()) {
  render(
    <Dropdown
      menuLabel="会话操作"
      trigger={(props) => (
        <button type="button" {...props}>
          更多操作
        </button>
      )}
      items={[
        { key: 'rename', label: '重命名', onSelect: () => onSelect('rename') },
        { key: 'pin', label: '置顶', onSelect: () => onSelect('pin') },
        { key: 'delete', label: '删除', onSelect: () => onSelect('delete'), danger: true },
      ]}
    />
  );
  return screen.getByRole('button', { name: '更多操作' });
}

describe('Dropdown', () => {
  it('默认不展开，点击触发器后出现带名称的菜单', () => {
    const trigger = renderDropdown();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(trigger);

    const menu = screen.getByRole('menu');
    expect(menu).toHaveAccessibleName('会话操作');
    expect(screen.getAllByRole('menuitem')).toHaveLength(3);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
  });

  it('展开后焦点落在第一项，方向键可在项之间移动', () => {
    renderDropdown();
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));

    const items = screen.getAllByRole('menuitem');
    expect(document.activeElement).toBe(items[0]);

    fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowDown' });
    expect(document.activeElement).toBe(items[1]);

    fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowUp' });
    expect(document.activeElement).toBe(items[0]);

    fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowUp' });
    expect(document.activeElement).toBe(items[2]);
  });

  it('点击菜单项触发回调、关闭菜单并把焦点还给触发器', () => {
    const onSelect = vi.fn();
    const trigger = renderDropdown(onSelect);
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('menuitem', { name: '删除' }));

    expect(onSelect).toHaveBeenCalledWith('delete');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it('Esc 关闭菜单并归还焦点', () => {
    const trigger = renderDropdown();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });
});
