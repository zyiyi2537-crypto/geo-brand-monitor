// 通用 SVG 图表 — 纯 SVG, 0 依赖, 暗色/亮色 theme 通过 currentColor + CSS var 自适应。

import { useState } from 'react';

export interface DonutSlice {
  label: string;
  value: number;
  color: string;
}

export function DonutChart({ slices, size = 180, hole = 0.6, centerText, centerSub }: {
  slices: DonutSlice[];
  size?: number;
  hole?: number;
  centerText?: string;
  centerSub?: string;
}) {
  // 鼠标移入分段:灰色提示「因子名 数量 个 · 占比%」
  const [hover, setHover] = useState<{ label: string; value: number; pct: number; x: number; y: number } | null>(null);
  const total = slices.reduce((s, x) => s + x.value, 0);
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 2;
  const innerR = r * hole;
  if (total <= 0) {
    return (
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full" style={{ maxWidth: size }}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--border-color)" strokeWidth="1" />
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle" fontSize="11" fill="var(--text-muted)">暂无数据</text>
      </svg>
    );
  }
  let acc = 0;
  const arcs = slices.map((sl, i) => {
    const startAngle = (acc / total) * Math.PI * 2 - Math.PI / 2;
    acc += sl.value;
    const endAngle = (acc / total) * Math.PI * 2 - Math.PI / 2;
    const large = endAngle - startAngle > Math.PI ? 1 : 0;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const xi1 = cx + innerR * Math.cos(endAngle);
    const yi1 = cy + innerR * Math.sin(endAngle);
    const xi2 = cx + innerR * Math.cos(startAngle);
    const yi2 = cy + innerR * Math.sin(startAngle);
    const d = [
      `M ${x1} ${y1}`,
      `A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`,
      `L ${xi1} ${yi1}`,
      `A ${innerR} ${innerR} 0 ${large} 0 ${xi2} ${yi2}`,
      'Z',
    ].join(' ');
    const pct = total ? (sl.value / total) * 100 : 0;
    const dim = hover && hover.label !== sl.label;
    return (
      <path
        key={i} d={d} fill={sl.color}
        style={{ opacity: dim ? 0.4 : 1, transition: 'opacity .12s', cursor: 'default' }}
        onMouseMove={(e) => setHover({ label: sl.label, value: sl.value, pct, x: e.clientX, y: e.clientY })}
        onMouseLeave={() => setHover(null)}
      />
    );
  });
  return (
    <div className="relative w-full" style={{ maxWidth: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full">
        {arcs}
        {centerText && (
          <text x={cx} y={cy - (centerSub ? 7 : 0)} textAnchor="middle" dominantBaseline="middle"
            fontSize="22" fontWeight="600" fill="var(--text-primary)">
            {centerText}
          </text>
        )}
        {centerSub && (
          <text x={cx} y={cy + 14} textAnchor="middle" dominantBaseline="middle"
            fontSize="10" fill="var(--text-muted)">
            {centerSub}
          </text>
        )}
      </svg>
      {hover && (
        <div
          className="fixed z-50 pointer-events-none px-2 py-1 rounded text-[11px] whitespace-nowrap shadow-lg"
          style={{ left: hover.x + 12, top: hover.y + 12, background: 'rgba(31,41,55,0.94)', color: '#fff' }}
        >
          {hover.label} {hover.value.toLocaleString()} 个 · {hover.pct.toFixed(1)}%
        </div>
      )}
    </div>
  );
}

export function DonutLegend({ slices, total }: { slices: DonutSlice[]; total?: number }) {
  const t = total ?? slices.reduce((s, x) => s + x.value, 0);
  return (
    <ul className="space-y-1.5 text-xs">
      {slices.map((s, i) => {
        const pct = t > 0 ? (s.value / t * 100) : 0;
        return (
          <li key={i} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: s.color }} />
            <span className="flex-1 truncate text-secondary">{s.label}</span>
            <span className="tabular-nums text-primary">{s.value.toLocaleString()}</span>
            <span className="tabular-nums text-muted w-12 text-right">{pct.toFixed(1)}%</span>
          </li>
        );
      })}
    </ul>
  );
}

export interface BarItem {
  label: string;
  value: number;
  color?: string;
}

// 横向条形图(用于 Top N 域名/查询/竞品)
export function HorizontalBarChart({ items, formatValue, max }: {
  items: BarItem[];
  formatValue?: (v: number) => string;
  max?: number;
}) {
  const upper = max ?? Math.max(1, ...items.map(i => i.value));
  return (
    <ul className="space-y-2 text-xs">
      {items.map((it, idx) => {
        const pct = (it.value / upper) * 100;
        return (
          <li key={idx} className="flex items-center gap-3">
            <span className="w-36 truncate text-primary flex-shrink-0">{it.label}</span>
            <div className="flex-1 h-5 rounded relative overflow-hidden" style={{ background: 'var(--bg-input)' }}>
              <div className="h-full rounded transition-all"
                style={{ width: `${pct}%`, background: it.color || 'var(--accent-primary)' }} />
            </div>
            <span className="tabular-nums text-muted w-14 text-right flex-shrink-0">
              {formatValue ? formatValue(it.value) : it.value.toLocaleString()}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// 纵向条形图 — 用 HTML/CSS 不用 SVG,避免 preserveAspectRatio=none 把字横向拉扁
export function VerticalBarChart({ items, height = 220, formatValue }: {
  items: BarItem[];
  height?: number;
  formatValue?: (v: number) => string;
}) {
  const max = Math.max(1, ...items.map(i => i.value));
  if (items.length === 0) return <div className="text-xs text-muted text-center py-6">暂无数据</div>;
  return (
    <div className="w-full" style={{ height }}>
      <div className="flex items-end gap-3 h-full px-2">
        {items.map((it, idx) => {
          const pct = (it.value / max) * 100;
          return (
            <div key={idx} className="flex-1 min-w-0 flex flex-col items-center justify-end gap-1.5 h-full">
              <span className="text-xs tabular-nums text-secondary whitespace-nowrap">
                {formatValue ? formatValue(it.value) : it.value.toLocaleString()}
              </span>
              <div
                className="w-full rounded-t transition-all"
                style={{
                  height: `${pct}%`,
                  minHeight: it.value > 0 ? 4 : 0,
                  background: it.color || 'var(--accent-primary)',
                }}
              />
              <span className="text-[11px] text-muted text-center truncate w-full" title={it.label}>
                {it.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// 模块标题旁的 ? 提示 — hover 显示 tooltip
export function InfoHint({ text }: { text: string }) {
  return (
    <span className="relative inline-flex group" tabIndex={0}>
      <span
        className="w-3.5 h-3.5 rounded-full text-[10px] flex items-center justify-center cursor-help"
        style={{ background: 'var(--bg-input)', color: 'var(--text-muted)', border: '1px solid var(--border-color)' }}
        aria-label={text}
      >
        ?
      </span>
      <span
        className="invisible group-hover:visible group-focus-within:visible absolute left-1/2 -translate-x-1/2 top-full mt-1.5 z-50 w-64 p-2 text-[11px] rounded shadow-lg"
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          color: 'var(--text-secondary)',
          pointerEvents: 'none',
          whiteSpace: 'pre-line',
        }}
      >
        {text}
      </span>
    </span>
  );
}

// 接口请求加载态 — 居中旋转 spinner + 文案。各页统一用这个,别再裸写 {L.loading}。
export function LoadingBlock({ label, className }: { label: string; className?: string }) {
  return (
    <div className={`flex flex-col items-center justify-center gap-2 py-10 text-muted ${className ?? ''}`}>
      <svg className="animate-spin w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
        style={{ color: 'var(--accent-primary)' }}>
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span className="text-xs">{label}</span>
    </div>
  );
}

// 默认配色 — 暖冷对照,适合 5-10 个分类
export const CHART_PALETTE = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1',
];
