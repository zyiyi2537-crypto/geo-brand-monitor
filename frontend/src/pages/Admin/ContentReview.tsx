// Admin 内容审核 — 选账号 + 主题 → 看文档列表 → 勾选送审 → 通过 + 选发布平台/媒体 (或拒绝).
// 路由:/workbench/content-review

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import {
  adminContentReviewApi,
  type DocSource, type DocStatus, type GeneratedDoc, type TopicWithDocs,
} from '../../services/adminContentReviewApi';

type StatusFilter = DocStatus | 'to_review' | 'all';
type SourceFilter = DocSource | 'all';

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'all',            label: 'all' },
  { key: 'to_review',      label: 'to_review' },
  { key: 'draft',          label: 'draft' },
  { key: 'pending_review', label: 'pending_review' },
  { key: 'approved',       label: 'approved' },
  { key: 'rejected',       label: 'rejected' },
  { key: 'published',      label: 'published' },
];

// 2026-05-28 — 多变体 combo 的可读 label(跟 BrandProfileForm 候选项同步)
const CREATION_DIRECTION_LABELS: Record<string, string> = {
  industry_insight: '行业洞察', case_story: '案例分享', how_to_guide: '实操指南',
  trend_forecast: '趋势预测', product_review: '产品评测', customer_story: '客户故事',
  faq: 'FAQ 答疑',
};
const COPYWRITING_TYPE_LABELS: Record<string, string> = {
  long_form: '深度长文', medium_post: '中等图文', short_social: '短社媒',
  video_script_long: '长视频脚本', video_script_short: '短视频文案', faq_list: 'FAQ 列表',
};
const CREATION_DIRECTION_COLOR = '#3b82f6';   // 蓝
const COPYWRITING_TYPE_COLOR = '#10b981';     // 绿

interface AdminContentReviewProps {
  // 锁定到指定 topic;给则隐藏 topic 选择器(用于项目详情页 stepper 内嵌)
  lockedTopicId?: number;
}

export function AdminContentReview({ lockedTopicId }: AdminContentReviewProps = {}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const token = localStorage.getItem('token') || '';

  // 深链:?topic=X 跳到指定项目,?status=Y 跳到指定状态(stepper / cockpit 待办卡用)
  // 若 lockedTopicId 给了,优先用它,完全忽略 URL.
  const initialUrlParams = useMemo(() => {
    const sp = new URLSearchParams(window.location.search);
    const topicParam = sp.get('topic');
    const statusParam = sp.get('status');
    return {
      topic: lockedTopicId ?? (topicParam ? Number(topicParam) : null),
      status: (statusParam as StatusFilter) || 'all',
    };
  }, [lockedTopicId]);

  const [topics, setTopics] = useState<TopicWithDocs[]>([]);
  const [topicId, setTopicId] = useState<number | null>(initialUrlParams.topic);
  const [docs, setDocs] = useState<GeneratedDoc[]>([]);
  const [status, setStatus] = useState<StatusFilter>(initialUrlParams.status);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [openDocId, setOpenDocId] = useState<number | null>(null);
  // 行内「通过」后让模态框开起来时,直接给它一份新数据 — docs[] 可能因 status filter
  // 把刚 approve 的 doc 过滤掉,光靠 docs.find() 就拿不到了
  const [forceOpenDoc, setForceOpenDoc] = useState<GeneratedDoc | null>(null);
  // 行内 approve 触发的「自动展开发布选择器」一次性 flag
  const [autoOpenPublish, setAutoOpenPublish] = useState(false);
  // 2026-05-28 — 同一 query 多份稿件折叠;set 里的 query 是收起的
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const toggleGroup = useCallback((q: string) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev);
      if (next.has(q)) next.delete(q); else next.add(q);
      return next;
    });
  }, []);
  const [searchText, setSearchText] = useState('');
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;
  // 行内「通过」按钮的 per-doc busy / err
  const [inlineBusyId, setInlineBusyId] = useState<number | null>(null);
  const [inlineErr, setInlineErr] = useState<string | null>(null);

  const isAdmin = useMemo(() => {
    try {
      const stored = localStorage.getItem('user');
      return stored ? !!JSON.parse(stored).is_admin : false;
    } catch { return false; }
  }, []);

  const refreshTopics = useCallback(async () => {
    try {
      const rs = await adminContentReviewApi.listTopics(token);
      setTopics(rs);
      // lockedTopicId 模式不自动覆盖,锁定不变
      if (lockedTopicId === undefined && rs.length > 0 && topicId === null) {
        setTopicId(rs[0].topic_id);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [token, topicId, lockedTopicId]);

  const refreshDocs = useCallback(async () => {
    if (topicId === null) return;
    setLoading(true); setErr(null);
    try {
      const ds = await adminContentReviewApi.listDocs(
        topicId, status === 'all' ? undefined : status, token,
        sourceFilter === 'all' ? undefined : sourceFilter,
      );
      setDocs(ds);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [topicId, status, sourceFilter, token]);

  useEffect(() => {
    if (!isAdmin) { navigate('/dashboard', { replace: true }); return; }
    refreshTopics();
  }, [isAdmin, navigate, refreshTopics]);

  useEffect(() => { refreshDocs(); }, [refreshDocs]);

  if (!isAdmin) return null;

  const selectedDoc = openDocId
    ? (forceOpenDoc && forceOpenDoc.id === openDocId
        ? forceOpenDoc
        : docs.find(d => d.id === openDocId) || null)
    : null;

  const togglePick = (id: number) => {
    setPicked(prev => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  };

  const sendToReview = async () => {
    if (picked.size === 0) return;
    try {
      await adminContentReviewApi.selectForReview(Array.from(picked), token);
      setPicked(new Set());
      refreshDocs(); refreshTopics();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  // 行内一键通过(pending_review 专用) — approve 之后直接把发布选择器打开,
  // 省得用户切到「已通过」tab 再翻一遍.
  const handleInlineApprove = async (docId: number) => {
    if (inlineBusyId !== null) return;
    setInlineBusyId(docId); setInlineErr(null);
    try {
      const fresh = await adminContentReviewApi.approveDoc(docId, token);
      setForceOpenDoc(fresh);
      setOpenDocId(docId);
      setAutoOpenPublish(true);
      refreshDocs(); refreshTopics();
    } catch (e: unknown) {
      setInlineErr(e instanceof Error ? e.message : String(e));
    } finally {
      setInlineBusyId(null);
    }
  };

  // 搜索 + 分页(客户端):docs 顺序由后端给,这里只过滤 + 切片.
  // 搜索 / 筛选切换时回到第 1 页;status/sourceFilter 在 refreshDocs 触发后 docs 重置,page 也回 1.
  const filteredDocs = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    if (!q) return docs;
    return docs.filter(d => {
      const hay = [d.title, d.summary, d.source_query_text].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [docs, searchText]);
  const totalPages = Math.max(1, Math.ceil(filteredDocs.length / PAGE_SIZE));
  useEffect(() => { setPage(1); }, [searchText, status, sourceFilter, topicId]);
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  const pagedDocs = useMemo(
    () => filteredDocs.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filteredDocs, page],
  );

  return (
    <div className="space-y-4">
      {/* 锁定模式由父页负责标题(stepper 已经接管上下文),不重复渲染 */}
      {lockedTopicId === undefined && (
        <>
          <PageHead titleKey="admin.contentReview.title" titleFallback="内容审核" />
          <header className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <h1 className="text-xl font-semibold text-primary">{t('admin.contentReview.title')}</h1>
              <p className="text-xs text-secondary mt-0.5">{t('admin.contentReview.subtitle')}</p>
            </div>
            <button type="button" onClick={() => { refreshTopics(); refreshDocs(); }}
                    className="text-xs px-3 py-1.5 rounded-md"
                    style={{ background: 'var(--bg-tertiary)', color: 'var(--accent-primary)' }}>
              ⟳ {t('admin.contentReview.refresh')}
            </button>
          </header>
        </>
      )}

      <div className="rounded-md p-3 flex flex-wrap gap-3 items-end"
           style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        {/* 锁定模式不显示 topic 选择器(stepper 上下文已锁定项目) */}
        {lockedTopicId === undefined && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">{t('admin.contentReview.topicLabel')}</label>
            <select value={topicId ?? ''}
                    onChange={e => { setTopicId(Number(e.target.value)); setPicked(new Set()); }}
                    className="text-sm px-3 py-1.5 rounded-md min-w-[260px]"
                    style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                             border: '1px solid var(--border-color)' }}>
              {topics.map(tp => (
                <option key={tp.topic_id} value={tp.topic_id}>
                  {tp.topic_name} · {tp.user_email} · ({tp.draft_count}/{tp.doc_count})
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">{t('admin.contentReview.statusLabel')}</label>
          <div className="flex gap-1">
            {STATUS_FILTERS.map(f => (
              <button key={f.key} type="button" onClick={() => setStatus(f.key)}
                      className="text-xs px-2.5 py-1 rounded-md"
                      style={{
                        background: status === f.key ? 'var(--accent-primary)' : 'var(--bg-input)',
                        color: status === f.key ? '#fff' : 'var(--text-secondary)',
                        border: '1px solid var(--border-color)',
                      }}>
                {t(`admin.contentReview.statusFilter.${f.key}`)}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">{t('admin.contentReview.sourceLabel')}</label>
          <div className="flex gap-1">
            {(['all', 'ai', 'user'] as SourceFilter[]).map(k => (
              <button key={k} type="button" onClick={() => setSourceFilter(k)}
                      className="text-xs px-2.5 py-1 rounded-md"
                      style={{
                        background: sourceFilter === k ? 'var(--accent-primary)' : 'var(--bg-input)',
                        color: sourceFilter === k ? '#fff' : 'var(--text-secondary)',
                        border: '1px solid var(--border-color)',
                      }}>
                {t(`admin.contentReview.sourceFilter.${k}`)}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1 flex-1 min-w-[180px]">
          <label className="text-xs text-muted">{t('admin.contentReview.searchLabel', { defaultValue: '搜索' })}</label>
          <input type="search" value={searchText}
                 onChange={e => setSearchText(e.target.value)}
                 placeholder={t('admin.contentReview.searchPlaceholder', { defaultValue: '标题 / 摘要 / 问题…' })}
                 className="text-sm px-3 py-1.5 rounded-md w-full"
                 style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                          border: '1px solid var(--border-color)' }} />
        </div>

        {picked.size > 0 && (
          <button type="button" onClick={sendToReview}
                  className="text-sm px-4 py-2 rounded-md text-white"
                  style={{ background: 'var(--accent-primary)' }}>
            {t('admin.contentReview.sendToReview', { n: picked.size })}
          </button>
        )}
      </div>

      {err && (
        <div className="rounded-md p-3 text-sm"
             style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                      border: '1px solid rgba(239,68,68,0.3)' }}>
          {err}
        </div>
      )}

      {inlineErr && (
        <div className="rounded-md p-3 text-sm"
             style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                      border: '1px solid rgba(239,68,68,0.3)' }}>
          {inlineErr}
        </div>
      )}

      {loading && <div className="py-12 text-center text-sm text-muted">…</div>}

      {!loading && filteredDocs.length === 0 && (
        <div className="py-12 text-center text-sm text-muted">
          {searchText
            ? t('admin.contentReview.emptySearch', { defaultValue: '没有匹配的文档' })
            : t('admin.contentReview.empty')}
        </div>
      )}

      <div className="space-y-2">
        {(() => {
          // 2026-05-28 — 同一 source_query_text 有 ≥2 篇时折叠成组,展示 query 头 + 子项;
          // 单篇 query 仍直出 DocCard,保持老体验.
          const groups: { query: string; docs: typeof pagedDocs }[] = [];
          const byQuery = new Map<string, typeof pagedDocs>();
          for (const d of pagedDocs) {
            const q = (d.source_query_text || '').trim() || '(无 query)';
            if (!byQuery.has(q)) byQuery.set(q, []);
            byQuery.get(q)!.push(d);
          }
          for (const [q, docs] of byQuery) groups.push({ query: q, docs });
          return groups.map(g => {
            if (g.docs.length === 1) {
              const d = g.docs[0];
              return (
                <DocCard key={d.id} doc={d}
                         pickable={d.status === 'draft'}
                         picked={picked.has(d.id)}
                         onPick={() => togglePick(d.id)}
                         onOpen={() => setOpenDocId(d.id)}
                         approveBusy={inlineBusyId === d.id}
                         onInlineApprove={d.status === 'pending_review'
                           ? () => handleInlineApprove(d.id)
                           : undefined} />
              );
            }
            const collapsed = collapsedGroups.has(g.query);
            return (
              <div key={g.query} className="space-y-1">
                <button type="button"
                        onClick={() => toggleGroup(g.query)}
                        className="w-full text-left rounded-md p-2 flex items-center gap-2"
                        style={{ background: 'var(--bg-secondary)',
                                 border: '1px solid var(--border-color)' }}>
                  <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {collapsed ? '▶' : '▼'}
                  </span>
                  <span className="text-xs font-medium flex-1 truncate"
                        style={{ color: 'var(--text-primary)' }}>
                    Query: {g.query}
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full"
                        style={{ background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                    {g.docs.length} 篇
                  </span>
                </button>
                {!collapsed && (
                  <div className="pl-4 space-y-1">
                    {g.docs.map(d => (
                      <DocCard key={d.id} doc={d}
                               pickable={d.status === 'draft'}
                               picked={picked.has(d.id)}
                               onPick={() => togglePick(d.id)}
                               onOpen={() => setOpenDocId(d.id)}
                               approveBusy={inlineBusyId === d.id}
                               onInlineApprove={d.status === 'pending_review'
                                 ? () => handleInlineApprove(d.id)
                                 : undefined} />
                    ))}
                  </div>
                )}
              </div>
            );
          });
        })()}
      </div>

      {filteredDocs.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-secondary px-1 pt-1">
          <span className="tabular-nums text-muted">
            {(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, filteredDocs.length)} / {filteredDocs.length}
          </span>
          <div className="flex items-center gap-2">
            <button type="button" disabled={page <= 1}
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    className="px-2 py-1 rounded-md disabled:opacity-40"
                    style={{ background: 'var(--bg-tertiary)' }}>
              {t('admin.contentReview.prev', { defaultValue: '上一页' })}
            </button>
            <span className="tabular-nums">{page} / {totalPages}</span>
            <button type="button" disabled={page >= totalPages}
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    className="px-2 py-1 rounded-md disabled:opacity-40"
                    style={{ background: 'var(--bg-tertiary)' }}>
              {t('admin.contentReview.next', { defaultValue: '下一页' })}
            </button>
          </div>
        </div>
      )}

      {selectedDoc && (
        <DocDetailModal doc={selectedDoc}
                        token={token}
                        autoOpenPublish={autoOpenPublish}
                        onClose={() => {
                          setOpenDocId(null);
                          setForceOpenDoc(null);
                          setAutoOpenPublish(false);
                        }}
                        onAnyChange={() => { refreshDocs(); refreshTopics(); }} />
      )}
    </div>
  );
}

function DocCard({ doc, pickable, picked, onPick, onOpen, onInlineApprove, approveBusy }: {
  doc: GeneratedDoc; pickable: boolean; picked: boolean;
  onPick: () => void; onOpen: () => void;
  // 仅 pending_review 给 → 渲染行内「✓ 通过」按钮,一键 approve
  onInlineApprove?: () => void;
  approveBusy?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <section className="rounded-md p-3 flex items-start gap-3 flex-wrap"
             style={{ background: picked ? 'var(--bg-tertiary)' : 'var(--bg-card)',
                      border: `1px solid ${picked ? 'var(--accent-primary)' : 'var(--border-color)'}` }}>
      {pickable && (
        <input type="checkbox" checked={picked} onChange={onPick} className="mt-1"
               style={{ accentColor: 'var(--accent-primary)' }} />
      )}
      <div className="flex-1 min-w-0 cursor-pointer" onClick={onOpen}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-primary">{doc.title || `#${doc.id}`}</span>
          <DocStatusChip status={doc.status} />
          <DocSourceChip source={doc.source} />
          {/* 2026-05-28 — combo chips:同一 query 多份稿件按 (direction, type) 区分 */}
          {doc.creation_direction && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                  style={{ background: `${CREATION_DIRECTION_COLOR}22`,
                           color: CREATION_DIRECTION_COLOR }}>
              {CREATION_DIRECTION_LABELS[doc.creation_direction] || doc.creation_direction}
            </span>
          )}
          {doc.copywriting_type && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                  style={{ background: `${COPYWRITING_TYPE_COLOR}22`,
                           color: COPYWRITING_TYPE_COLOR }}>
              {COPYWRITING_TYPE_LABELS[doc.copywriting_type] || doc.copywriting_type}
            </span>
          )}
          {doc.generation_error && (
            <span className="text-[10px]" style={{ color: '#ef4444' }}>
              ⚠ {t('admin.contentReview.genError')}
            </span>
          )}
        </div>
        {doc.source_query_text && (
          <div className="text-[11px] text-muted mt-0.5">
            {t('admin.contentReview.sourceQuery')}:{doc.source_query_text}
          </div>
        )}
        {doc.summary && (
          <div className="text-xs text-secondary mt-1 line-clamp-2">{doc.summary}</div>
        )}
        {doc.publish_targets.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {doc.publish_targets.map((p, i) => (
              <span key={i} className="text-[10px] px-2 py-0.5 rounded-full"
                    style={{ background: 'rgba(59,130,246,0.12)', color: '#3b82f6' }}>
                {p.platform}{p.media ? ` / ${p.media}` : ''}
              </span>
            ))}
          </div>
        )}
        <MediumslyStateChip doc={doc} compact />
      </div>
      <div className="flex items-center gap-2 self-center">
        {onInlineApprove && (
          <button type="button" disabled={approveBusy}
                  onClick={(e) => { e.stopPropagation(); onInlineApprove(); }}
                  className="text-xs px-3 py-1 rounded-md text-white"
                  style={{ background: 'var(--accent-primary)',
                           opacity: approveBusy ? 0.5 : 1 }}>
            {approveBusy ? '…' : `✓ ${t('admin.contentReview.approve')}`}
          </button>
        )}
        <button type="button" onClick={onOpen}
                className="text-xs px-3 py-1 rounded-md"
                style={{ background: 'var(--bg-input)', color: 'var(--accent-primary)',
                         border: '1px solid var(--border-color)' }}>
          {t('admin.contentReview.view')}
        </button>
      </div>
    </section>
  );
}

// Mediumsly 推送状态展示:成功 → 绿色链接;失败 → 红色错误。`compact` 是列表卡片用的小尺寸。
function MediumslyStateChip({ doc, compact = false }: { doc: GeneratedDoc; compact?: boolean }) {
  const { t } = useTranslation();
  if (doc.mediumsly_url) {
    const labelKey = compact ? 'admin.contentReview.mediumslyPushedShort'
                              : 'admin.contentReview.mediumslyPushed';
    return (
      <div className={compact ? 'mt-1' : 'mt-2'}>
        <a href={doc.mediumsly_url} target="_blank" rel="noreferrer"
           className={`${compact ? 'text-[10px]' : 'text-xs'} inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full underline`}
           style={{ background: 'rgba(34,197,94,0.12)', color: '#22c55e' }}>
          ✓ {t(labelKey)}
          {!compact && doc.mediumsly_pushed_at && (
            <span className="text-muted">
              · {new Date(doc.mediumsly_pushed_at).toLocaleString()}
            </span>
          )}
        </a>
      </div>
    );
  }
  if (doc.mediumsly_last_error) {
    return (
      <div className={compact ? 'mt-1' : 'mt-2'}>
        <span className={`${compact ? 'text-[10px]' : 'text-xs'} inline-block px-2 py-0.5 rounded-md`}
              style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                       border: '1px solid rgba(239,68,68,0.3)',
                       maxWidth: compact ? 360 : '100%' }}
              title={doc.mediumsly_last_error}>
          ⚠ {t('admin.contentReview.mediumslyFailed')}
          {!compact && `: ${doc.mediumsly_last_error}`}
        </span>
      </div>
    );
  }
  return null;
}

function DocSourceChip({ source }: { source: DocSource }) {
  const { t } = useTranslation();
  const cm = source === 'ai'
    ? { c: '#8b5cf6', bg: 'rgba(139,92,246,0.15)' }
    : { c: '#06b6d4', bg: 'rgba(6,182,212,0.15)' };
  return (
    <span className="text-[10px] px-2 py-0.5 rounded-full"
          style={{ background: cm.bg, color: cm.c }}>
      {t(`admin.contentReview.sourceFilter.${source}`)}
    </span>
  );
}

function DocStatusChip({ status }: { status: DocStatus }) {
  const { t } = useTranslation();
  const cm: Record<DocStatus, { c: string; bg: string }> = {
    draft:          { c: '#94a3b8', bg: 'rgba(148,163,184,0.15)' },
    pending_review: { c: '#eab308', bg: 'rgba(234,179,8,0.15)' },
    approved:       { c: '#10b981', bg: 'rgba(16,185,129,0.15)' },
    rejected:       { c: '#ef4444', bg: 'rgba(239,68,68,0.15)' },
    published:      { c: '#3b82f6', bg: 'rgba(59,130,246,0.15)' },
  };
  const s = cm[status];
  return (
    <span className="text-[10px] px-2 py-0.5 rounded-full"
          style={{ background: s.bg, color: s.c }}>
      {t(`admin.contentReview.statusFilter.${status}`)}
    </span>
  );
}

function DocDetailModal({ doc: initialDoc, token, onClose, onAnyChange, autoOpenPublish }:
  { doc: GeneratedDoc; token: string; onClose: () => void; onAnyChange: () => void;
    autoOpenPublish?: boolean }) {
  const { t } = useTranslation();
  // 模态框自己维护当前 doc;不依赖父组件的 docs[] 过滤后结果(否则一旦状态变了 doc
  // 被过滤出列表,modal 就会因为 selectedDoc 变 null 而消失)
  const [doc, setDoc] = useState<GeneratedDoc>(initialDoc);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showReject, setShowReject] = useState(false);
  // 2026-06-12 — 平台审核结果回填(published 稿)
  const [showPlatformReject, setShowPlatformReject] = useState(false);
  const [platformRejectReason, setPlatformRejectReason] = useState('');
  const [rejectReason, setRejectReason] = useState('');
  const [showPublish, setShowPublish] = useState(false);
  const [editing, setEditing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [editTitle, setEditTitle] = useState(doc.title);
  const [editBody, setEditBody] = useState(doc.body_markdown);
  const [editSummary, setEditSummary] = useState(doc.summary);

  // 行内通过后自动打开发布选择器,一次性
  const autoOpenedRef = useRef(false);
  useEffect(() => {
    if (autoOpenPublish && doc.status === 'approved' && !autoOpenedRef.current) {
      autoOpenedRef.current = true;
      setShowPublish(true);
    }
  }, [autoOpenPublish, doc.status]);

  // mutation 后调一次拿到最新 doc — 替换本地 state,模态框 UI 立刻反应新状态
  const refetch = useCallback(async () => {
    try {
      const fresh = await adminContentReviewApi.getDoc(doc.id, token);
      setDoc(fresh);
    } catch { /* 留旧 doc,onAnyChange 会让父列表自己刷,模态层降级展示无害 */ }
  }, [doc.id, token]);

  // 返回 boolean 表示成功 — 调用方按需决定下一步(展开 publish 选择器、关弹窗等)
  const wrap = async (fn: () => Promise<unknown>): Promise<boolean> => {
    if (busy) return false;
    setBusy(true); setErr(null);
    try {
      await fn();
      await refetch();
      onAnyChange();
      return true;
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleApprove = async () => {
    const ok = await wrap(() => adminContentReviewApi.approveDoc(doc.id, token));
    if (ok) setShowPublish(true);   // 通过后直接展开发布选择器,不用再点一次
  };

  const handleReject = async () => {
    const ok = await wrap(() => adminContentReviewApi.rejectDoc(doc.id, rejectReason.trim(), token));
    if (ok) onClose();
  };

  const handlePublish = async (
    targets: { platform: string; media: string; url?: string }[],
    pushToMediumsly: boolean,
  ) => {
    const ok = await wrap(() => adminContentReviewApi.publishDoc(doc.id, targets, token, pushToMediumsly));
    if (ok) onClose();
  };

  const handleSaveEdit = async () => {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      await adminContentReviewApi.updateDoc(doc.id, {
        title: editTitle, body_markdown: editBody, summary: editSummary,
      }, token);
      await refetch();
      setEditing(false);
      onAnyChange();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleRegenerate = async () => {
    if (busy || regenerating) return;
    if (!window.confirm('重新生成会用 AI 覆盖当前标题和正文(包括手动修改过的内容),确定继续?')) return;
    setRegenerating(true); setErr(null);
    try {
      const fresh = await adminContentReviewApi.regenerateDoc(doc.id, token);
      setDoc(fresh);
      setEditing(false);
      onAnyChange();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ background: 'rgba(0,0,0,0.5)' }}>
      <div className="rounded-md w-full max-w-3xl max-h-[90vh] flex flex-col"
           style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="p-4 flex items-start justify-between gap-3 border-b"
             style={{ borderColor: 'var(--border-color)' }}>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-semibold text-primary">{doc.title || `#${doc.id}`}</h2>
              <DocStatusChip status={doc.status} />
              <DocSourceChip source={doc.source} />
            </div>
            <div className="text-xs text-muted mt-1">
              {doc.source_query_text}
              {' · '}{new Date(doc.created_at).toLocaleString()}
            </div>
          </div>
          {!editing && (
            <>
              <button type="button"
                      onClick={() => {
                        setEditTitle(doc.title);
                        setEditBody(doc.body_markdown);
                        setEditSummary(doc.summary);
                        setEditing(true);
                      }}
                      disabled={regenerating}
                      className="text-xs px-2.5 py-1 rounded-md"
                      style={{ background: 'transparent', color: 'var(--text-secondary)',
                               border: '1px solid var(--border-color)' }}>
                ✎ 编辑
              </button>
              {doc.status !== 'approved' && doc.status !== 'published' && (
                <button type="button"
                        onClick={handleRegenerate}
                        disabled={busy || regenerating}
                        className="text-xs px-2.5 py-1 rounded-md"
                        style={{ background: 'transparent', color: 'var(--text-secondary)',
                                 border: '1px solid var(--border-color)',
                                 opacity: (busy || regenerating) ? 0.6 : 1 }}>
                  {regenerating ? '↻ 重新生成中…' : '↻ 重新生成'}
                </button>
              )}
            </>
          )}
          <button type="button" onClick={onClose} className="text-muted hover:text-primary">✕</button>
        </div>

        <div className="p-4 flex-1 overflow-auto space-y-3">
          {err && <div className="text-xs" style={{ color: '#ef4444' }}>{err}</div>}
          {doc.generation_error && (
            <div className="rounded-md p-2 text-xs"
                 style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
              {doc.generation_error}
            </div>
          )}
          {doc.reject_reason && (
            <div className="rounded-md p-2 text-xs"
                 style={{ background: 'rgba(239,68,68,0.05)', color: '#ef4444',
                          border: '1px solid rgba(239,68,68,0.3)' }}>
              {t('admin.contentReview.rejectReason')}:{doc.reject_reason}
            </div>
          )}
          {editing ? (
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-muted mb-1">标题</label>
                <input className="w-full rounded-md px-2 py-1.5 text-sm"
                       style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                                border: '1px solid var(--border-color)' }}
                       value={editTitle} onChange={e => setEditTitle(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">正文</label>
                <textarea className="w-full rounded-md px-2 py-1.5 text-sm font-mono leading-relaxed"
                          style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                                   border: '1px solid var(--border-color)', minHeight: 280 }}
                          value={editBody} onChange={e => setEditBody(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">摘要</label>
                <textarea rows={2} className="w-full rounded-md px-2 py-1.5 text-sm"
                          style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                                   border: '1px solid var(--border-color)' }}
                          value={editSummary} onChange={e => setEditSummary(e.target.value)} />
              </div>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setEditing(false)} disabled={busy}
                        className="text-xs px-3 py-1.5 rounded-md"
                        style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)',
                                 border: '1px solid var(--border-color)' }}>
                  取消
                </button>
                <button type="button" onClick={handleSaveEdit} disabled={busy}
                        className="text-xs px-3 py-1.5 rounded-md text-white"
                        style={{ background: 'var(--accent-primary)', opacity: busy ? 0.5 : 1 }}>
                  {busy ? '保存中…' : '保存'}
                </button>
              </div>
            </div>
          ) : (
            <article className="text-sm text-primary whitespace-pre-wrap leading-relaxed">
              {doc.body_markdown || <span className="text-muted">{t('admin.contentReview.emptyBody')}</span>}
            </article>
          )}
          {doc.publish_targets.length > 0 && (
            <div>
              <p className="text-xs text-muted mb-1">{t('admin.contentReview.publishedTo')}:</p>
              <div className="flex flex-wrap gap-1.5">
                {doc.publish_targets.map((p, i) => (
                  <span key={i}
                        className="text-[11px] px-2 py-0.5 rounded-full inline-flex items-center gap-1.5"
                        style={{ background: 'rgba(59,130,246,0.12)', color: '#3b82f6' }}>
                    {p.platform}{p.media ? ` / ${p.media}` : ''}
                    {p.url && (
                      <a href={p.url} target="_blank" rel="noreferrer"
                         className="underline opacity-80 hover:opacity-100">🔗</a>
                    )}
                    <span className="text-muted ml-1">
                      {p.marked_at && new Date(p.marked_at).toLocaleDateString()}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          )}
          <MediumslyStateChip doc={doc} />
        </div>

        <div className="p-3 border-t flex justify-end gap-2 flex-wrap"
             style={{ borderColor: 'var(--border-color)' }}>
          {(doc.status === 'draft' || doc.status === 'pending_review') && (
            <>
              <button type="button" onClick={() => setShowReject(true)} disabled={busy}
                      className="text-xs px-4 py-1.5 rounded-md"
                      style={{ background: 'var(--bg-input)', color: '#ef4444',
                               border: '1px solid var(--border-color)' }}>
                {t('admin.contentReview.reject')}
              </button>
              <button type="button" disabled={busy}
                      onClick={handleApprove}
                      className="text-xs px-4 py-1.5 rounded-md text-white"
                      style={{ background: 'var(--accent-primary)' }}>
                {t('admin.contentReview.approve')}
              </button>
            </>
          )}
          {doc.status === 'approved' && (
            <button type="button" onClick={() => setShowPublish(true)} disabled={busy}
                    className="text-xs px-4 py-1.5 rounded-md text-white"
                    style={{ background: '#3b82f6' }}>
              {t('admin.contentReview.choosePublish')}
            </button>
          )}
          {/* 2026-06-12 — 平台审核结果回填:被拒原因会进平台规则学习 */}
          {doc.status === 'published' && (
            <>
              {doc.platform_review_status === 'passed' && (
                <span className="text-xs px-2 py-1 rounded-md self-center"
                      style={{ background: 'rgba(16,185,129,0.12)', color: '#10b981' }}>
                  平台已过审
                </span>
              )}
              {doc.platform_review_status === 'rejected' && (
                <span className="text-xs px-2 py-1 rounded-md self-center"
                      title={doc.platform_reject_reason || ''}
                      style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444' }}>
                  平台被拒:{(doc.platform_reject_reason || '').slice(0, 30)}
                </span>
              )}
              <button type="button" disabled={busy}
                      onClick={() => setShowPlatformReject(v => !v)}
                      className="text-xs px-4 py-1.5 rounded-md"
                      style={{ background: 'var(--bg-input)', color: '#ef4444',
                               border: '1px solid var(--border-color)' }}>
                平台被拒…
              </button>
              <button type="button" disabled={busy}
                      onClick={() => wrap(() =>
                        adminContentReviewApi.setPlatformReview(doc.id, 'passed', token))}
                      className="text-xs px-4 py-1.5 rounded-md text-white"
                      style={{ background: '#10b981' }}>
                ✓ 平台已过审
              </button>
            </>
          )}
        </div>

        {showPlatformReject && (
          <div className="p-3 border-t"
               style={{ borderColor: 'var(--border-color)', background: 'var(--bg-tertiary)' }}>
            <p className="text-xs text-secondary mb-2">
              平台拒稿原因(必填 — 会被「平台规则·从拒稿学习」提炼成该平台审核规则)
            </p>
            <textarea value={platformRejectReason}
                      onChange={e => setPlatformRejectReason(e.target.value)} rows={2}
                      placeholder="例:含绝对化用语「全网第一」被拒 / 文末二维码导流被拒…"
                      className="w-full text-sm px-3 py-2 rounded-md"
                      style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                               border: '1px solid var(--border-color)' }} />
            <div className="flex justify-end gap-2 mt-2">
              <button type="button"
                      onClick={() => { setShowPlatformReject(false); setPlatformRejectReason(''); }}
                      className="text-xs px-3 py-1 rounded-md"
                      style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)' }}>
                {t('admin.contentReview.cancel')}
              </button>
              <button type="button" disabled={busy || !platformRejectReason.trim()}
                      onClick={async () => {
                        const ok = await wrap(() => adminContentReviewApi.setPlatformReview(
                          doc.id, 'rejected', token, platformRejectReason.trim()));
                        if (ok) { setShowPlatformReject(false); setPlatformRejectReason(''); }
                      }}
                      className="text-xs px-3 py-1 rounded-md text-white disabled:opacity-40"
                      style={{ background: '#ef4444' }}>
                {busy ? '…' : '确认回填'}
              </button>
            </div>
          </div>
        )}

        {showReject && (
          <div className="p-3 border-t"
               style={{ borderColor: 'var(--border-color)', background: 'var(--bg-tertiary)' }}>
            <p className="text-xs text-secondary mb-2">{t('admin.contentReview.rejectReasonLabel')}</p>
            <textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)} rows={2}
                      className="w-full text-sm px-3 py-2 rounded-md"
                      style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                               border: '1px solid var(--border-color)' }} />
            <div className="flex justify-end gap-2 mt-2">
              <button type="button" onClick={() => { setShowReject(false); setRejectReason(''); }}
                      className="text-xs px-3 py-1 rounded-md"
                      style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)' }}>
                {t('admin.contentReview.cancel')}
              </button>
              <button type="button" disabled={busy}
                      onClick={handleReject}
                      className="text-xs px-3 py-1 rounded-md text-white"
                      style={{ background: '#ef4444' }}>
                {t('admin.contentReview.confirmReject')}
              </button>
            </div>
          </div>
        )}

        {showPublish && (
          <PublishPicker onCancel={() => setShowPublish(false)}
                         onConfirm={handlePublish}
                         busy={busy} />
        )}
      </div>
    </div>
  );
}

// 通过审核后的发布卡片。目前只有 Mediumsly 一个自动发布渠道,所以 UI 就是一个
// 确认卡 + 一个大按钮。以后再接其他平台时再扩成多渠道选择器,不预先做空抽象。
function PublishPicker({ onCancel, onConfirm, busy }: {
  onCancel: () => void;
  onConfirm: (targets: { platform: string; media: string; url?: string }[],
              pushToMediumsly: boolean) => void;
  busy?: boolean;
}) {
  const { t } = useTranslation();
  const submit = () => onConfirm([], true);

  return (
    <div className="p-4 border-t space-y-3"
         style={{ borderColor: 'var(--border-color)', background: 'var(--bg-tertiary)' }}>
      <div>
        <p className="text-sm font-medium text-primary">
          {t('admin.contentReview.publishToMediumslyTitle')}
        </p>
        <p className="text-xs text-secondary mt-1 leading-relaxed">
          {t('admin.contentReview.publishToMediumslyHint')}
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} disabled={busy}
                className="text-xs px-3 py-1.5 rounded-md"
                style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)',
                         border: '1px solid var(--border-color)' }}>
          {t('admin.contentReview.cancel')}
        </button>
        <button type="button" onClick={submit} disabled={busy}
                className="text-xs px-4 py-1.5 rounded-md text-white font-medium"
                style={{ background: '#3b82f6', opacity: busy ? 0.6 : 1 }}>
          {busy ? `${t('admin.contentReview.publishing')}…` : `✓ ${t('admin.contentReview.publishToMediumslyConfirm')}`}
        </button>
      </div>
    </div>
  );
}
