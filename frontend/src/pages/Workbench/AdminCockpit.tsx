// 项目进度 — admin 主入口,一屏看完每个主题在 GEO 管线上的进度.
// 路由:/workbench/cockpit (workbench 默认页)
// 不按 pipeline stage 让 admin 一步步点 sidebar,而是把所有主题铺开 + 每个 stage 用 chip
// 显示状态(完成 / 进行中 / 待处理 / 异常 / 未启动),admin 直接点 chip 跳详情页.

import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import { adminReviewApi, type StageState, type TopicReviewListItem } from '../../services/adminReviewApi';
import { authApi } from '../../services/authApi';

type StageKey = 'submit' | 'review' | 'solution' | 'plan' | 'content' | 'insight';

const STAGE_ORDER: StageKey[] = ['submit', 'review', 'solution', 'plan', 'content', 'insight'];

const STATE_COLOR: Record<StageState, { c: string; bg: string; border: string }> = {
  done: { c: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.35)' },
  running: { c: '#3b82f6', bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.35)' },
  pending: { c: '#eab308', bg: 'rgba(234,179,8,0.12)', border: 'rgba(234,179,8,0.35)' },
  blocked: { c: '#ef4444', bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.35)' },
  idle: { c: '#94a3b8', bg: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.30)' },
};

function deriveStages(t: TopicReviewListItem): Record<StageKey, { state: StageState; to: string }> {
  const tid = t.topic_id;
  const sub = t.submission_status;
  // stage 1 submit:有 topic 就算 done.
  // stage 2 review:由 submission_status 推.
  // stage 3-6:后端 admin_review.py 已经按各自表的状态算好(idle/running/done/blocked/pending),
  //           前端直接读字段;后端缺字段时 Pydantic 会回退到 'idle'.
  const reviewRaw: StageState =
    sub === 'approved' ? 'done' :
      sub === 'rejected' ? 'blocked' :
        sub === 'pending' ? 'pending' : 'idle';

  // 工作流式管线 — backward infer:任意 stage 状态非 idle(done / running /
  // pending / blocked),意味着上游早已发生过,即便上游 DB 行缺失.把上游的
  // idle 推升为 done,避免「下游已完成、上游仍未启动」的错位.
  //
  // 这条规则替代了原来的「forward 门禁」(上游非 done → 下游强制 idle).
  // forward 门禁在老数据/缺失行场景下会把真实完成的下游硬塞成 idle —
  // 例如 程晓峰 topic_id=2:plan 行未生成、但 content 70 篇已 published、
  // telemetry success,plan 的「样本缺失」不应该把 content 拖成未启动.
  const rawByKey: Record<StageKey, StageState> = {
    submit: 'done',
    review: reviewRaw,
    solution: t.diagnose_status,
    plan: t.plan_status,
    content: t.content_status,
    insight: t.insight_status,
  };
  const effective: Record<StageKey, StageState> = { ...rawByKey };
  let downstreamProgressed = false;
  for (let i = STAGE_ORDER.length - 1; i >= 0; i--) {
    const key = STAGE_ORDER[i];
    if (downstreamProgressed && effective[key] === 'idle') {
      effective[key] = 'done';
    }
    if (effective[key] !== 'idle') downstreamProgressed = true;
  }
  // Forward gate:效果查验依赖内容已发布 — 没发布就没效果可查.
  // 后端 _insight_state 用 last_run_status === 'success' 直接判 done,会让 batch 跑完
  // 但文稿还在审/没 published 时出现「6 已完成 5 没完成」的视觉错乱.
  // 这里把 content !== done 时的 insight done 强制降到 running(等内容发布).
  if (effective.content !== 'done' && effective.insight === 'done') {
    effective.insight = 'running';
  }
  // 用户偏好:项目进度看板不展示「异常」(red),blocked 一律按「进行中」(blue)呈现.
  // 真实失败状态查 stage 详情页(执行计划 / 审核 / 监测各页都会还原 raw status).
  for (const key of STAGE_ORDER) {
    if (effective[key] === 'blocked') effective[key] = 'running';
  }

  // 全部 6 段 chip 都指向「画像」主流程的对应 step,只保留这一个主流程.
  //   submit (品牌与主题创建)   → step 1 设置 / 资料
  //   review (诊断与方案预评估) → step 3 监测问题(种子 + queries 全景)
  //   solution (GEO策略优化方案) → step 4 健康诊断报告
  //   plan (执行策略与规划)     → step 5 计划书(inline)
  //   content (内容发布与审核)  → step 6 文案复审(inline)
  //   insight (效果查验与更新)  → step 7 监测反哺(inline)
  const base = `/workbench/topics/${tid}/edit`;
  return {
    submit: { state: effective.submit, to: `${base}?step=1` },
    review: { state: effective.review, to: `${base}?step=3` },
    solution: { state: effective.solution, to: `${base}?step=4` },
    plan: { state: effective.plan, to: `${base}?step=5` },
    content: { state: effective.content, to: `${base}?step=6` },
    insight: { state: effective.insight, to: `${base}?step=7` },
  };
}

export function AdminCockpit() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const token = localStorage.getItem('token') || '';
  const [topics, setTopics] = useState<TopicReviewListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // 「新建项目」入口:与「画像」页 (AdminAccounts.tsx) 同一套创建账号弹窗,成功后
  // 跳到 /workbench/accounts/{id}/topics?new=1,AdminAccountTopics 会自动打开新建主题编辑器.
  const [modalOpen, setModalOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  useEffect(() => {
    adminReviewApi.listTopicReviews(token)
      .then(setTopics)
      .catch(e => setErr(e?.message || 'failed'))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    if (!modalOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) setModalOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener('keydown', onKey);
    };
  }, [modalOpen, submitting]);

  const openModal = () => {
    setEmail(''); setPassword(''); setName(''); setFormErr(null);
    setModalOpen(true);
  };
  const closeModal = () => {
    if (submitting) return;
    setModalOpen(false);
  };
  const handleCreate = async () => {
    setFormErr(null);
    const e = email.trim().toLowerCase();
    const p = password;
    const n = name.trim();
    if (!e) { setFormErr(t('workbench.adminAccounts.createForm.emailRequired')); return; }
    if (p.length < 6) { setFormErr(t('workbench.adminAccounts.createForm.passwordTooShort')); return; }
    setSubmitting(true);
    try {
      const u = await authApi.register(e, p, n || undefined);
      setModalOpen(false);
      navigate(`/workbench/accounts/${u.id}/topics?new=1`);
    } catch (ex: unknown) {
      setFormErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSubmitting(false);
    }
  };

  const rows = useMemo(
    () => topics.map(tp => ({ topic: tp, stages: deriveStages(tp) })),
    [topics],
  );

  // 待办计数(去审核流):
  //   - 未启动 = approved 但 plan 为 idle(admin 直建后未点「启动」)
  //   - 跑批待处理 = plan_status === 'blocked' (run failed) 或 'pending'
  //   - 待复审文案 = content_status === 'pending'
  const todoCounts = useMemo(() => {
    let notStarted = 0, runStuck = 0, docPending = 0;
    for (const tp of topics) {
      if (tp.submission_status === 'approved' && tp.plan_status === 'idle') notStarted++;
      if (tp.plan_status === 'blocked' || tp.plan_status === 'pending') runStuck++;
      if (tp.content_status === 'pending') docPending++;
    }
    return { notStarted, runStuck, docPending };
  }, [topics]);

  return (
    <div className="space-y-4">
      <PageHead titleKey="workbench.adminCockpit.title" titleFallback="项目进度" />
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-primary">
            {t('workbench.adminCockpit.heading')}
          </h1>
          <p className="text-xs text-secondary mt-0.5">
            {t('workbench.adminCockpit.subtitle')}
          </p>
        </div>
        <button type="button" onClick={openModal}
                className="text-xs px-3 py-1.5 rounded-md text-white whitespace-nowrap"
                style={{ background: 'var(--accent-primary)' }}>
          + {t('workbench.adminCockpit.newProject')}
        </button>
      </header>

      {/* 待办区:3 张计数卡 — 点击跳到对应列表(带过滤) */}
      {!loading && !err && topics.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <TodoCard count={todoCounts.notStarted}
                    label={t('workbench.adminCockpit.todo.notStarted')}
                    color="#3b82f6"
                    to="/workbench/accounts" />
          <TodoCard count={todoCounts.runStuck}
                    label={t('workbench.adminCockpit.todo.runStuck')}
                    color="#eab308"
                    to="/workbench/accounts" />
          <TodoCard count={todoCounts.docPending}
                    label={t('workbench.adminCockpit.todo.docPending')}
                    color="#10b981"
                    to="/workbench/content-review?status=pending_review" />
        </div>
      )}

      {loading ? (
        <div className="text-xs text-muted text-center py-10">{t('common.loading')}</div>
      ) : err ? (
        <div className="text-xs text-red-500">{err}</div>
      ) : rows.length === 0 ? (
        <div className="text-xs text-muted text-center py-10">
          {t('workbench.adminCockpit.empty')}
        </div>
      ) : (
        <div className="rounded-lg overflow-hidden"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted">
                <th className="text-left px-3 py-2 whitespace-nowrap">{t('workbench.adminCockpit.colTopic')}</th>
                <th className="text-left px-3 py-2 whitespace-nowrap">{t('workbench.adminCockpit.colCustomer')}</th>
                {STAGE_ORDER.map((s, i) => (
                  <th key={s} className="px-2 py-2 text-center whitespace-nowrap">
                    <span className="text-muted">{i + 1}.</span>{' '}
                    {t(`workbench.adminCockpit.stage.${s}`)}
                  </th>
                ))}
                <th className="px-2 py-2 text-center whitespace-nowrap">
                  {t('workbench.adminCockpit.colGrowth')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ topic, stages }) => (
                <tr key={topic.topic_id} className="border-t"
                  style={{ borderColor: 'var(--border-color)' }}>
                  <td className="px-3 py-2 text-primary">
                    {topic.profile_name || topic.topic_name}
                    <div className="text-[10px] text-muted">#{topic.topic_id}</div>
                  </td>
                  <td className="px-3 py-2 text-secondary">
                    {topic.user_email}
                  </td>
                  {STAGE_ORDER.map(key => {
                    const { state, to } = stages[key];
                    const c = STATE_COLOR[state];
                    return (
                      <td key={key} className="px-2 py-2 text-center">
                        <Link to={to}
                          className="inline-block px-2 py-0.5 rounded-md text-[11px] border transition-colors"
                          style={{ color: c.c, background: c.bg, borderColor: c.border }}>
                          {t(`workbench.adminCockpit.stageStatus.${state}`)}
                        </Link>
                      </td>
                    );
                  })}
                  {/* 客户视角品牌增长面板入口 — admin 直接看客户看到的那个 /brand-growth */}
                  <td className="px-2 py-2 text-center">
                    <Link to={`/brand-growth?topic=${topic.topic_id}`}
                      className="inline-block px-2 py-0.5 rounded-md text-[11px] border transition-colors hover:opacity-80"
                      style={{ color: 'var(--accent-primary)', borderColor: 'var(--accent-primary)' }}>
                      {t('workbench.adminCockpit.viewGrowth')}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 「新建项目」弹窗 — 与「画像」AdminAccounts.tsx 同源,复用同一套 i18n 字典. */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)' }}
             onClick={closeModal}>
          <div className="w-full max-w-md rounded-xl p-5 shadow-2xl"
               style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 mb-4">
              <h2 className="text-base font-semibold text-primary">
                {t('workbench.adminAccounts.createForm.title')}
              </h2>
              <button type="button" onClick={closeModal} disabled={submitting}
                      className="text-muted hover:text-primary text-lg leading-none"
                      aria-label="close">×</button>
            </div>
            <div className="space-y-3">
              <label className="block text-xs text-secondary">
                <span className="block mb-1">
                  {t('workbench.adminAccounts.createForm.emailLabel')} *
                </span>
                <input type="email" autoFocus autoComplete="off" value={email}
                       onChange={e => setEmail(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                       placeholder={t('workbench.adminAccounts.createForm.emailPlaceholder')}
                       className="w-full px-2 py-1.5 rounded-md text-xs text-primary"
                       style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }} />
              </label>
              <label className="block text-xs text-secondary">
                <span className="block mb-1">
                  {t('workbench.adminAccounts.createForm.passwordLabel')} *
                </span>
                <input type="text" autoComplete="off" value={password}
                       onChange={e => setPassword(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                       placeholder={t('workbench.adminAccounts.createForm.passwordPlaceholder')}
                       className="w-full px-2 py-1.5 rounded-md text-xs text-primary"
                       style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }} />
              </label>
              <label className="block text-xs text-secondary">
                <span className="block mb-1">
                  {t('workbench.adminAccounts.createForm.nameLabel')}
                </span>
                <input type="text" autoComplete="off" value={name}
                       onChange={e => setName(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                       placeholder={t('workbench.adminAccounts.createForm.namePlaceholder')}
                       className="w-full px-2 py-1.5 rounded-md text-xs text-primary"
                       style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }} />
              </label>
            </div>
            {formErr && (
              <div className="mt-3 text-xs text-red-500">{formErr}</div>
            )}
            <div className="mt-5 flex items-center justify-end gap-2">
              <button type="button" disabled={submitting} onClick={closeModal}
                      className="text-xs px-3 py-1.5 rounded-md"
                      style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>
                {t('workbench.adminAccounts.createForm.cancel')}
              </button>
              <button type="button" disabled={submitting} onClick={handleCreate}
                      className="text-xs px-3 py-1.5 rounded-md text-white"
                      style={{ background: 'var(--accent-primary)', opacity: submitting ? 0.5 : 1 }}>
                {submitting
                  ? t('workbench.adminAccounts.createForm.submitting')
                  : t('workbench.adminAccounts.createForm.submit')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TodoCard({ count, label, color, to }: {
  count: number; label: string; color: string; to: string;
}) {
  const isEmpty = count === 0;
  return (
    <Link to={to}
          className="rounded-lg p-3 flex items-center justify-between transition-colors"
          style={{
            background: isEmpty ? 'var(--bg-card)' : `${color}15`,
            border: `1px solid ${isEmpty ? 'var(--border-color)' : `${color}40`}`,
            opacity: isEmpty ? 0.55 : 1,
          }}>
      <div>
        <div className="text-xs text-muted">{label}</div>
        <div className="text-2xl font-semibold tabular-nums" style={{ color: isEmpty ? 'var(--text-muted)' : color }}>
          {count}
        </div>
      </div>
      <div className="text-xs" style={{ color: isEmpty ? 'var(--text-muted)' : color }}>→</div>
    </Link>
  );
}
