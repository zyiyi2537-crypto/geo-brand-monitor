// 监测任务侧栏 — 对齐 WisersOne 原型(3 级展开树).
//
// 层级:
//   监测
//   └─ 世纪互联 (=account.target, 始终展开 — 单账户也显示)
//      ├─ 公司主体 (=keyword_group.name, 可折叠)
//      │   ├─ 世纪互联 (=term, 点击 → ?q=世纪互联 过滤文章)
//      │   └─ 21Vianet
//      ├─ 法院诉讼
//      └─ ...
//
// 点击行为:
//   - 账户头:select 账户,清空 ?q
//   - keyword_group:toggle expand,select 账户
//   - term:select 账户 + 设 ?q=&lt;term&gt; (ArticlesTab 读它当 topic 过滤)
//
// 折叠状态用 localStorage 持久化(per-account-per-group).
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { SentimentAccount, KeywordKind } from '../../../../types/sentiment';

interface Props {
  accounts: SentimentAccount[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  /** 当前视图 — 'newsnow' 时账户选中态隐藏,工具组高亮 */
  view?: 'account' | 'newsnow';
  /** 点击"实时热榜"工具项 */
  onSelectNewsnow?: () => void;
}

const COLLAPSED_KEY = 'sentiment.sidebar.collapsedNodes';

// 节点 id 编码:`acct-{id}` / `grp-{accountId}-{groupIndex}`
function nodeId(...parts: (string | number)[]): string {
  return parts.join('-');
}

export function AccountSidebar({
  accounts, selectedId, onSelect,
  view = 'account', onSelectNewsnow,
}: Props) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const activeQ = params.get('q') ?? '';

  // 按 target group accounts(多账户时折叠到品牌 header 下)
  const groups = useMemo(() => {
    const m = new Map<string, SentimentAccount[]>();
    for (const a of accounts) {
      const key = a.target || '—';
      const arr = m.get(key) ?? [];
      arr.push(a);
      m.set(key, arr);
    }
    return Array.from(m.entries());
  }, [accounts]);

  // 折叠状态:存「折叠的节点 id」集合(默认全部展开)
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(COLLAPSED_KEY);
      return new Set<string>(raw ? JSON.parse(raw) : []);
    } catch {
      return new Set();
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, JSON.stringify(Array.from(collapsed)));
    } catch { /* quota 满,忽略 */ }
  }, [collapsed]);

  const toggleNode = (id: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const setQuery = (q: string) => {
    const next = new URLSearchParams(params);
    if (q) next.set('q', q);
    else next.delete('q');
    next.set('tab', 'articles');
    // 关键:从「实时热榜」切回账户视图。否则 view=newsnow 在 Sentiment.tsx
    // 强制渲 HotTopicsPanel,点 keyword 看不到任何反应。
    next.delete('view');
    setParams(next, { replace: false });
  };

  const handleSelectAccount = (id: number) => {
    onSelect(id);
    setQuery('');
  };

  const handleSelectTerm = (id: number, term: string) => {
    onSelect(id);
    setQuery(term);
  };

  // view==='newsnow' 时账户行不显示选中态(但内部 selectedId 仍保留,切回 'account' 视图能恢复)
  const effectiveSelectedId = view === 'account' ? selectedId : null;

  if (!accounts.length) {
    return (
      <aside className="rounded-xl p-4 text-xs text-muted" style={cardStyle}>
        {t('dashboard.sentiment.sidebar.empty')}
      </aside>
    );
  }

  return (
    <aside className="rounded-xl py-3 self-start" style={cardStyle}>
      <header className="px-4 pb-2 mb-1 flex items-center justify-between"
        style={{ borderBottom: '1px solid var(--border-color)' }}>
        <span className="text-xs font-semibold text-secondary uppercase tracking-wider">
          {t('dashboard.sentiment.sidebar.title')}
        </span>
      </header>

      <nav className="px-2 space-y-0.5">
        {groups.map(([target, items]) => {
          // 多账户共享 target:渲染品牌 group header + 折叠
          const showBrandHeader = items.length > 1;
          const brandNodeId = nodeId('brand', target);
          const brandCollapsed = showBrandHeader && collapsed.has(brandNodeId);

          if (showBrandHeader) {
            return (
              <div key={target}>
                <TreeRow
                  level={0}
                  expandable
                  expanded={!brandCollapsed}
                  selected={items.some(a => a.id === effectiveSelectedId)}
                  onToggle={() => toggleNode(brandNodeId)}
                  onClick={() => toggleNode(brandNodeId)}
                  label={target}
                  bold
                />
                {!brandCollapsed && items.map(a => (
                  <AccountNode key={a.id}
                    account={a}
                    level={1}
                    selectedId={effectiveSelectedId}
                    activeQ={activeQ}
                    collapsed={collapsed}
                    onToggleNode={toggleNode}
                    onSelectAccount={handleSelectAccount}
                    onSelectTerm={handleSelectTerm}
                    t={t}
                  />
                ))}
              </div>
            );
          }
          // 单账户:不显示 brand header,直接渲 AccountNode
          const a = items[0];
          return (
            <AccountNode key={a.id}
              account={a}
              level={0}
              selectedId={effectiveSelectedId}
              activeQ={activeQ}
              collapsed={collapsed}
              onToggleNode={toggleNode}
              onSelectAccount={handleSelectAccount}
              onSelectTerm={handleSelectTerm}
              t={t}
            />
          );
        })}
      </nav>

      <footer className="px-3 pt-2 mt-2" style={{ borderTop: '1px solid var(--border-color)' }}>
        <Link
          to="/account/brand"
          className="block w-full text-xs px-2 py-1.5 rounded text-center hover:brightness-110"
          style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)' }}
        >
          {t('dashboard.sentiment.sidebar.newTask')}
        </Link>
      </footer>

      {/* 工具组 — 与账户监测解耦的辅助功能(实时热榜等)*/}
      <div className="px-2 pt-3 mt-2" style={{ borderTop: '1px solid var(--border-color)' }}>
        <div className="px-2 mb-1.5 text-[10px] font-semibold text-secondary uppercase tracking-wider">
          {t('dashboard.sentiment.sidebar.tools')}
        </div>
        <TreeRow
          level={0}
          selected={view === 'newsnow'}
          onClick={() => onSelectNewsnow?.()}
          label={t('dashboard.sentiment.sidebar.newsnow')}
          bold
        />
      </div>
    </aside>
  );
}

/** 单账户节点:渲染账户名 + 嵌套 keyword_groups + terms */
function AccountNode({
  account, level, selectedId, activeQ, collapsed,
  onToggleNode, onSelectAccount, onSelectTerm, t,
}: {
  account: SentimentAccount;
  level: number;
  selectedId: number | null;
  activeQ: string;
  collapsed: Set<string>;
  onToggleNode: (id: string) => void;
  onSelectAccount: (id: number) => void;
  onSelectTerm: (id: number, term: string) => void;
  t: (k: string) => string;
}) {
  const acctNodeId = nodeId('acct', account.id);
  const isOpen = !collapsed.has(acctNodeId);
  const isSelected = account.id === selectedId;
  const groups = account.keyword_groups ?? [];
  const label = account.ticker
    ? `${account.target} · ${account.ticker}`
    : account.target;

  return (
    <div>
      <TreeRow
        level={level}
        expandable={groups.length > 0}
        expanded={isOpen}
        selected={isSelected && !activeQ}
        onToggle={() => onToggleNode(acctNodeId)}
        onClick={() => onSelectAccount(account.id)}
        label={label}
        bold
      />
      {isOpen && groups.length === 0 && (
        <div className="px-3 py-1 text-[11px] text-muted"
          style={{ marginLeft: (level + 1) * 12 }}>
          {t('dashboard.sentiment.sidebar.noKeywords')}
        </div>
      )}
      {isOpen && groups.map((g, gi) => (
        <KeywordGroupNode key={`${account.id}-${gi}`}
          accountId={account.id}
          groupIndex={gi}
          name={g.name || t(`dashboard.sentiment.sidebar.kinds.${g.kind as KeywordKind}`)}
          terms={(g.items ?? []).filter(it => it.enabled !== false).map(it => it.term)}
          level={level + 1}
          activeQ={activeQ}
          isAccountSelected={isSelected}
          collapsed={collapsed}
          onToggleNode={onToggleNode}
          onSelectTerm={(term) => onSelectTerm(account.id, term)}
        />
      ))}
    </div>
  );
}

/** keyword_group 节点:折叠 header + terms list */
function KeywordGroupNode({
  accountId, groupIndex, name, terms, level,
  activeQ, isAccountSelected, collapsed,
  onToggleNode, onSelectTerm,
}: {
  accountId: number;
  groupIndex: number;
  name: string;
  terms: string[];
  level: number;
  activeQ: string;
  isAccountSelected: boolean;
  collapsed: Set<string>;
  onToggleNode: (id: string) => void;
  onSelectTerm: (term: string) => void;
}) {
  const gNodeId = nodeId('grp', accountId, groupIndex);
  const isOpen = !collapsed.has(gNodeId);
  return (
    <>
      <TreeRow
        level={level}
        expandable={terms.length > 0}
        expanded={isOpen}
        selected={false}
        onToggle={() => onToggleNode(gNodeId)}
        onClick={() => onToggleNode(gNodeId)}
        label={`${name} (${terms.length})`}
      />
      {isOpen && terms.map(term => {
        const isActive = isAccountSelected && activeQ === term;
        return (
          <TreeRow
            key={`${gNodeId}-${term}`}
            level={level + 1}
            selected={isActive}
            onClick={() => onSelectTerm(term)}
            label={term}
          />
        );
      })}
    </>
  );
}

/** 通用树行 — 按 level 缩进,可选 ▸/▾ 展开标记 */
function TreeRow({
  level, expandable = false, expanded = false,
  selected, onToggle, onClick, label, bold,
}: {
  level: number;
  expandable?: boolean;
  expanded?: boolean;
  selected: boolean;
  onToggle?: () => void;
  onClick: () => void;
  label: string;
  bold?: boolean;
}) {
  return (
    <div className="flex items-center"
      style={{
        paddingLeft: level * 12,
        background: selected ? 'var(--bg-tertiary)' : 'transparent',
        borderLeft: selected ? '2px solid var(--accent-primary)' : '2px solid transparent',
      }}>
      {expandable && (
        <button type="button"
          onClick={(e) => { e.stopPropagation(); onToggle?.(); }}
          className="text-[10px] px-1 py-1 text-muted hover:text-primary"
          aria-label={expanded ? 'collapse' : 'expand'}>
          {expanded ? '▾' : '▸'}
        </button>
      )}
      {!expandable && <span style={{ width: 16 }} />}
      <button type="button" onClick={onClick}
        className="flex-1 px-1.5 py-1 text-left text-xs truncate transition-colors"
        style={{
          color: selected ? 'var(--accent-primary)' : 'var(--text-secondary)',
          fontWeight: bold ? 600 : selected ? 600 : 400,
        }}
        title={label}>
        {label}
      </button>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};
