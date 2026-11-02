// Admin 执行计划书 — 编辑发文表(draft / 插入式编辑) / 查看(confirmed).
// 路由:/workbench/topics/:topicId/execution-plan

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import { TopicStepper } from '../../components/TopicStepper';
import { adminReviewApi, type ExecutionPlan } from '../../services/adminReviewApi';
import { PublishingPlanEditor } from './PublishingPlanEditor';

export function AdminExecutionPlan() {
  const { topicId } = useParams();
  const tid = Number(topicId);
  return (
    <div className="space-y-4">
      <PageHead titleKey="admin.executionPlan.title" titleFallback="执行计划书" />
      <TopicStepper topicId={tid} active="plan" />
      <ExecutionPlanView topicId={tid} />
    </div>
  );
}

// 嵌入版:无 PageHead / TopicStepper,只渲染计划书主体内容.
// 用于 TopicEditor 7 步 wizard 的第 5 步内联展示.
export function ExecutionPlanView({ topicId }: { topicId: number }) {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';
  const [plan, setPlan] = useState<ExecutionPlan | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // 项目还没启动 = backend 404 "no execution plan generated".用专门的空态展示 + 启动按钮,
  // 不要把后端英文 raw 错误甩到红 banner 上.
  const [notStarted, setNotStarted] = useState(false);
  const [rerunBusy, setRerunBusy] = useState(false);
  const [regenBusy, setRegenBusy] = useState(false);
  const [startBusy, setStartBusy] = useState(false);
  const [inlineEdit, setInlineEdit] = useState(false);  // confirmed 态下的「编辑发文表」开关
  const pollRef = useRef<number | null>(null);

  const needsPolling = (p: ExecutionPlan): boolean => {
    if (p.run_status === 'running') return true;
    // confirmed 状态:有文章还没生成完(plan_item 没出稿)就继续轮
    if (p.status === 'confirmed') {
      const pending = (p.publishing_plan || []).some(
        it => !it.doc_id || it.doc_status === 'draft',
      );
      if (pending) return true;
    }
    return false;
  };

  const fetchOnce = useCallback(async () => {
    if (!topicId) return;
    try {
      const p = await adminReviewApi.getExecutionPlan(topicId, token);
      setPlan(p);
      setNotStarted(false);
      setErr(null);
      if (!needsPolling(p)) {
        if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      // 404 / 后端 "no execution plan" → 项目还没启动,不算错误,渲染空态.
      if (/no execution plan/i.test(msg)) {
        setNotStarted(true);
        setErr(null);
      } else {
        setErr(msg);
      }
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
    }
  }, [topicId, token]);

  useEffect(() => {
    fetchOnce();
    pollRef.current = window.setInterval(fetchOnce, 3000);
    return () => {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [fetchOnce]);

  const handleStart = async () => {
    if (startBusy) return;
    setStartBusy(true); setErr(null);
    try {
      await adminReviewApi.startTopic(topicId, token);
      // 启动后立刻重拉一次;后端异步生成 plan,polling 接管后续刷新.
      setNotStarted(false);
      await fetchOnce();
      if (!pollRef.current) {
        pollRef.current = window.setInterval(fetchOnce, 3000);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setStartBusy(false);
    }
  };

  const editMode = plan?.status === 'draft' || inlineEdit;

  return (
    <div className="space-y-4">
      {plan && (
        <div className="flex justify-end">
          {/* 重新生成计划书 — topic 改了种子词/扩展词后,把快照按当前状态重建;发文表不动 */}
          <button type="button" disabled={regenBusy}
                  onClick={async () => {
                    if (regenBusy) return;
                    if (!window.confirm(t('admin.executionPlan.regenConfirm'))) return;
                    setRegenBusy(true); setErr(null);
                    try {
                      const p = await adminReviewApi.regenerateExecutionPlan(topicId, token);
                      setPlan(p);
                    } catch (e: unknown) {
                      setErr(e instanceof Error ? e.message : String(e));
                    } finally {
                      setRegenBusy(false);
                    }
                  }}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                           border: '1px solid var(--border-color)', opacity: regenBusy ? 0.5 : 1 }}>
            {regenBusy ? '…' : t('admin.executionPlan.regenSnapshot')}
          </button>
        </div>
      )}
      {plan && (plan.status === 'failed' || !plan.run_id) && (
        <div className="flex justify-end">
          <button type="button" disabled={rerunBusy}
                  onClick={async () => {
                    if (rerunBusy) return;
                    setRerunBusy(true); setErr(null);
                    try {
                      const p = await adminReviewApi.rerunTopic(topicId, token);
                      setPlan(p);
                      if (!pollRef.current) {
                        pollRef.current = window.setInterval(fetchOnce, 3000);
                      }
                    } catch (e: unknown) {
                      setErr(e instanceof Error ? e.message : String(e));
                    } finally {
                      setRerunBusy(false);
                    }
                  }}
                  className="text-xs px-3 py-1.5 rounded-md text-white"
                  style={{ background: 'var(--accent-primary)', opacity: rerunBusy ? 0.5 : 1 }}>
            {rerunBusy ? '…' : t('admin.executionPlan.rerun')}
          </button>
        </div>
      )}

      {err && (
        <div className="rounded-md p-3 text-sm"
             style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                      border: '1px solid rgba(239,68,68,0.3)' }}>
          {err}
        </div>
      )}

      {notStarted && (
        <div className="rounded-md p-6 text-center space-y-3"
             style={{ background: 'var(--bg-secondary)',
                      border: '1px dashed var(--border-color)' }}>
          <div className="text-sm text-secondary">
            项目尚未启动 — 启动后会自动生成执行计划书与发文表
          </div>
          <button type="button" disabled={startBusy} onClick={handleStart}
                  className="px-4 py-1.5 text-sm rounded-md text-white disabled:opacity-50"
                  style={{ background: 'var(--accent-primary)' }}>
            {startBusy ? '启动中…' : '⚡ 启动项目'}
          </button>
        </div>
      )}

      {!plan && !err && !notStarted && (
        <div className="py-12 text-center text-sm text-muted">…</div>
      )}

      {plan && (
        <div className="space-y-4">
          <OverviewSection plan={plan}
                           inlineEditToggle={
                             plan.status === 'confirmed' && !inlineEdit
                               ? () => setInlineEdit(true) : undefined
                           } />
          <ProgressSection plan={plan} />
          {editMode ? (
            <SectionCard title={plan.status === 'draft' ? '编辑发文计划(草稿)' : '编辑发文计划'}>
              <PublishingPlanEditor
                plan={plan}
                topicId={topicId}
                mode={plan.status === 'draft' ? 'draft' : 'inline-edit'}
                onSaved={(updated) => {
                  setPlan(updated);
                  // confirmed 态下保存修改后退出编辑
                  if (updated.status !== 'draft') setInlineEdit(false);
                }}
                onConfirmed={(updated) => {
                  setPlan(updated);
                  setInlineEdit(false);
                  if (!pollRef.current) {
                    pollRef.current = window.setInterval(fetchOnce, 3000);
                  }
                }}
                onCancel={plan.status !== 'draft' ? () => setInlineEdit(false) : undefined}
              />
            </SectionCard>
          ) : (
            <PublishingPlanSection plan={plan}
                                   onRegenerate={async (itemId) => {
                                     try {
                                       const p = await adminReviewApi.regeneratePlanItem(topicId, itemId, token);
                                       setPlan(p);
                                       if (!pollRef.current) {
                                         pollRef.current = window.setInterval(fetchOnce, 3000);
                                       }
                                     } catch (e: unknown) {
                                       setErr(e instanceof Error ? e.message : String(e));
                                     }
                                   }} />
          )}
          <ChangelogSection plan={plan} />
          <ExpansionSection plan={plan} />
        </div>
      )}
    </div>
  );
}

function OverviewSection({
  plan, inlineEditToggle,
}: {
  plan: ExecutionPlan;
  inlineEditToggle?: () => void;
}) {
  const { t } = useTranslation();
  const o = plan.overview || {};
  const planDocs = plan.publishing_plan || [];
  const docDone = planDocs.filter(it => it.doc_id && it.doc_status && it.doc_status !== 'draft').length;
  const docTotal = planDocs.length;
  const planStatusLabel: Record<string, { text: string; color: string }> = {
    draft:     { text: '草稿(待确认)', color: '#3b82f6' },
    confirmed: { text: '已确认',         color: '#10b981' },
    failed:    { text: '失败',           color: '#ef4444' },
    ready:     { text: '已确认',         color: '#10b981' }, // 兼容旧值
    generating:{ text: '草稿(待确认)', color: '#3b82f6' },
  };
  const ps = planStatusLabel[plan.status] || { text: plan.status, color: '#94a3b8' };
  const rows: [string, unknown][] = [
    ['项目名称', o.topic_name],
    ['品牌简称', o.company_short_name],
    ['行业', o.industry],
    ['服务地域', o.service_geo],
    ['监测问题数', o.monitored_queries_count],
    ['引擎', Array.isArray(o.engines) ? (o.engines as string[]).join(', ') : ''],
    ['预估 cell 数', o.estimated_cells],
    ['计划生成时间', plan.generated_at && new Date(plan.generated_at).toLocaleString()],
    ['确认时间', plan.confirmed_at && new Date(plan.confirmed_at).toLocaleString()],
    ['通过触发的 run_id', plan.run_id || '—'],
  ];
  return (
    <SectionCard title={t('admin.executionPlan.section.overview')}>
      <div className="flex items-center gap-3 mb-3 text-sm">
        <span className="text-muted">计划状态:</span>
        <span className="font-semibold" style={{ color: ps.color }}>{ps.text}</span>
        {docTotal > 0 && (
          <>
            <span className="text-muted">·</span>
            <span className="text-secondary">
              文章 {docDone} / {docTotal}
            </span>
          </>
        )}
        <div className="flex-1" />
        {inlineEditToggle && (
          <button type="button" onClick={inlineEditToggle}
                  className="text-xs px-2.5 py-1 rounded-md"
                  style={{ background: 'transparent', color: 'var(--text-secondary)',
                           border: '1px solid var(--border-color)' }}>
            ✎ 编辑发文表
          </button>
        )}
      </div>
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
        {rows.filter(([_, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => (
          <div key={k} className="flex items-start gap-2">
            <dt className="text-muted shrink-0 min-w-[100px]">{k}:</dt>
            <dd className="text-primary break-words">{String(v)}</dd>
          </div>
        ))}
      </dl>
    </SectionCard>
  );
}

function ChangelogSection({ plan }: { plan: ExecutionPlan }) {
  const { t } = useTranslation();
  return (
    <SectionCard title={t('admin.executionPlan.section.changelog', { n: plan.topic_changelog.length })}>
      {plan.topic_changelog.length === 0 && (
        <div className="text-xs text-muted">—</div>
      )}
      <ul className="text-xs space-y-1 max-h-60 overflow-auto">
        {[...plan.topic_changelog].reverse().map((e, i) => (
          <li key={i} className="text-secondary">
            <span className="text-muted">{new Date(e.at).toLocaleString()}</span>
            <span className="mx-1">·</span>
            <span style={{ color: e.actor_role === 'admin' ? '#ef4444' : '#10b981' }}>{e.actor_role}</span>
            <span className="mx-1">·</span>
            <span>{e.field}</span>
            {e.after && <span className="text-primary ml-1">→ {e.after}</span>}
            {e.note && <span className="text-muted ml-1">({e.note})</span>}
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

function ExpansionSection({ plan }: { plan: ExecutionPlan }) {
  const { t } = useTranslation();
  return (
    <SectionCard title={t('admin.executionPlan.section.expansion', { n: plan.expansion_log.length })}>
      {plan.expansion_log.length === 0 && <div className="text-xs text-muted">—</div>}
      <ul className="text-xs space-y-2 max-h-60 overflow-auto">
        {[...plan.expansion_log].reverse().map((e, i) => (
          <li key={i} className="text-secondary border-l pl-2"
              style={{ borderColor: 'var(--border-color)' }}>
            <div>
              <span className="text-muted">{new Date(e.at).toLocaleString()}</span>
              <span className="mx-1">·</span>
              <span className="text-primary">种子:{e.seed}</span>
              <span className="mx-1">·</span>
              <span>{e.model}</span>
              <span className="mx-1">·</span>
              <span>+{e.expanded_count} 条</span>
            </div>
            {e.raw_excerpt && (
              <div className="text-muted truncate mt-0.5">{e.raw_excerpt}</div>
            )}
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

function ProgressSection({ plan }: { plan: ExecutionPlan }) {
  const { t } = useTranslation();
  const pct = plan.progress_total > 0
    ? Math.round(plan.progress_done / plan.progress_total * 100)
    : 0;
  return (
    <SectionCard title={t('admin.executionPlan.section.progress')}>
      <div className="space-y-2">
        <div className="flex items-center gap-3 text-xs">
          <div className="flex-1 h-2 rounded-full overflow-hidden"
               style={{ background: 'var(--bg-tertiary)' }}>
            <div className="h-full transition-all"
                 style={{ width: `${pct}%`, background: 'var(--accent-primary)' }} />
          </div>
          <div className="text-muted shrink-0">
            {plan.progress_done}/{plan.progress_total} ({pct}%)
          </div>
        </div>
        <div className="text-xs text-secondary">
          run #{plan.run_id || '—'} · status:
          <span className="ml-1"
                style={{ color: plan.run_status === 'success' ? '#10b981'
                       : plan.run_status === 'failed' ? '#ef4444'
                       : plan.run_status === 'running' ? '#eab308' : '#94a3b8' }}>
            {plan.run_status || 'unknown'}
          </span>
        </div>
        {plan.progress.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5 mt-2 max-h-80 overflow-auto">
            {plan.progress.map((c, i) => (
              <div key={i} className="rounded-md p-1.5 text-[11px]"
                   style={{
                     background: c.status === 'done' ? 'rgba(16,185,129,0.10)'
                               : c.status === 'running' ? 'rgba(234,179,8,0.10)'
                               : 'var(--bg-card)',
                     border: '1px solid var(--border-color)',
                   }}>
                <div className="font-semibold truncate" style={{
                  color: c.status === 'done' ? '#10b981'
                       : c.status === 'running' ? '#eab308' : 'var(--text-secondary)',
                }}>
                  {c.engine}
                  {c.hit === true && <span className="ml-1">✓</span>}
                </div>
                <div className="text-muted truncate" title={c.query}>{c.query}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function PublishingPlanSection({
  plan, onRegenerate,
}: {
  plan: ExecutionPlan;
  onRegenerate?: (itemId: string) => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const items = plan.publishing_plan || [];
  if (items.length === 0) {
    return null;
  }
  const canRegenerate = plan.status === 'confirmed' && onRegenerate !== undefined;
  const PRI_STYLE: Record<string, { c: string; bg: string; label: string }> = {
    high: { c: '#ef4444', bg: 'rgba(239,68,68,0.10)', label: t('admin.executionPlan.priority.high') },
    med:  { c: '#eab308', bg: 'rgba(234,179,8,0.10)', label: t('admin.executionPlan.priority.med') },
    low:  { c: '#10b981', bg: 'rgba(16,185,129,0.10)', label: t('admin.executionPlan.priority.low') },
  };
  const DOC_STATUS_LABEL: Record<string, string> = {
    draft: t('admin.executionPlan.docStatus.draft'),
    pending_review: t('admin.executionPlan.docStatus.pending_review'),
    approved: t('admin.executionPlan.docStatus.approved'),
    rejected: t('admin.executionPlan.docStatus.rejected'),
    published: t('admin.executionPlan.docStatus.published'),
  };
  return (
    <SectionCard title={t('admin.executionPlan.section.publishingPlan', { n: items.length })}>
      <p className="text-xs text-muted mb-3">
        {t('admin.executionPlan.publishingPlanHint')}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left" style={{ color: 'var(--text-muted)' }}>
              <th className="py-2 px-2 font-medium">{t('admin.executionPlan.col.date')}</th>
              <th className="py-2 px-2 font-medium">主题(种子 / query)</th>
              <th className="py-2 px-2 font-medium text-center">{t('admin.executionPlan.col.coverage')}</th>
              <th className="py-2 px-2 font-medium text-center">{t('admin.executionPlan.col.priority')}</th>
              <th className="py-2 px-2 font-medium">模板/平台</th>
              <th className="py-2 px-2 font-medium">{t('admin.executionPlan.col.doc')}</th>
              {canRegenerate && <th className="py-2 px-2 font-medium text-center">操作</th>}
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => {
              const pri = PRI_STYLE[it.priority] || PRI_STYLE.med;
              return (
                <tr key={it.id || i}
                    style={{ borderTop: '1px solid var(--border-color)' }}>
                  <td className="py-2 px-2 tabular-nums text-primary whitespace-nowrap cursor-pointer"
                      onClick={() => navigate(`/workbench/topics/${plan.topic_id}/edit?step=6`)}>
                    {it.publish_date}
                    <span className="text-muted ml-1">(#{it.seq + 1})</span>
                  </td>
                  <td className="py-2 px-2 max-w-[280px] cursor-pointer"
                      title={[it.seed, ...(it.queries?.length ? it.queries : [it.query])]
                        .filter(Boolean).join('\n')}
                      onClick={() => navigate(`/workbench/topics/${plan.topic_id}/edit?step=6`)}>
                    {it.seed ? (
                      <div className="truncate">
                        <span className="text-primary">{it.seed}</span>
                        <span className="text-[10px] text-muted ml-1">种子</span>
                      </div>
                    ) : (
                      <div className="truncate">
                        <span className="text-primary">
                          {(it.queries?.length ? it.queries[0] : it.query)}
                        </span>
                      </div>
                    )}
                    {/* 多选监测问题:种子行/单 query 行都可能挂一组,展示条数角标 */}
                    {(it.queries?.length ?? 0) > (it.seed ? 0 : 1) && (
                      <div className="text-[10px] text-muted truncate">
                        覆盖 {it.queries!.length} 条监测问题
                      </div>
                    )}
                  </td>
                  <td className="py-2 px-2 text-center tabular-nums">
                    <span style={{ color: it.coverage_pct === 0 ? '#ef4444'
                                       : it.coverage_pct < 50 ? '#eab308' : '#10b981' }}>
                      {it.coverage_pct.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-2 px-2 text-center">
                    <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold"
                          style={{ background: pri.bg, color: pri.c }}>
                      {pri.label}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-[10px]">
                    {it.template_name && (
                      <span className="block text-primary">{it.template_name}</span>
                    )}
                    {it.platform && (
                      <span className="inline-block px-1.5 py-0.5 rounded-full"
                            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>
                        {it.platform}
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-2">
                    {it.doc_id ? (
                      <span className="text-[10px] cursor-pointer"
                            onClick={() => navigate(`/workbench/topics/${plan.topic_id}/edit?step=6`)}>
                        #{it.doc_id}
                        {it.doc_status && (
                          <span className="ml-1 text-muted">
                            ({DOC_STATUS_LABEL[it.doc_status] || it.doc_status})
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-muted text-[10px]">
                        {t('admin.executionPlan.docStatus.notGenerated')}
                      </span>
                    )}
                  </td>
                  {canRegenerate && (
                    <td className="py-2 px-2 text-center">
                      <button type="button"
                              onClick={() => onRegenerate?.(it.id)}
                              className="text-[10px] px-2 py-0.5 rounded-md"
                              style={{ background: 'transparent', color: 'var(--text-secondary)',
                                       border: '1px solid var(--border-color)' }}
                              title="重新生成这条">
                        ↻ 重生
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md p-4"
             style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <h2 className="text-sm font-semibold text-primary mb-3">{title}</h2>
      {children}
    </section>
  );
}
