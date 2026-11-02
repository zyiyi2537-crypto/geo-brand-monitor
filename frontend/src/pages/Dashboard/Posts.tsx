// 内容投放 — 渠道库 + 派稿 + 状态跟踪.
// 当前为静态页 MVP:渠道库 + 投放记录全 mock,不接后端 / 真派稿.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';

type ChannelCategory = 'owned' | 'pr' | 'vertical' | 'social';
type DispatchStatus = 'pending' | 'sent' | 'failed';

interface Channel {
  id: string;
  nameKey: string;
  category: ChannelCategory;
  icon: string;
}

interface DispatchEntry {
  id: number;
  title: string;
  query: string;
  channelIds: string[];
  status: DispatchStatus;
  scheduledAt: string;
  publishedAt?: string;
  url?: string;
  error?: string;
}

const CHANNELS: Channel[] = [
  { id: 'own-blog',           nameKey: 'dashboard.posts.ch.ownBlog',        category: 'owned',    icon: '🏠' },
  { id: 'own-wechat',         nameKey: 'dashboard.posts.ch.ownWechat',      category: 'owned',    icon: '🏠' },
  { id: 'own-newsletter',     nameKey: 'dashboard.posts.ch.ownNewsletter',  category: 'owned',    icon: '🏠' },
  { id: 'pr-newswire',        nameKey: 'dashboard.posts.ch.prNewswire',     category: 'pr',       icon: '📰' },
  { id: 'pr-businesswire',    nameKey: 'dashboard.posts.ch.prBusinesswire', category: 'pr',       icon: '📰' },
  { id: 'pr-prchina',         nameKey: 'dashboard.posts.ch.prChina',        category: 'pr',       icon: '📰' },
  { id: 'vertical-36kr',      nameKey: 'dashboard.posts.ch.vertical36kr',   category: 'vertical', icon: '📌' },
  { id: 'vertical-tmt',       nameKey: 'dashboard.posts.ch.verticalTmt',    category: 'vertical', icon: '📌' },
  { id: 'vertical-pinwan',    nameKey: 'dashboard.posts.ch.verticalPinwan', category: 'vertical', icon: '📌' },
  { id: 'vertical-huxiu',     nameKey: 'dashboard.posts.ch.verticalHuxiu',  category: 'vertical', icon: '📌' },
  { id: 'social-zhihu',       nameKey: 'dashboard.posts.ch.socialZhihu',    category: 'social',   icon: '💬' },
  { id: 'social-weibo',       nameKey: 'dashboard.posts.ch.socialWeibo',    category: 'social',   icon: '💬' },
  { id: 'social-xiaohongshu', nameKey: 'dashboard.posts.ch.socialXhs',      category: 'social',   icon: '💬' },
];

const MOCK_ENTRIES: DispatchEntry[] = [
  {
    id: 1,
    title: 'TMT 海外并购十大案例',
    query: '适合企业跨境 / TMT 投资、海外并购的北京律师',
    channelIds: ['own-blog', 'vertical-tmt'],
    status: 'sent',
    scheduledAt: '2026-05-10 09:00',
    publishedAt: '2026-05-10 09:05',
    url: 'https://example.com/articles/tmt-cases',
  },
  {
    id: 2,
    title: '反垄断合规要点 2026 深度解读',
    query: '适合反垄断申报与合规的北京律师',
    channelIds: ['own-blog', 'pr-prchina', 'vertical-36kr'],
    status: 'pending',
    scheduledAt: '2026-05-16 10:00',
  },
  {
    id: 3,
    title: '资本市场上市辅导经验白皮书',
    query: '适合资本市场(港股 / 美股 / A 股)的北京律师',
    channelIds: ['pr-newswire'],
    status: 'failed',
    scheduledAt: '2026-05-12 14:00',
    error: '渠道认证失效',
  },
];

export function Posts() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<DispatchStatus | 'all'>('all');
  const [showDispatch, setShowDispatch] = useState(false);
  const [entries] = useState<DispatchEntry[]>(MOCK_ENTRIES);

  const filtered = useMemo(() => {
    if (filter === 'all') return entries;
    return entries.filter(e => e.status === filter);
  }, [entries, filter]);

  const counts = useMemo(() => ({
    all: entries.length,
    pending: entries.filter(e => e.status === 'pending').length,
    sent: entries.filter(e => e.status === 'sent').length,
    failed: entries.filter(e => e.status === 'failed').length,
  }), [entries]);

  return (
    <div className="space-y-4">
      <PageHead titleKey="dashboard.nav.posts" titleFallback="Distribution" />

      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-primary leading-tight">
            {t('dashboard.nav.posts')}
          </h1>
          <p className="text-xs text-secondary mt-0.5">
            {t('dashboard.posts.subtitle')}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowDispatch(true)}
          className="px-3 py-1.5 text-sm rounded-md text-white"
          style={{ background: 'var(--accent-primary)' }}
        >
          + {t('dashboard.posts.newDispatch')}
        </button>
      </header>

      {/* 状态过滤 */}
      <div className="flex items-center gap-2 flex-wrap">
        {(['all', 'pending', 'sent', 'failed'] as const).map(k => (
          <button
            key={k}
            type="button"
            onClick={() => setFilter(k)}
            className="px-3 py-1 rounded-full text-xs"
            style={{
              background: filter === k ? 'var(--accent-primary)' : 'var(--bg-input)',
              color: filter === k ? 'var(--solid-btn-text)' : 'var(--text-secondary)',
              border: '1px solid var(--border-color)',
            }}
          >
            {t(`dashboard.posts.filter.${k}`)} ({counts[k]})
          </button>
        ))}
      </div>

      {/* 投放列表 */}
      <div className="space-y-3">
        {filtered.length === 0 && (
          <div className="py-12 text-center text-sm text-muted">
            {t('dashboard.posts.empty')}
          </div>
        )}
        {filtered.map(e => (
          <DispatchCard key={e.id} entry={e} />
        ))}
      </div>

      <p className="text-[11px] text-muted">
        {t('dashboard.posts.mockNotice')}
      </p>

      {showDispatch && (
        <DispatchModal onClose={() => setShowDispatch(false)} />
      )}
    </div>
  );
}

function DispatchCard({ entry }: { entry: DispatchEntry }) {
  const { t } = useTranslation();
  const channels = entry.channelIds
    .map(id => CHANNELS.find(c => c.id === id))
    .filter((c): c is Channel => !!c);

  const statusColor =
    entry.status === 'sent'   ? '#10b981' :
    entry.status === 'failed' ? '#ef4444' :
                                '#f59e0b';

  return (
    <article
      className="rounded-md p-4"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-primary">{entry.title}</h3>
          <p className="text-[11px] text-muted mt-0.5">
            <span className="text-secondary">Q:</span> {entry.query}
          </p>
        </div>
        <span
          className="text-[10px] font-bold px-2 py-0.5 rounded uppercase"
          style={{ background: `${statusColor}20`, color: statusColor }}
        >
          {t(`dashboard.posts.filter.${entry.status}`)}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {channels.map(c => (
          <span
            key={c.id}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px]"
            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
          >
            {c.icon} {t(c.nameKey)}
          </span>
        ))}
      </div>

      <div className="mt-3 flex items-center gap-4 text-[11px] text-muted flex-wrap">
        <span>{t('dashboard.posts.scheduledAt')} {entry.scheduledAt}</span>
        {entry.publishedAt && (
          <span>· {t('dashboard.posts.publishedAt')} {entry.publishedAt}</span>
        )}
        {entry.url && (
          <a
            href={entry.url}
            target="_blank"
            rel="noreferrer"
            className="underline"
            style={{ color: 'var(--accent-primary)' }}
          >
            🔗 {entry.url.replace(/^https?:\/\//, '').slice(0, 40)}…
          </a>
        )}
        {entry.error && <span style={{ color: '#ef4444' }}>⚠ {entry.error}</span>}
      </div>
    </article>
  );
}

function DispatchModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const groups: { cat: ChannelCategory; titleKey: string }[] = [
    { cat: 'owned',    titleKey: 'dashboard.posts.catOwned' },
    { cat: 'pr',       titleKey: 'dashboard.posts.catPr' },
    { cat: 'vertical', titleKey: 'dashboard.posts.catVertical' },
    { cat: 'social',   titleKey: 'dashboard.posts.catSocial' },
  ];

  const toggle = (id: string) => {
    setPicked(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="rounded-lg max-w-2xl w-full max-h-[85vh] overflow-y-auto p-5 space-y-4"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-primary">
            {t('dashboard.posts.dispatchTitle')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-secondary hover:text-primary"
          >✕</button>
        </header>

        <p className="text-xs text-muted">{t('dashboard.posts.dispatchHint')}</p>

        {groups.map(g => (
          <section key={g.cat} className="space-y-2">
            <h3 className="text-xs font-semibold text-secondary uppercase tracking-wide">
              {t(g.titleKey)}
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {CHANNELS.filter(c => c.category === g.cat).map(c => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => toggle(c.id)}
                  className="text-left px-3 py-2 rounded-md text-xs transition-colors"
                  style={{
                    background: picked.has(c.id) ? 'var(--bg-tertiary)' : 'var(--bg-input)',
                    border: `1px solid ${picked.has(c.id) ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                    color: 'var(--text-primary)',
                  }}
                >
                  <span className="mr-1.5">{c.icon}</span>
                  {t(c.nameKey)}
                </button>
              ))}
            </div>
          </section>
        ))}

        <footer
          className="flex items-center justify-between gap-3 pt-3 border-t"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <span className="text-xs text-muted">
            {t('dashboard.posts.pickedCount', { n: picked.size })}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded-md"
              style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)' }}
            >
              {t('common.cancel') || '取消'}
            </button>
            <button
              type="button"
              disabled={picked.size === 0}
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded-md text-white"
              style={{
                background: 'var(--accent-primary)',
                opacity: picked.size === 0 ? 0.5 : 1,
              }}
            >
              {t('dashboard.posts.confirmDispatch')}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
