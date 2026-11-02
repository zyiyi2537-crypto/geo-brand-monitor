// Phase D.1 — 内容(合并原 Compose + Posts).
// 一屏看到该 topic 下所有 AI 生成 / 用户提交的稿件 + 审核状态 + 已发布媒体.
//
// 路由:/dashboard/content
//
// 组成:
//   1. 顶栏:topic 切换 + AI 排程入口 + 「+ 提交文章」入口
//   2. 5 张统计卡:已发布 / 待审核 / 待修改(rejected) / 草稿 / AI 自动状态
//   3. 状态 + 来源筛选条
//   4. 文章列表(单条点开 → 详情抽屉)
//   5. SubmitDrawer / AutoScheduleDrawer / DocDetailDrawer

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import { aiTelemetryApi, type Topic } from '../../services/aiTelemetryApi';
import {
  contentApi,
  type ContentDoc, type ContentStats,
  type DocSource, type DocStatus,
  type AutoGenerateConfig,
} from '../../services/contentApi';

type StatusFilter = DocStatus | 'all';
type SourceFilter = DocSource | 'all';

const STATUS_FILTERS: StatusFilter[] = ['all', 'draft', 'pending_review', 'rejected', 'approved', 'published'];

export function Content() {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';

  const [topics, setTopics] = useState<Topic[]>([]);
  const [topicId, setTopicId] = useState<number | null>(null);
  const [docs, setDocs] = useState<ContentDoc[]>([]);
  const [stats, setStats] = useState<ContentStats | null>(null);
  const [status, setStatus] = useState<StatusFilter>('all');
  const [source, setSource] = useState<SourceFilter>('all');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [openDocId, setOpenDocId] = useState<number | null>(null);
  const [showSubmit, setShowSubmit] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);

  useEffect(() => {
    aiTelemetryApi.listTopics(token)
      .then(list => {
        setTopics(list);
        if (list[0]?.id) setTopicId(list[0].id);
      })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)));
  }, [token]);

  const currentTopic = useMemo(
    () => topics.find(x => x.id === topicId) || null,
    [topics, topicId],
  );

  const refresh = useCallback(async () => {
    if (topicId == null) return;
    setLoading(true); setErr(null);
    try {
      const [docList, s] = await Promise.all([
        contentApi.listDocs(topicId, { status, source }, token),
        contentApi.stats(topicId, token),
      ]);
      setDocs(docList);
      setStats(s);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [topicId, status, source, token]);

  useEffect(() => { refresh(); }, [refresh]);

  const reloadTopics = async () => {
    try {
      const list = await aiTelemetryApi.listTopics(token);
      setTopics(list);
    } catch {/* ignore */}
  };

  const openDoc = docs.find(d => d.id === openDocId) || null;
  const topicApproved = (currentTopic?.submission_status || 'draft') === 'approved';

  return (
    <div className="space-y-4">
      <PageHead titleKey="dashboard.nav.content" titleFallback="Content" />

      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-primary leading-tight">
            {t('dashboard.nav.content')}
          </h1>
          <p className="text-xs text-secondary mt-0.5">
            {t('dashboard.content.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={topicId ?? ''}
            onChange={(e) => { setTopicId(Number(e.target.value)); setOpenDocId(null); }}
            disabled={topics.length === 0}
            className="px-3 py-1.5 rounded-md text-sm min-w-[200px]"
            style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            {topics.length === 0 && <option value="">{t('dashboard.content.noTopic')}</option>}
            {topics.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
          <button
            type="button"
            disabled={!topicApproved}
            onClick={() => setShowSchedule(true)}
            className="text-xs px-3 py-1.5 rounded-md"
            style={{
              background: 'var(--bg-tertiary)',
              color: 'var(--accent-primary)',
              opacity: topicApproved ? 1 : 0.5,
            }}
          >
            ⏰ {t('dashboard.content.aiScheduleBtn')}
          </button>
          <button
            type="button"
            disabled={!topicApproved}
            onClick={() => setShowSubmit(true)}
            className="px-3 py-1.5 text-sm rounded-md text-white"
            style={{
              background: 'var(--accent-primary)',
              opacity: topicApproved ? 1 : 0.5,
            }}
          >
            + {t('dashboard.content.submitMyArticleBtn')}
          </button>
        </div>
      </header>

      {!topicApproved && currentTopic && (
        <div
          className="rounded-md p-2.5 text-xs"
          style={{
            background: 'rgba(234,179,8,0.1)',
            color: '#eab308',
            border: '1px solid rgba(234,179,8,0.3)',
          }}
        >
          {t('dashboard.content.topicNotApproved')}
        </div>
      )}

      {/* 统计卡 */}
      <StatsRow stats={stats} topic={currentTopic} t={t}
                onScheduleClick={() => setShowSchedule(true)} />

      {/* 筛选 */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted">{t('dashboard.content.filterStatusLabel')}</span>
          {STATUS_FILTERS.map(k => (
            <button
              key={k}
              type="button"
              onClick={() => setStatus(k)}
              className="px-2.5 py-1 rounded-full text-[11px]"
              style={{
                background: status === k ? 'var(--accent-primary)' : 'var(--bg-input)',
                color: status === k ? 'var(--solid-btn-text)' : 'var(--text-secondary)',
                border: '1px solid var(--border-color)',
              }}
            >
              {t(`dashboard.content.statusFilter.${k}`)}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 ml-2">
          <span className="text-xs text-muted">{t('dashboard.content.filterSourceLabel')}</span>
          {(['all', 'ai', 'user'] as SourceFilter[]).map(k => (
            <button
              key={k}
              type="button"
              onClick={() => setSource(k)}
              className="px-2.5 py-1 rounded-full text-[11px]"
              style={{
                background: source === k ? 'var(--accent-primary)' : 'var(--bg-input)',
                color: source === k ? 'var(--solid-btn-text)' : 'var(--text-secondary)',
                border: '1px solid var(--border-color)',
              }}
            >
              {t(`dashboard.content.sourceFilter.${k}`)}
            </button>
          ))}
        </div>
      </div>

      {err && (
        <div
          className="rounded-md p-3 text-sm"
          style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}
        >
          {err}
        </div>
      )}

      {loading && <div className="py-12 text-center text-sm text-muted">…</div>}

      {!loading && docs.length === 0 && (
        <div className="py-12 text-center text-sm text-muted">
          {t('dashboard.content.empty')}
        </div>
      )}

      <div className="space-y-2">
        {docs.map(d => (
          <DocCard key={d.id} doc={d} onOpen={() => setOpenDocId(d.id)} />
        ))}
      </div>

      {openDoc && (
        <DocDetailDrawer
          doc={openDoc}
          onClose={() => setOpenDocId(null)}
          onChanged={() => { refresh(); }}
        />
      )}

      {showSubmit && currentTopic && (
        <SubmitDrawer
          topic={currentTopic}
          onClose={() => setShowSubmit(false)}
          onSubmitted={() => { setShowSubmit(false); refresh(); }}
        />
      )}

      {showSchedule && currentTopic && (
        <AutoScheduleDrawer
          topic={currentTopic}
          onClose={() => setShowSchedule(false)}
          onSaved={() => { setShowSchedule(false); reloadTopics(); refresh(); }}
        />
      )}
    </div>
  );
}

// ─────────────────────────── 统计卡 ───────────────────────────

function StatsRow({
  stats, topic, t, onScheduleClick,
}: {
  stats: ContentStats | null; topic: Topic | null;
  t: (k: string, v?: Record<string, unknown>) => string;
  onScheduleClick: () => void;
}) {
  const cards = [
    { key: 'published', val: stats?.published ?? 0, color: '#3b82f6' },
    { key: 'pending_review', val: stats?.pending_review ?? 0, color: '#eab308' },
    { key: 'rejected', val: stats?.rejected ?? 0, color: '#ef4444' },
    { key: 'draft', val: stats?.draft ?? 0, color: '#94a3b8' },
  ] as const;
  const aiOn = !!topic?.auto_generate_enabled;
  const aiTime = topic?.auto_generate_time || '09:00';
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
      {cards.map(c => (
        <div
          key={c.key}
          className="rounded-md p-3"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
        >
          <div className="text-[11px] text-muted">
            {t(`dashboard.content.statsCard.${c.key}`)}
          </div>
          <div className="mt-1 text-xl font-semibold" style={{ color: c.color }}>
            {c.val}
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={onScheduleClick}
        className="rounded-md p-3 text-left"
        style={{ background: 'var(--bg-card)', border: '1px dashed var(--border-color)' }}
      >
        <div className="text-[11px] text-muted">
          {t('dashboard.content.statsCard.aiSchedule')}
        </div>
        <div className="mt-1 text-sm font-semibold text-primary">
          {aiOn
            ? t('dashboard.content.aiOnAtTime', { time: aiTime })
            : t('dashboard.content.aiOff')}
        </div>
      </button>
    </div>
  );
}

// ─────────────────────────── 列表卡 ───────────────────────────

function DocCard({ doc, onOpen }: { doc: ContentDoc; onOpen: () => void }) {
  const { t } = useTranslation();
  return (
    <article
      className="rounded-md p-3 cursor-pointer"
      onClick={onOpen}
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
    >
      <div className="flex items-start gap-2 flex-wrap">
        <h3 className="text-sm font-semibold text-primary flex-1 min-w-[200px]">
          {doc.title || `#${doc.id}`}
        </h3>
        <DocStatusChip status={doc.status} />
        <DocSourceChip source={doc.source} />
      </div>
      {doc.source_query_text && (
        <p className="text-[11px] text-muted mt-1">
          <span className="text-secondary">Q:</span> {doc.source_query_text}
        </p>
      )}
      {doc.summary && (
        <p className="text-xs text-secondary mt-1.5 line-clamp-2">{doc.summary}</p>
      )}
      {doc.reject_reason && (
        <p className="text-[11px] mt-1.5" style={{ color: '#ef4444' }}>
          ⚠ {t('dashboard.content.rejectReasonLabel')}:{doc.reject_reason}
        </p>
      )}
      <div className="mt-2 flex items-center gap-3 text-[11px] text-muted flex-wrap">
        <span>📅 {new Date(doc.created_at).toLocaleString()}</span>
        {doc.publish_targets.length > 0 && (
          <span className="inline-flex items-center gap-1">
            🌐 {doc.publish_targets.map((p, i) => (
              <span key={i} className="px-1.5 py-0.5 rounded"
                    style={{ background: 'rgba(59,130,246,0.12)', color: '#3b82f6' }}>
                {p.platform}{p.media ? `·${p.media}` : ''}
              </span>
            ))}
          </span>
        )}
      </div>
    </article>
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
    <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
          style={{ background: s.bg, color: s.c }}>
      {t(`dashboard.content.statusFilter.${status}`)}
    </span>
  );
}

function DocSourceChip({ source }: { source: DocSource }) {
  const { t } = useTranslation();
  const cm = source === 'ai'
    ? { c: '#8b5cf6', bg: 'rgba(139,92,246,0.15)' }
    : { c: '#06b6d4', bg: 'rgba(6,182,212,0.15)' };
  return (
    <span className="text-[10px] px-2 py-0.5 rounded-full"
          style={{ background: cm.bg, color: cm.c }}>
      {t(`dashboard.content.sourceFilter.${source}`)}
    </span>
  );
}

// ─────────────────────────── 详情抽屉 ─────────────────────────

function DocDetailDrawer({
  doc, onClose, onChanged,
}: {
  doc: ContentDoc;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(doc.title);
  const [body, setBody] = useState(doc.body_markdown);
  const [summary, setSummary] = useState(doc.summary);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canEdit = doc.source === 'user' && (doc.status === 'draft' || doc.status === 'rejected');
  const canSubmit = doc.status === 'draft' || doc.status === 'rejected';
  const canReview = doc.status === 'draft' || doc.status === 'pending_review';   // 用户自审

  const approve = async () => {
    setBusy(true); setErr(null);
    try {
      await contentApi.approveMyDoc(doc.id, token);
      onChanged(); onClose();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const reject = async () => {
    const reason = window.prompt('驳回原因(可留空):') ?? null;
    if (reason === null) return;
    setBusy(true); setErr(null);
    try {
      await contentApi.rejectMyDoc(doc.id, reason, token);
      onChanged(); onClose();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      await contentApi.updateMyDoc(doc.id, { title, body_markdown: body, summary }, token);
      setEditing(false);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const submitReview = async () => {
    setBusy(true); setErr(null);
    try {
      await contentApi.submitForReview(doc.id, token);
      onChanged();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div className="flex-1" />
      <div
        className="w-full md:w-[60%] max-w-3xl h-full overflow-y-auto"
        style={{ background: 'var(--bg-card)', borderLeft: '1px solid var(--border-color)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="sticky top-0 z-10 p-4 flex items-start justify-between gap-2 border-b"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-semibold text-primary">
                {doc.title || `#${doc.id}`}
              </h2>
              <DocStatusChip status={doc.status} />
              <DocSourceChip source={doc.source} />
            </div>
            <div className="text-xs text-muted mt-1">
              {doc.source_query_text && <span>Q: {doc.source_query_text} · </span>}
              <span>{new Date(doc.created_at).toLocaleString()}</span>
            </div>
          </div>
          <button type="button" onClick={onClose}
                  className="text-muted hover:text-primary text-xl leading-none">✕</button>
        </header>

        <div className="p-4 space-y-3">
          {err && <div className="text-xs" style={{ color: '#ef4444' }}>{err}</div>}

          {doc.reject_reason && (
            <div className="rounded-md p-2.5 text-xs"
                 style={{ background: 'rgba(239,68,68,0.05)', color: '#ef4444',
                          border: '1px solid rgba(239,68,68,0.3)' }}>
              {t('dashboard.content.rejectReasonLabel')}:{doc.reject_reason}
            </div>
          )}
          {doc.generation_error && (
            <div className="rounded-md p-2.5 text-xs"
                 style={{ background: 'rgba(239,68,68,0.05)', color: '#ef4444',
                          border: '1px solid rgba(239,68,68,0.3)' }}>
              {t('dashboard.content.generationErrorLabel')}:{doc.generation_error}
            </div>
          )}

          {!editing && (
            <article
              className="text-sm text-primary whitespace-pre-wrap leading-relaxed rounded-md p-3"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}
            >
              {doc.body_markdown || <span className="text-muted">{t('dashboard.content.emptyBody')}</span>}
            </article>
          )}

          {editing && (
            <div className="space-y-2">
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder={t('dashboard.content.submitTitlePh')}
                className="w-full text-sm px-3 py-2 rounded-md"
                style={{
                  background: 'var(--bg-input)', color: 'var(--text-primary)',
                  border: '1px solid var(--border-color)',
                }}
              />
              <textarea
                value={summary}
                onChange={e => setSummary(e.target.value)}
                rows={2}
                placeholder={t('dashboard.content.submitSummaryPh')}
                className="w-full text-sm px-3 py-2 rounded-md resize-none"
                style={{
                  background: 'var(--bg-input)', color: 'var(--text-primary)',
                  border: '1px solid var(--border-color)',
                }}
              />
              <textarea
                value={body}
                onChange={e => setBody(e.target.value)}
                rows={20}
                className="w-full text-sm px-3 py-2 rounded-md font-mono resize-none"
                style={{
                  background: 'var(--bg-surface)', color: 'var(--text-primary)',
                  border: '1px solid var(--border-color)',
                }}
              />
            </div>
          )}

          {doc.publish_targets.length > 0 && (
            <section>
              <p className="text-xs text-muted mb-1.5">{t('dashboard.content.publishedToLabel')}:</p>
              <div className="flex flex-wrap gap-1.5">
                {doc.publish_targets.map((p, i) => (
                  <span key={i}
                        className="text-[11px] px-2.5 py-1 rounded-full inline-flex items-center gap-1.5"
                        style={{ background: 'rgba(59,130,246,0.12)', color: '#3b82f6' }}>
                    {p.platform}{p.media ? ` / ${p.media}` : ''}
                    {p.url && (
                      <a
                        href={p.url} target="_blank" rel="noreferrer"
                        onClick={e => e.stopPropagation()}
                        className="underline opacity-80 hover:opacity-100"
                      >🔗</a>
                    )}
                    <span className="text-muted opacity-80">
                      {p.marked_at ? new Date(p.marked_at).toLocaleDateString() : ''}
                    </span>
                  </span>
                ))}
              </div>
            </section>
          )}
        </div>

        <footer
          className="sticky bottom-0 p-3 border-t flex justify-end gap-2 flex-wrap"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
        >
          {!editing && canEdit && (
            <button type="button" onClick={() => setEditing(true)}
                    className="text-xs px-3 py-1.5 rounded-md"
                    style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)',
                             border: '1px solid var(--border-color)' }}>
              {t('dashboard.content.editBtn')}
            </button>
          )}
          {editing && (
            <>
              <button type="button" disabled={busy}
                      onClick={() => {
                        setEditing(false);
                        setTitle(doc.title); setBody(doc.body_markdown); setSummary(doc.summary);
                      }}
                      className="text-xs px-3 py-1.5 rounded-md"
                      style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)' }}>
                {t('dashboard.content.cancelBtn')}
              </button>
              <button type="button" disabled={busy} onClick={save}
                      className="text-xs px-3 py-1.5 rounded-md text-white"
                      style={{ background: 'var(--accent-primary)', opacity: busy ? 0.5 : 1 }}>
                {busy ? '...' : t('dashboard.content.saveBtn')}
              </button>
            </>
          )}
          {!editing && canSubmit && (
            <button type="button" disabled={busy} onClick={submitReview}
                    className="text-xs px-3 py-1.5 rounded-md"
                    style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)', opacity: busy ? 0.5 : 1 }}>
              {t('dashboard.content.submitForReviewBtn')}
            </button>
          )}
          {!editing && canReview && (
            <>
              <button type="button" disabled={busy} onClick={reject}
                      className="text-xs px-3 py-1.5 rounded-md"
                      style={{ background: 'transparent', color: '#ef4444', border: '1px solid rgba(239,68,68,0.4)', opacity: busy ? 0.5 : 1 }}>
                驳回
              </button>
              <button type="button" disabled={busy} onClick={approve}
                      className="text-xs px-3 py-1.5 rounded-md text-white"
                      style={{ background: '#10b981', opacity: busy ? 0.5 : 1 }}>
                {busy ? '...' : '审核通过'}
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}

// ─────────────────────────── 提交抽屉 ─────────────────────────

function SubmitDrawer({
  topic, onClose, onSubmitted,
}: {
  topic: Topic;
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [summary, setSummary] = useState('');
  const [linkedQuery, setLinkedQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const selectedQueries = useMemo(() => {
    const out: string[] = [];
    (topic.queries || []).forEach((q, i) => {
      if ((topic.query_selected || [])[i] ?? true) out.push(q);
    });
    return out;
  }, [topic]);

  const submit = async (sendForReview: boolean) => {
    if (!title.trim() || !body.trim()) {
      setErr(t('dashboard.content.submitErrEmpty'));
      return;
    }
    setBusy(true); setErr(null);
    try {
      await contentApi.submitMyDoc(topic.id, {
        title: title.trim(),
        body_markdown: body,
        summary: summary.trim(),
        source_query_text: linkedQuery.trim(),
        submit_for_review: sendForReview,
      }, token);
      onSubmitted();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div className="flex-1" />
      <div
        className="w-full md:w-[60%] max-w-3xl h-full overflow-y-auto"
        style={{ background: 'var(--bg-card)', borderLeft: '1px solid var(--border-color)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="sticky top-0 z-10 p-4 flex items-center justify-between border-b"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
        >
          <h2 className="text-lg font-semibold text-primary">
            {t('dashboard.content.submitDrawerTitle')}
          </h2>
          <button type="button" onClick={onClose}
                  className="text-muted hover:text-primary text-xl leading-none">✕</button>
        </header>

        <div className="p-4 space-y-3">
          <p className="text-xs text-muted">{t('dashboard.content.submitDrawerHint')}</p>
          {err && <div className="text-xs" style={{ color: '#ef4444' }}>{err}</div>}

          <div>
            <label className="text-xs text-muted block mb-1">
              {t('dashboard.content.submitTopicLabel')}
            </label>
            <input
              type="text" value={topic.name} disabled
              className="w-full text-sm px-3 py-2 rounded-md opacity-70"
              style={{
                background: 'var(--bg-input)', color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
              }}
            />
          </div>

          <div>
            <label className="text-xs text-muted block mb-1">
              {t('dashboard.content.submitLinkedQueryLabel')}
            </label>
            <select
              value={linkedQuery}
              onChange={e => setLinkedQuery(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-md"
              style={{
                background: 'var(--bg-input)', color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
              }}
            >
              <option value="">{t('dashboard.content.submitLinkedQueryNone')}</option>
              {selectedQueries.map(q => (
                <option key={q} value={q}>{q}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-muted block mb-1">
              {t('dashboard.content.submitTitleLabel')}
            </label>
            <input
              type="text" value={title} onChange={e => setTitle(e.target.value)}
              placeholder={t('dashboard.content.submitTitlePh')}
              className="w-full text-sm px-3 py-2 rounded-md"
              style={{
                background: 'var(--bg-input)', color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
              }}
            />
          </div>

          <div>
            <label className="text-xs text-muted block mb-1">
              {t('dashboard.content.submitSummaryLabel')}
            </label>
            <textarea
              value={summary} onChange={e => setSummary(e.target.value)}
              rows={2} placeholder={t('dashboard.content.submitSummaryPh')}
              className="w-full text-sm px-3 py-2 rounded-md resize-none"
              style={{
                background: 'var(--bg-input)', color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
              }}
            />
          </div>

          <div>
            <label className="text-xs text-muted block mb-1">
              {t('dashboard.content.submitBodyLabel')}
            </label>
            <textarea
              value={body} onChange={e => setBody(e.target.value)}
              rows={18}
              placeholder={t('dashboard.content.submitBodyPh')}
              className="w-full text-sm px-3 py-2 rounded-md font-mono resize-none"
              style={{
                background: 'var(--bg-surface)', color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
              }}
            />
          </div>
        </div>

        <footer
          className="sticky bottom-0 p-3 border-t flex justify-end gap-2 flex-wrap"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
        >
          <button type="button" onClick={onClose}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)' }}>
            {t('dashboard.content.cancelBtn')}
          </button>
          <button type="button" disabled={busy} onClick={() => submit(false)}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                           opacity: busy ? 0.5 : 1 }}>
            {t('dashboard.content.saveDraftBtn')}
          </button>
          <button type="button" disabled={busy} onClick={() => submit(true)}
                  className="text-xs px-3 py-1.5 rounded-md text-white"
                  style={{ background: 'var(--accent-primary)', opacity: busy ? 0.5 : 1 }}>
            {busy ? '...' : t('dashboard.content.submitForReviewBtn')}
          </button>
        </footer>
      </div>
    </div>
  );
}

// ─────────────────────────── AI 排程抽屉 ──────────────────────

function AutoScheduleDrawer({
  topic, onClose, onSaved,
}: {
  topic: Topic;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';
  const [cfg, setCfg] = useState<AutoGenerateConfig>({
    enabled: !!topic.auto_generate_enabled,
    time: topic.auto_generate_time || '09:00',
    count: topic.auto_generate_count || 3,
    // 默认开:topic 没显式关过(undefined)就当开
    publish_enabled: topic.auto_publish_enabled !== false,
  });
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      await contentApi.configureAutoGenerate(topic.id, cfg, token);
      setMsg(t('dashboard.content.scheduleSaved'));
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const runNow = async () => {
    setRunning(true); setErr(null); setMsg(null);
    try {
      const r = await contentApi.runNow(topic.id, token);
      setMsg(t('dashboard.content.runNowQueued', { n: r.queued }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const seedCount = (topic.seed_prompts || []).length;
  const selectedCount = (topic.query_selected || []).filter(Boolean).length;
  const profile = topic.profile;
  const profileFilled = profile
    ? Object.values(profile).filter(v => (Array.isArray(v) ? v.length > 0 : !!v)).length
    : 0;

  return (
    <div
      className="fixed inset-0 z-50 flex"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div className="flex-1" />
      <div
        className="w-full md:w-[50%] max-w-2xl h-full overflow-y-auto"
        style={{ background: 'var(--bg-card)', borderLeft: '1px solid var(--border-color)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="sticky top-0 z-10 p-4 flex items-center justify-between border-b"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
        >
          <h2 className="text-lg font-semibold text-primary">
            {t('dashboard.content.scheduleDrawerTitle')}
          </h2>
          <button type="button" onClick={onClose}
                  className="text-muted hover:text-primary text-xl leading-none">✕</button>
        </header>

        <div className="p-4 space-y-4">
          <p className="text-xs text-muted">{t('dashboard.content.scheduleDrawerHint')}</p>
          {err && <div className="text-xs" style={{ color: '#ef4444' }}>{err}</div>}
          {msg && <div className="text-xs" style={{ color: '#10b981' }}>{msg}</div>}

          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox"
                   checked={cfg.enabled}
                   onChange={e => setCfg({ ...cfg, enabled: e.target.checked })}
                   style={{ accentColor: 'var(--accent-primary)' }} />
            <span className="text-sm text-primary">
              {t('dashboard.content.scheduleEnableLabel')}
            </span>
          </label>

          <div className="flex items-center gap-3 flex-wrap">
            <div>
              <label className="text-xs text-muted block mb-1">
                {t('dashboard.content.scheduleTimeLabel')}
              </label>
              <input type="time" value={cfg.time}
                     onChange={e => setCfg({ ...cfg, time: e.target.value })}
                     disabled={!cfg.enabled}
                     className="text-sm px-3 py-1.5 rounded-md"
                     style={{
                       background: 'var(--bg-input)', color: 'var(--text-primary)',
                       border: '1px solid var(--border-color)',
                       opacity: cfg.enabled ? 1 : 0.5,
                     }} />
            </div>
            <div>
              <label className="text-xs text-muted block mb-1">
                {t('dashboard.content.scheduleCountLabel')}
              </label>
              <input type="number" min={1} max={20} value={cfg.count}
                     onChange={e => setCfg({
                       ...cfg,
                       count: Math.max(1, Math.min(20, Number(e.target.value) || 1)),
                     })}
                     disabled={!cfg.enabled}
                     className="w-20 text-sm px-3 py-1.5 rounded-md"
                     style={{
                       background: 'var(--bg-input)', color: 'var(--text-primary)',
                       border: '1px solid var(--border-color)',
                       opacity: cfg.enabled ? 1 : 0.5,
                     }} />
            </div>
            <div className="text-xs text-muted self-end pb-1">
              {t('dashboard.content.scheduleTimeNote')}
            </div>
          </div>

          <div className="pt-1 border-t" style={{ borderColor: 'var(--border-color)' }}>
            <label className="flex items-center gap-2 cursor-pointer pt-3">
              <input type="checkbox"
                     checked={cfg.publish_enabled !== false}
                     onChange={e => setCfg({ ...cfg, publish_enabled: e.target.checked })}
                     style={{ accentColor: 'var(--accent-primary)' }} />
              <span className="text-sm text-primary">
                {t('dashboard.content.schedulePublishLabel')}
              </span>
            </label>
            <p className="text-xs text-muted mt-1 ml-6">
              {t('dashboard.content.schedulePublishHint')}
            </p>
          </div>

          <div className="rounded-md p-3 space-y-2"
               style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
            <p className="text-xs font-semibold text-secondary uppercase tracking-wide">
              {t('dashboard.content.scheduleSourcesTitle')}
            </p>
            <div className="text-xs text-secondary flex justify-between">
              <span>{t('dashboard.content.scheduleProfile')}</span>
              <span>{profileFilled} {t('dashboard.content.scheduleFields')}</span>
            </div>
            <div className="text-xs text-secondary flex justify-between">
              <span>{t('dashboard.content.scheduleSeeds')}</span>
              <span>{seedCount}</span>
            </div>
            <div className="text-xs text-secondary flex justify-between">
              <span>{t('dashboard.content.scheduleMonitored')}</span>
              <span>{selectedCount}</span>
            </div>
            {topic.auto_generate_last_run_at && (
              <div className="text-xs text-muted pt-1 border-t mt-2"
                   style={{ borderColor: 'var(--border-color)' }}>
                {t('dashboard.content.scheduleLastRunAt')}:
                {' '}
                {new Date(topic.auto_generate_last_run_at).toLocaleString()}
              </div>
            )}
          </div>
        </div>

        <footer
          className="sticky bottom-0 p-3 border-t flex justify-end gap-2 flex-wrap"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
        >
          <button type="button" onClick={onClose}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)' }}>
            {t('dashboard.content.cancelBtn')}
          </button>
          <button type="button" disabled={running} onClick={runNow}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'var(--bg-tertiary)', color: 'var(--accent-primary)',
                           opacity: running ? 0.5 : 1 }}>
            {running ? '...' : t('dashboard.content.runNowBtn')}
          </button>
          <button type="button" disabled={busy} onClick={save}
                  className="text-xs px-3 py-1.5 rounded-md text-white"
                  style={{ background: 'var(--accent-primary)', opacity: busy ? 0.5 : 1 }}>
            {busy ? '...' : t('dashboard.content.saveBtn')}
          </button>
        </footer>
      </div>
    </div>
  );
}
