import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './Tabs';

function Demo({ onChange }: { onChange?: (v: string) => void }) {
  const [value, setValue] = React.useState('a');
  return (
    <Tabs
      value={value}
      onValueChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
    >
      <TabsList>
        <TabsTrigger value="a" step="01">
          第一步
        </TabsTrigger>
        <TabsTrigger value="b" step="02">
          第二步
        </TabsTrigger>
        <TabsTrigger value="c" step="03">
          第三步
        </TabsTrigger>
      </TabsList>
      <TabsContent value="a">面板 A</TabsContent>
      <TabsContent value="b">面板 B</TabsContent>
      <TabsContent value="c">面板 C</TabsContent>
    </Tabs>
  );
}

import * as React from 'react';

describe('Tabs', () => {
  it('暴露 tablist / tab / tabpanel 语义并串联两端 id', () => {
    render(<Demo />);
    const list = screen.getByRole('tablist');
    expect(list).toBeInTheDocument();

    const tabA = screen.getByRole('tab', { name: /第一步/ });
    expect(tabA).toHaveAttribute('aria-selected', 'true');
    const panel = screen.getByRole('tabpanel');
    expect(panel).toHaveTextContent('面板 A');
    expect(panel).toHaveAttribute('aria-labelledby', tabA.id);
    expect(tabA).toHaveAttribute('aria-controls', panel.id);
  });

  it('只有当前 tab 在 Tab 序列里，其余用方向键移动', () => {
    render(<Demo />);
    const tabA = screen.getByRole('tab', { name: /第一步/ });
    const tabB = screen.getByRole('tab', { name: /第二步/ });
    expect(tabA).toHaveAttribute('tabindex', '0');
    expect(tabB).toHaveAttribute('tabindex', '-1');
  });

  it('方向键切换选中项并循环回到第一个', () => {
    const onChange = vi.fn();
    render(<Demo onChange={onChange} />);
    const tabA = screen.getByRole('tab', { name: /第一步/ });
    const tabC = screen.getByRole('tab', { name: /第三步/ });

    tabA.focus();
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowRight' });
    expect(onChange).toHaveBeenLastCalledWith('b');

    tabC.focus();
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowRight' });
    expect(onChange).toHaveBeenLastCalledWith('a');

    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'End' });
    expect(onChange).toHaveBeenLastCalledWith('c');
  });

  it('未选中的面板不渲染', () => {
    render(<Demo />);
    expect(screen.queryByText('面板 B')).not.toBeInTheDocument();
  });
});
