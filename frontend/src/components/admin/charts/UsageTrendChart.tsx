import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { formatNumber } from '../adminFormat';

export interface UsageTrendPoint {
  date?: string;
  tokens?: number;
  calls?: number;
}

const HEIGHT = 240;
const PAD = { top: 16, right: 44, bottom: 24, left: 52 };
const GRID_STEPS = 4;

/** 把最大值向上取整到 1/2/5×10ⁿ，让刻度落在好读的数字上 */
function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

function tickLabel(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k`;
  return String(Math.round(value));
}

/**
 * Token / 调用次数双轴趋势图。
 *
 * 为什么手写 SVG 而不是用 recharts：recharts 3.8 的 es6 深路径引入实测只能省 1.8% gzip
 * （348.4→348.3 kB，104.4→102.6 kB），因为它所有图表共享同一套 core；而全站只有这一个图表，
 * 直接移除依赖可以把这块 348 kB 从后台路由里彻底去掉。交互只保留 hover 读数，
 * 关键数字仍然在下方 dl 里以文本复述，图形不是唯一信息载体。
 */
export const UsageTrendChart: React.FC<{ data: UsageTrendPoint[] }> = ({ data }) => {
  const points = useMemo(
    () =>
      data.map((item) => ({
        date: String(item.date ?? ''),
        tokens: Number(item.tokens ?? 0),
        calls: Number(item.calls ?? 0),
      })),
    [data]
  );

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(640);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  useEffect(() => {
    const node = containerRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width ?? 0;
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const scale = useMemo(() => {
    const innerWidth = Math.max(width - PAD.left - PAD.right, 1);
    const innerHeight = HEIGHT - PAD.top - PAD.bottom;
    const tokenMax = niceCeil(Math.max(...points.map((item) => item.tokens), 0));
    const callMax = niceCeil(Math.max(...points.map((item) => item.calls), 0));
    const x = (index: number) =>
      points.length <= 1 ? PAD.left + innerWidth / 2 : PAD.left + (innerWidth * index) / (points.length - 1);
    const yToken = (value: number) => PAD.top + innerHeight - (innerHeight * value) / tokenMax;
    const yCall = (value: number) => PAD.top + innerHeight - (innerHeight * value) / callMax;
    return { innerWidth, innerHeight, tokenMax, callMax, x, yToken, yCall };
  }, [points, width]);

  const handleMove = useCallback(
    (event: React.MouseEvent<SVGSVGElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const offset = event.clientX - rect.left - PAD.left;
      const step = scale.innerWidth / Math.max(points.length - 1, 1);
      const index = Math.round(offset / step);
      setHoverIndex(Math.min(Math.max(index, 0), points.length - 1));
    },
    [points.length, scale.innerWidth]
  );

  if (points.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
        还没有用量数据。等有对话流量后，这里会显示每天的趋势。
      </p>
    );
  }

  const peakTokens = points.reduce((best, item) => (item.tokens > best.tokens ? item : best), points[0]);
  const peakCalls = points.reduce((best, item) => (item.calls > best.calls ? item : best), points[0]);
  const totalTokens = points.reduce((sum, item) => sum + item.tokens, 0);
  const totalCalls = points.reduce((sum, item) => sum + item.calls, 0);
  const averageTokens = Math.round(totalTokens / points.length);
  const ariaLabel =
    `用量趋势，共 ${points.length} 天。Token 最高 ${formatNumber(peakTokens.tokens)}（${peakTokens.date}），` +
    `调用次数最多 ${formatNumber(peakCalls.calls)} 次（${peakCalls.date}），日均 ${formatNumber(averageTokens)} Token。`;

  const tokenPath = points
    .map((item, index) => `${index === 0 ? 'M' : 'L'}${scale.x(index).toFixed(1)},${scale.yToken(item.tokens).toFixed(1)}`)
    .join(' ');
  const callPath = points
    .map((item, index) => `${index === 0 ? 'M' : 'L'}${scale.x(index).toFixed(1)},${scale.yCall(item.calls).toFixed(1)}`)
    .join(' ');

  // X 轴日期按可用宽度抽稀，避免标签互相压叠
  const labelStep = Math.max(1, Math.ceil(points.length / Math.max(3, Math.floor(scale.innerWidth / 72))));
  const hovered = hoverIndex === null ? null : points[hoverIndex];
  const hoverX = hoverIndex === null ? 0 : scale.x(hoverIndex);
  const tooltipWidth = 132;
  const tooltipX = Math.min(Math.max(hoverX - tooltipWidth / 2, PAD.left), width - PAD.right - tooltipWidth);

  return (
    <div className="flex flex-col gap-4">
      <div ref={containerRef} className="relative w-full" role="img" aria-label={ariaLabel}>
        <svg
          width="100%"
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          aria-hidden="true"
          onMouseMove={handleMove}
          onMouseLeave={() => setHoverIndex(null)}
          className="block text-muted-foreground"
        >
          {Array.from({ length: GRID_STEPS + 1 }, (_, step) => {
            const ratio = step / GRID_STEPS;
            const y = PAD.top + scale.innerHeight * ratio;
            const tokenTick = scale.tokenMax * (1 - ratio);
            const callTick = scale.callMax * (1 - ratio);
            return (
              <g key={step}>
                <line
                  x1={PAD.left}
                  x2={width - PAD.right}
                  y1={y}
                  y2={y}
                  stroke="var(--color-border)"
                  strokeDasharray={step === GRID_STEPS ? undefined : '3 3'}
                />
                <text x={PAD.left - 8} y={y + 3} textAnchor="end" fontSize={10} fill="currentColor">
                  {tickLabel(tokenTick)}
                </text>
                <text x={width - PAD.right + 8} y={y + 3} textAnchor="start" fontSize={10} fill="currentColor">
                  {tickLabel(callTick)}
                </text>
              </g>
            );
          })}

          {points.map((item, index) =>
            index % labelStep === 0 || index === points.length - 1 ? (
              <text
                key={`x-${item.date}-${index}`}
                x={scale.x(index)}
                y={HEIGHT - 6}
                textAnchor="middle"
                fontSize={10}
                fill="currentColor"
              >
                {item.date.slice(5) || item.date}
              </text>
            ) : null
          )}

          <path d={tokenPath} fill="none" stroke="var(--color-primary)" strokeWidth={2} strokeLinecap="round" />
          <path
            d={callPath}
            fill="none"
            stroke="var(--color-success)"
            strokeWidth={2}
            strokeDasharray="4 3"
            strokeLinecap="round"
          />

          {hovered ? (
            <g>
              <line
                x1={hoverX}
                x2={hoverX}
                y1={PAD.top}
                y2={PAD.top + scale.innerHeight}
                stroke="var(--color-muted-foreground)"
                strokeDasharray="2 2"
              />
              <circle cx={hoverX} cy={scale.yToken(hovered.tokens)} r={3} fill="var(--color-primary)" />
              <circle cx={hoverX} cy={scale.yCall(hovered.calls)} r={3} fill="var(--color-success)" />
              <rect
                x={tooltipX}
                y={PAD.top}
                width={tooltipWidth}
                height={46}
                rx={6}
                fill="var(--color-card)"
                stroke="var(--color-border)"
              />
              <text x={tooltipX + 8} y={PAD.top + 15} fontSize={10} fill="var(--color-foreground)">
                {hovered.date}
              </text>
              <text x={tooltipX + 8} y={PAD.top + 29} fontSize={10} fill="var(--color-primary)">
                Token {formatNumber(hovered.tokens)}
              </text>
              <text x={tooltipX + 8} y={PAD.top + 41} fontSize={10} fill="var(--color-success)">
                调用 {formatNumber(hovered.calls)} 次
              </text>
            </g>
          ) : null}
        </svg>
        <div className="mt-1 flex items-center gap-4 text-2xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 rounded-full bg-primary" aria-hidden="true" />
            Token
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 rounded-full bg-success" aria-hidden="true" />
            调用次数（右轴）
          </span>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { label: 'Token 峰值', value: formatNumber(peakTokens.tokens), hint: peakTokens.date },
          { label: '调用峰值', value: `${formatNumber(peakCalls.calls)} 次`, hint: peakCalls.date },
          { label: '日均 Token', value: formatNumber(averageTokens), hint: `覆盖 ${points.length} 天` },
          { label: '区间合计', value: formatNumber(totalTokens), hint: `Token，另 ${formatNumber(totalCalls)} 次调用` },
        ].map((item) => (
          <div key={item.label} className="rounded-lg border border-border bg-card px-3 py-2">
            <dt className="text-2xs text-muted-foreground">{item.label}</dt>
            <dd className="mt-0.5 font-mono text-sm tabular-nums text-foreground">{item.value}</dd>
            <dd className="text-2xs text-muted-foreground">{item.hint}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
};
