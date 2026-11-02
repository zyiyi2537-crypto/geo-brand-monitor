import { useMemo, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';

import type { KeywordGroup, KeywordKind } from '../../../../types/sentiment';

interface Props {
  value: KeywordGroup[];
  onChange: (next: KeywordGroup[]) => void;
}

const KIND_OPTIONS: { kind: KeywordKind; emoji: string }[] = [
  { kind: 'entity',     emoji: '🏢' },
  { kind: 'legal',      emoji: '⚖️' },
  { kind: 'exec',       emoji: '👤' },
  { kind: 'project',    emoji: '🚀' },
  { kind: 'competitor', emoji: '⚔️' },
  { kind: 'custom',     emoji: '📌' },
];

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

export function KeywordGroupsEditor({ value, onChange }: Props) {
  const { t } = useTranslation();
  const [activeIdx, setActiveIdx] = useState(0);
  const [draft, setDraft] = useState('');

  const safeIdx = Math.min(activeIdx, Math.max(0, value.length - 1));
  const activeGroup = value[safeIdx];

  const totalEnabled = useMemo(() => {
    let n = 0;
    for (const g of value) {
      for (const it of g.items) if (it.enabled !== false) n += 1;
    }
    return n;
  }, [value]);

  const update = (idx: number, mut: (g: KeywordGroup) => KeywordGroup) => {
    onChange(value.map((g, i) => (i === idx ? mut(g) : g)));
  };

  const addGroup = () => {
    const name = prompt(t('dashboard.sentiment.keywordGroups.newGroupPrompt'));
    if (!name?.trim()) return;
    onChange([
      ...value,
      { name: name.trim(), kind: 'custom', items: [] },
    ]);
    setActiveIdx(value.length);
  };

  const removeGroup = (idx: number) => {
    if (!confirm(t('dashboard.sentiment.keywordGroups.removeGroupConfirm', { name: value[idx]?.name ?? '' }))) return;
    onChange(value.filter((_, i) => i !== idx));
    setActiveIdx(Math.max(0, idx - 1));
  };

  const renameGroup = (idx: number) => {
    const cur = value[idx];
    if (!cur) return;
    const next = prompt(t('dashboard.sentiment.keywordGroups.renamePrompt'), cur.name);
    if (!next?.trim()) return;
    update(idx, (g) => ({ ...g, name: next.trim() }));
  };

  const setKind = (idx: number, kind: KeywordKind) => {
    update(idx, (g) => ({ ...g, kind }));
  };

  const addItem = () => {
    const term = draft.trim().replace(/,$/, '');
    if (!term || !activeGroup) return;
    if (activeGroup.items.some((it) => it.term === term)) {
      setDraft('');
      return;
    }
    update(safeIdx, (g) => ({ ...g, items: [...g.items, { term, is_new: true }] }));
    setDraft('');
  };

  const removeItem = (j: number) => {
    update(safeIdx, (g) => ({ ...g, items: g.items.filter((_, idx) => idx !== j) }));
  };

  const toggleEnabled = (j: number) => {
    update(safeIdx, (g) => ({
      ...g,
      items: g.items.map((it, idx) =>
        idx === j ? { ...it, enabled: it.enabled === false ? true : false } : it,
      ),
    }));
  };

  const clearIsNew = (j: number) => {
    update(safeIdx, (g) => ({
      ...g,
      items: g.items.map((it, idx) => (idx === j ? { ...it, is_new: false } : it)),
    }));
  };

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addItem();
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)] gap-3 rounded-xl p-3" style={cardStyle}>
      {/* 左:分组列表 */}
      <aside className="space-y-1.5">
        <header className="flex items-center justify-between px-1 mb-1">
          <span className="text-xs font-semibold text-secondary uppercase tracking-wider">
            {t('dashboard.sentiment.keywordGroups.groupsHeader', { count: totalEnabled })}
          </span>
          <button type="button" onClick={addGroup}
            className="text-xs" style={{ color: 'var(--accent-primary)' }}>
            + {t('dashboard.sentiment.keywordGroups.addGroup')}
          </button>
        </header>
        {value.length === 0 ? (
          <p className="text-xs text-muted px-2 py-3 text-center">
            {t('dashboard.sentiment.keywordGroups.empty')}
          </p>
        ) : (
          <ul className="space-y-0.5">
            {value.map((g, i) => {
              const isActive = i === safeIdx;
              const enabled = g.items.filter((it) => it.enabled !== false).length;
              return (
                <li key={`${g.name}-${i}`}>
                  <button type="button" onClick={() => setActiveIdx(i)}
                    className="w-full text-left px-2 py-1.5 rounded text-sm transition-colors"
                    style={{
                      background: isActive ? 'var(--bg-tertiary)' : 'transparent',
                      color: isActive ? 'var(--accent-primary)' : 'var(--text-primary)',
                      border: '1px solid transparent',
                    }}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate">
                        {kindEmoji(g.kind)} {g.name}
                      </span>
                      <span className="text-[10px] text-muted">{enabled}/{g.items.length}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </aside>

      {/* 右:当前分组 items */}
      <section className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
        {!activeGroup ? (
          <p className="text-sm text-muted py-12 text-center">
            {t('dashboard.sentiment.keywordGroups.selectOrAdd')}
          </p>
        ) : (
          <>
            <header className="flex items-center justify-between flex-wrap gap-2 mb-2">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-primary">
                  {kindEmoji(activeGroup.kind)} {activeGroup.name}
                </h3>
                <button type="button" onClick={() => renameGroup(safeIdx)}
                  className="text-xs text-muted hover:text-primary">
                  ✏️ {t('dashboard.sentiment.keywordGroups.rename')}
                </button>
              </div>
              <div className="flex items-center gap-2">
                <select value={activeGroup.kind}
                  onChange={(e) => setKind(safeIdx, e.target.value as KeywordKind)}
                  className="text-xs rounded px-2 py-1"
                  style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
                  {KIND_OPTIONS.map((k) => (
                    <option key={k.kind} value={k.kind}>
                      {k.emoji} {t(`dashboard.sentiment.keywordGroups.kinds.${k.kind}`)}
                    </option>
                  ))}
                </select>
                <button type="button" onClick={() => removeGroup(safeIdx)}
                  className="text-xs" style={{ color: '#dc2626' }}>
                  🗑 {t('dashboard.sentiment.keywordGroups.removeGroup')}
                </button>
              </div>
            </header>

            {/* 添加输入 */}
            <div className="flex items-center gap-2 mb-2">
              <input type="text" value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKey}
                placeholder={t('dashboard.sentiment.keywordGroups.addItemPlaceholder')}
                className="flex-1 px-2 py-1.5 rounded text-sm"
                style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
              <button type="button" onClick={addItem}
                className="rounded-md px-3 py-1.5 text-xs font-semibold btn-solid">
                + {t('dashboard.sentiment.keywordGroups.addItem')}
              </button>
            </div>

            {/* items 列表 */}
            {activeGroup.items.length === 0 ? (
              <p className="text-xs text-muted py-6 text-center">
                {t('dashboard.sentiment.keywordGroups.noItems')}
              </p>
            ) : (
              <ul className="space-y-1 max-h-[420px] overflow-auto pr-1">
                {activeGroup.items.map((it, j) => (
                  <li key={`${it.term}-${j}`}
                    className="flex items-center gap-2 px-2 py-1.5 rounded"
                    style={{
                      background: it.is_new ? 'rgba(251, 191, 36, 0.15)' : 'transparent',
                      border: '1px solid var(--border-color)',
                      opacity: it.enabled === false ? 0.5 : 1,
                    }}>
                    <input type="checkbox"
                      checked={it.enabled !== false}
                      onChange={() => toggleEnabled(j)}
                      title={t('dashboard.sentiment.keywordGroups.enabledHint')} />
                    <span className="flex-1 text-sm font-mono truncate" style={{ color: 'var(--text-primary)' }}>
                      {it.term}
                    </span>
                    {it.is_new && (
                      <button type="button" onClick={() => clearIsNew(j)}
                        className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                        style={{ background: '#fbbf24', color: '#78350f' }}
                        title={t('dashboard.sentiment.keywordGroups.clearNew')}>
                        NEW
                      </button>
                    )}
                    <button type="button" onClick={() => removeItem(j)}
                      className="text-xs text-muted hover:text-primary"
                      title={t('dashboard.sentiment.keywordGroups.remove')}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function kindEmoji(kind: KeywordKind): string {
  const found = KIND_OPTIONS.find((o) => o.kind === kind);
  return found?.emoji ?? '📌';
}
