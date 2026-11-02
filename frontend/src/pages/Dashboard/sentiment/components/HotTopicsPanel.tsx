// 实时热点面板 — 自托管 newsnow 多站热榜的"全网在聊什么"仪表盘。
//
// 设计:
//   - 多源卡片网格(对齐 newsnow.busiyi.world):每卡 = 一个源 Top N
//   - 每卡独立 React Query,失败 / 慢不互相影响
//   - 类别 chip 多选过滤,localStorage 持久化用户偏好
//   - 命中当前账户品牌词的条目高亮(🔥),帮用户在热榜里第一眼看到自家话题
//
// 与 account.newsnow_sources 互补:
//   - 后者:配在账号上,按 keywords 过滤入 posts 表 → 分析管线
//   - 本面板:全量裸热榜,不入库,纯展示
//
// 数据极薄(newsnow 接口天花板):title + url + 偶尔 hotness;无时间戳/正文/作者。
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { useNewsnowSources, useNewsnowHot } from '../../../../hooks/useSentiment';
import { timeAgo } from '../../../../mocks/sentiment';
import {
  flattenKeywordGroups,
  type NewsnowItem, type NewsnowSource, type SentimentAccount,
} from '../../../../types/sentiment';

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

const innerCardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

const STORAGE_KEY = 'sentiment.hotTopics.enabledCategories';
const DEFAULT_CATEGORIES = ['social', 'news', 'tech', 'finance'];

const CATEGORY_BADGE_STYLE: Record<string, React.CSSProperties> = {
  social: { background: 'rgba(236,72,153,0.12)', color: '#db2777' },
  news: { background: 'rgba(59,130,246,0.12)', color: '#2563eb' },
  tech: { background: 'rgba(168,85,247,0.12)', color: '#9333ea' },
  finance: { background: 'rgba(16,185,129,0.12)', color: '#059669' },
};

const FALLBACK_SOURCES: NewsnowSource[] = [
  { id: 'weibo', name_zh: '微博热搜', name_en: 'Weibo', category: 'social' },
  { id: 'zhihu', name_zh: '知乎热榜', name_en: 'Zhihu', category: 'social' },
  { id: 'douyin', name_zh: '抖音热榜', name_en: 'Douyin', category: 'social' },
  { id: 'hupu', name_zh: '虎扑步行街', name_en: 'Hupu', category: 'social' },
  { id: 'toutiao', name_zh: '今日头条', name_en: 'Toutiao', category: 'news' },
  { id: 'baidu', name_zh: '百度热搜', name_en: 'Baidu', category: 'news' },
  { id: 'thepaper', name_zh: '澎湃新闻', name_en: 'ThePaper', category: 'news' },
  { id: 'ithome', name_zh: 'IT 之家', name_en: 'IThome', category: 'tech' },
  { id: '36kr', name_zh: '36 氪', name_en: '36Kr', category: 'tech' },
  { id: 'huxiu', name_zh: '虎嗅', name_en: 'Huxiu', category: 'tech' },
  { id: 'wallstreetcn', name_zh: '华尔街见闻', name_en: 'WallstreetCN', category: 'finance' },
  { id: 'cls', name_zh: '财联社', name_en: 'CaiLianShe', category: 'finance' },
  { id: 'jin10', name_zh: '金十数据', name_en: 'Jin10', category: 'finance' },
];

interface Props {
  /** mock 模式下跳过真实拉取 */
  usingMock?: boolean;
  /** 单卡 Top N,默认 10 */
  limit?: number;
  /** 当前账户(可选)— 用于品牌词命中高亮 */
  account?: SentimentAccount | null;
}

export function HotTopicsPanel({ usingMock, limit = 10, account }: Props) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();

  const { data: sourcesResp } = useNewsnowSources();
  const allSources: NewsnowSource[] = sourcesResp?.items ?? FALLBACK_SOURCES;

  // 类别筛选(localStorage 持久化)
  const [enabledCategories, setEnabledCategories] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return new Set<string>(JSON.parse(raw));
    } catch { /* noop */ }
    return new Set(DEFAULT_CATEGORIES);
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(enabledCategories)));
    } catch { /* quota,忽略 */ }
  }, [enabledCategories]);

  const toggleCategory = (cat: string) => {
    setEnabledCategories(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      // 至少保留一个类别,否则视为"全选"避免空白页
      if (next.size === 0) return new Set(DEFAULT_CATEGORIES);
      return next;
    });
  };

  // 品牌词集合(target + aliases + keyword_groups + keywords)— 全部小写化
  const brandTerms = useMemo<string[]>(() => {
    if (!account) return [];
    const terms = new Set<string>();
    if (account.target) terms.add(account.target);
    for (const a of account.aliases ?? []) if (a) terms.add(a);
    if (account.keyword_groups?.length) {
      for (const k of flattenKeywordGroups(account.keyword_groups)) terms.add(k);
    } else {
      for (const k of account.keywords ?? []) if (k) terms.add(k);
    }
    return Array.from(terms).map(s => s.toLowerCase().trim()).filter(Boolean);
  }, [account]);

  const visibleSources = useMemo(
    () => allSources.filter(s => enabledCategories.has(s.category)),
    [allSources, enabledCategories],
  );

  const labelOf = (s: NewsnowSource): string =>
    i18n.language?.startsWith('en') ? s.name_en : s.name_zh;

  const refreshAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['sentiment', 'newsnow-hot'] });
  }, [qc]);

  return (
    <section className="rounded-xl p-5" style={cardStyle}>
      <header className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold text-primary">
            {t('dashboard.sentiment.today.hotTopics.title')}
          </h3>
          <p className="text-xs text-muted mt-0.5">
            {t('dashboard.sentiment.today.hotTopics.subtitle')}
          </p>
        </div>
        <button
          type="button"
          onClick={refreshAll}
          disabled={usingMock}
          className="text-xs font-semibold rounded-md px-3 py-1.5 disabled:opacity-50"
          style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
        >
          ↻ {t('dashboard.sentiment.today.hotTopics.refreshAll')}
        </button>
      </header>

      {/* 类别筛选 — 多选 chip */}
      <div className="flex items-center gap-1.5 flex-wrap mb-4">
        <span className="text-[10px] uppercase tracking-wider text-muted mr-1">
          {t('dashboard.sentiment.today.hotTopics.filterBy')}
        </span>
        {DEFAULT_CATEGORIES.map((cat) => {
          const active = enabledCategories.has(cat);
          const palette = CATEGORY_BADGE_STYLE[cat];
          return (
            <button
              key={cat}
              type="button"
              onClick={() => toggleCategory(cat)}
              className="text-xs px-2.5 py-1 rounded-full font-medium transition-colors"
              style={active
                ? palette
                : { background: 'var(--bg-tertiary)', color: 'var(--text-secondary)', opacity: 0.6 }}
            >
              {t(`dashboard.sentiment.today.hotTopics.categories.${cat}`, cat)}
            </button>
          );
        })}
        {brandTerms.length > 0 && (
          <span className="ml-auto text-[11px] text-muted">
            🔥 {t('dashboard.sentiment.today.hotTopics.brandHint', {
              count: brandTerms.length,
              brand: account?.target ?? '',
            })}
          </span>
        )}
      </div>

      {visibleSources.length === 0 ? (
        <p className="text-sm text-secondary py-10 text-center">
          {t('dashboard.sentiment.today.hotTopics.noCategory')}
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {visibleSources.map((s) => (
            <SourceCard
              key={s.id}
              source={s}
              label={labelOf(s)}
              limit={limit}
              usingMock={usingMock}
              brandTerms={brandTerms}
            />
          ))}
        </div>
      )}
    </section>
  );
}

// ─────────────────────────── SourceCard ───────────────────────────

function SourceCard({
  source, label, limit, usingMock, brandTerms,
}: {
  source: NewsnowSource;
  label: string;
  limit: number;
  usingMock?: boolean;
  brandTerms: string[];
}) {
  const { t } = useTranslation();
  const hot = useNewsnowHot(usingMock ? null : source.id, limit);
  const items = hot.data?.items ?? [];
  const fetchedAt = hot.data?.fetched_at;
  const palette = CATEGORY_BADGE_STYLE[source.category] ?? {};

  // 命中数量(用于卡头显示)
  const brandHits = useMemo(() => {
    if (!brandTerms.length || !items.length) return 0;
    return items.reduce((n, it) => (titleMatches(it.title, brandTerms) ? n + 1 : n), 0);
  }, [items, brandTerms]);

  return (
    <div
      className="rounded-lg p-3 flex flex-col min-w-0"
      style={{ ...innerCardStyle, minHeight: 320 }}
    >
      <header className="flex items-center gap-2 pb-2 mb-2 min-w-0"
        style={{ borderBottom: '1px solid var(--border-color)' }}>
        <span className="text-sm font-semibold text-primary truncate" title={label}>
          {label}
        </span>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0"
          style={palette}
        >
          {t(`dashboard.sentiment.today.hotTopics.categories.${source.category}`, source.category)}
        </span>
        {brandHits > 0 && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded font-semibold shrink-0"
            style={{ background: 'rgba(239,68,68,0.12)', color: '#dc2626' }}
            title={t('dashboard.sentiment.today.hotTopics.brandHits', { count: brandHits }) as string}
          >
            🔥 {brandHits}
          </span>
        )}
        <button
          type="button"
          onClick={() => hot.refetch()}
          disabled={hot.isFetching || usingMock}
          className="ml-auto text-[11px] text-muted hover:text-primary disabled:opacity-40 shrink-0"
          title={fetchedAt ? timeAgo(fetchedAt) : ''}
        >
          {hot.isFetching ? '...' : '↻'}
        </button>
      </header>

      <div className="flex-1 min-w-0">
        {hot.isLoading && (
          <p className="text-xs text-secondary py-6 text-center">
            {t('dashboard.sentiment.today.hotTopics.loading')}
          </p>
        )}
        {hot.isError && !hot.isLoading && (
          <p className="text-xs py-6 text-center" style={{ color: '#dc2626' }}>
            ⚠ {t('dashboard.sentiment.today.hotTopics.error')}
          </p>
        )}
        {!hot.isLoading && !hot.isError && items.length === 0 && (
          <p className="text-xs text-secondary py-6 text-center">
            {t('dashboard.sentiment.today.hotTopics.empty')}
          </p>
        )}
        {items.length > 0 && (
          <ol className="space-y-0.5">
            {items.map((it, idx) => (
              <HotItemRow
                key={`${source.id}-${it.id ?? idx}`}
                item={it}
                rank={idx + 1}
                isBrandHit={titleMatches(it.title, brandTerms)}
              />
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────── HotItemRow ───────────────────────────

function HotItemRow({
  item, rank, isBrandHit,
}: { item: NewsnowItem; rank: number; isBrandHit: boolean }) {
  const href = item.url || item.mobileUrl;
  const hotness = item.extra?.info;

  // Top 3 色阶 badge,4-10 灰色,11+ 更淡
  const rankBadge = (() => {
    if (rank === 1) return { background: '#dc2626', color: '#fff' };
    if (rank === 2) return { background: '#ea580c', color: '#fff' };
    if (rank === 3) return { background: '#ca8a04', color: '#fff' };
    if (rank <= 10) return { background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' };
    return { background: 'transparent', color: 'var(--text-muted)' };
  })();

  const rowBg = isBrandHit ? 'rgba(239,68,68,0.06)' : 'transparent';
  const titleColor = isBrandHit ? '#dc2626' : 'var(--text-primary)';

  const content = (
    <span className="flex items-center gap-2 min-w-0">
      <span
        className="text-[10px] font-bold tabular-nums w-5 h-5 rounded inline-flex items-center justify-center shrink-0"
        style={rankBadge}
      >
        {rank}
      </span>
      {isBrandHit && <span className="text-[11px] shrink-0">🔥</span>}
      <span
        className="text-xs truncate"
        style={{ color: titleColor, fontWeight: isBrandHit ? 600 : 400 }}
      >
        {item.title}
      </span>
      {hotness && (
        <span className="ml-auto text-[10px] text-muted shrink-0 tabular-nums">{hotness}</span>
      )}
    </span>
  );

  if (!href) {
    return <li className="py-1 px-1.5 rounded" style={{ background: rowBg }}>{content}</li>;
  }

  return (
    <li>
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="block py-1 px-1.5 rounded hover:brightness-110 transition-all"
        style={{ background: rowBg }}
      >
        {content}
      </a>
    </li>
  );
}

// 不分大小写,title 含任一 brand term 即命中
function titleMatches(title: string | undefined, terms: string[]): boolean {
  if (!title || terms.length === 0) return false;
  const t = title.toLowerCase();
  return terms.some(term => t.includes(term));
}
