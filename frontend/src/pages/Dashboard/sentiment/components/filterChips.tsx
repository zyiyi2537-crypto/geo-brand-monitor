// 文章筛选的 chip 原子组件 — ArticlesTab 顶部 chip 行和高级筛选 modal 共用.
//
// FilterChip: 4-5 项 enum(风险/情感)用的实色 chip
// GridChip:   单 chip,3 列 grid 排版,适合平台 code 这种带数量的
// ExpandableGridChip: 在 GridChip 上加 ▾,展开后内联渲染下属平台 list
import { useState } from 'react';

export function FilterChip({ label, active, onClick, dot }:
  { label: string; active: boolean; onClick: () => void; dot?: boolean }) {
  return (
    <button type="button" onClick={onClick}
      className="relative text-xs px-2 py-0.5 rounded transition-colors"
      style={{
        background: active ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
        color: active ? '#ffffff' : 'var(--text-secondary)',
        border: '1px solid transparent',
      }}>
      {label}
      {dot && (
        <span aria-label="有看空内容"
          style={{
            position: 'absolute', top: -3, right: -3,
            width: 8, height: 8, borderRadius: '50%',
            background: '#ef4444',
            border: '1px solid var(--bg-primary)',
          }} />
      )}
    </button>
  );
}

export function Section({ title, hint, children }:
  { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline gap-1.5 pb-1.5 mb-2"
        style={{ borderBottom: '1px solid var(--border-color)' }}>
        <span className="text-xs font-semibold text-primary">{title}</span>
        {hint && <span className="text-[11px] text-muted">({hint})</span>}
      </div>
      {children}
    </div>
  );
}

export function ChipGrid({ children, cols = 3 }:
  { children: React.ReactNode; cols?: 2 | 3 | 4 }) {
  const gridCls = cols === 2 ? 'grid-cols-2' : cols === 4 ? 'grid-cols-4' : 'grid-cols-3';
  return (
    <div className={`grid ${gridCls} gap-x-1 gap-y-0.5`}>
      {children}
    </div>
  );
}

const chipBase =
  "text-xs px-1.5 py-1 rounded transition-colors text-left flex items-center justify-between";

function activeChipStyle(active: boolean): React.CSSProperties {
  return {
    background: active ? 'rgba(99,102,241,0.12)' : 'transparent',
    color: active ? 'var(--accent-primary)' : 'var(--text-secondary)',
    fontWeight: active ? 600 : 400,
  };
}

export function GridChip({ label, count, active, onClick }:
  { label: string; count?: number; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={chipBase}
      style={activeChipStyle(active)} title={label}>
      <span className="truncate">{label}</span>
      {count !== undefined && (
        <span className="ml-1 text-[10px]"
          style={{ color: active ? 'var(--accent-primary)' : 'var(--text-muted)' }}>
          {count >= 1000 ? `${(count/1000).toFixed(1)}K` : count}
        </span>
      )}
    </button>
  );
}

export function ExpandableGridChip({
  label, count, active, onToggleSelf,
  codes, platformLabel, countOf, isSourceActive, onToggleSource,
}: {
  label: string;
  count: number;
  active: boolean;
  onToggleSelf: (() => void) | null;
  codes: string[];
  platformLabel: (code: string) => string;
  countOf: (code: string) => number;
  isSourceActive: (code: string) => boolean;
  onToggleSource: (code: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const hasChildren = codes.length > 0;
  return (
    <>
      <div className="flex items-center" style={activeChipStyle(active)}>
        <button type="button"
          onClick={() => onToggleSelf ? onToggleSelf() : setOpen(v => !v)}
          className="text-xs pl-1.5 py-1 truncate flex-1 text-left"
          style={{ color: 'inherit' }}
          title={label}>
          {label}
        </button>
        <span className="text-[10px] mr-1"
          style={{ color: active ? 'var(--accent-primary)' : 'var(--text-muted)' }}>
          {count >= 1000 ? `${(count/1000).toFixed(1)}K` : count}
        </span>
        {hasChildren && (
          <button type="button" onClick={() => setOpen(v => !v)}
            className="text-[10px] pr-1.5 py-1 hover:text-primary"
            style={{ color: 'var(--text-muted)' }}
            aria-label={open ? 'collapse' : 'expand'}>
            {open ? '▴' : '▾'}
          </button>
        )}
      </div>
      {open && hasChildren && (
        <div className="col-span-3 ml-2 mb-1 mt-0.5 grid grid-cols-3 gap-x-1 gap-y-0.5"
          style={{ paddingLeft: 6, borderLeft: '2px solid var(--border-color)' }}>
          {codes.map(c => (
            <GridChip key={c}
              label={platformLabel(c)}
              count={countOf(c)}
              active={isSourceActive(c)}
              onClick={() => onToggleSource(c)} />
          ))}
        </div>
      )}
    </>
  );
}

// toggleSet 改成各调用方各自维护一份 4 行的本地 toggle 帮手 — 见 ArticlesTab /
// AdvancedFilterModal.tsx.原本的导出会触发 react-refresh/only-export-components.
