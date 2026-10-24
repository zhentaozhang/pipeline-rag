import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { UsageTrendChart } from './UsageTrendChart';

const DATA = [
  { date: '2026-01-01', tokens: 1200, calls: 12 },
  { date: '2026-01-02', tokens: 4800, calls: 40 },
  { date: '2026-01-03', tokens: 2400, calls: 21 },
];

describe('UsageTrendChart', () => {
  it('把趋势摘要写进 role="img" 的无障碍标签', () => {
    render(<UsageTrendChart data={DATA} />);
    const figure = screen.getByRole('img');
    expect(figure.getAttribute('aria-label')).toContain('用量趋势，共 3 天');
    expect(figure.getAttribute('aria-label')).toContain('Token 最高 4,800');
  });

  it('关键数字以文本形式重复一次，不只靠图形传达', () => {
    render(<UsageTrendChart data={DATA} />);
    expect(screen.getByText('Token 峰值')).toBeInTheDocument();
    expect(screen.getByText('调用峰值')).toBeInTheDocument();
    expect(screen.getByText('2,800')).toBeInTheDocument();
  });

  it('没有数据时给出下一步引导', () => {
    render(<UsageTrendChart data={[]} />);
    expect(screen.getByText(/还没有用量数据/)).toBeInTheDocument();
    expect(screen.queryByRole('img')).toBeNull();
  });
});
