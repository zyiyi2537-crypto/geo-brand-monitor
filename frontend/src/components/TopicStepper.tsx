// TopicStepper — 项目详情页共享的「6 步管线」导航条,与项目进度看板对齐.
// 用法:任何 /workbench/topics/:topicId/* 的页面顶部 render 一个 <TopicStepper topicId={tid} active="plan" />
// 6 步:① 画像 ② 诊断与方案预评估 ③ GEO策略优化方案 ④ 计划书 ⑤ 文案 ⑥ 效果查验与更新
// 状态符号:✓ done / ⋯ running / ─ idle / ✗ failed
//
// Maintained workflow: docs/product/content-workflow.md

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { adminReviewApi, type ExecutionPlan, type TopicReviewDetail, type TopicStrategicSolution } from '../services/adminReviewApi';

export type StepKey = 'profile' | 'review' | 'solution' | 'plan' | 'docs' | 'insight';
// editing 是新加的:plan 步骤在 draft 态下进入「等运营编辑发文表」,蓝调高亮.
export type StepStatus = 'idle' | 'running' | 'done' | 'failed' | 'editing';

interface Props {
  topicId: number;
  active: StepKey;
}

interface StepDef {
  key: StepKey;
  label: string;
  status: StepStatus;
  hint?: string;     // 副标题(进度数字等)
  onClick: () => void;
}

export function TopicStepper({ topicId, active }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const token = localStorage.getItem('token') || '';
  const [topic, setTopic] = useState<TopicReviewDetail | null>(null);
  const [solution, setSolution] = useState<TopicStrategicSolution | null>(null);
  const [plan, setPlan] = useState<ExecutionPlan | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!topicId) return;
    let cancelled = false;
    adminReviewApi.getTopicReview(topicId, token)
      .then((d) => { if (!cancelled) setTopic(d); })
      .catch((e) => { if (!cancelled) setErr(e instanceof Error ? e.message : String(e)); });
    // 健康诊断报告状态用 getStrategicSolution 拿,失败不显示错误(stepper 上只用状态)
    adminReviewApi.getStrategicSolution(topicId, token)
      .then((s) => { if (!cancelled) setSolution(s); })
      .catch(() => {});
    // 执行计划状态:plan.status + 文章生成进度 → plan step chip
    adminReviewApi.getExecutionPlan(topicId, token)
      .then((p) => { if (!cancelled) setPlan(p); })
      .catch(() => {});  // 还没启动项目时 404,不打扰
    return () => { cancelled = true; };
  }, [topicId, token]);

  // 各步状态推断.画像 = profile 必填齐 + 至少 1 个 selected query(合并设计里的画像和监测问题).
  // 文案 / 投放合并为「文案」.健康诊断报告从 solution.status 推 ready=done / generating=running / failed=failed.
  const profileOk = !!(topic?.profile?.company_short_name)
                    && ((topic?.selected_query_count ?? 0) > 0
                        || (topic?.query_selected?.some(Boolean) ?? false));
  // 诊断与方案预评估:由 submission_status 推.复刻 cockpit deriveStages 的 reviewRaw.
  // pending 在 stepper 视觉上没有独立态,合并到 running;rejected 走 failed.
  const sub = topic?.submission_status;
  const reviewChip: StepStatus =
    sub === 'approved' ? 'done'
    : sub === 'rejected' ? 'failed'
    : sub === 'pending' ? 'running'
    : 'idle';
  // 计划步骤 chip:plan.status 优先;没 plan 时 fallback 到老 last_run_status.
  // draft → editing(蓝)/ confirmed + 还有 doc 在跑或监控在跑 → running / confirmed + 全好 → done.
  const planChip: StepStatus = (() => {
    if (plan) {
      if (plan.status === 'failed') return 'failed';
      if (plan.status === 'draft' || plan.status === 'generating') return 'editing';
      // confirmed / ready 兼容
      const docsTotal = plan.publishing_plan?.length ?? 0;
      const docsPending = (plan.publishing_plan || []).some(
        it => !it.doc_id || it.doc_status === 'draft',
      );
      const monRunning = plan.run_status === 'running';
      if (docsTotal === 0 || docsPending || monRunning) return 'running';
      return 'done';
    }
    return topic?.last_run_status === 'success' ? 'done'
         : topic?.last_run_status === 'running' ? 'running'
         : topic?.last_run_status === 'failed' ? 'failed'
         : 'idle';
  })();
  const solChip: StepStatus = solution?.status === 'ready' ? 'done'
                            : solution?.status === 'generating' ? 'running'
                            : solution?.status === 'failed' ? 'failed'
                            : 'idle';
  // 效果查验与更新:复刻后端 admin_review._insight_state — approved + 有过运行才算非 idle.
  // success → done / running → running / failed → failed / 其他 → idle.
  const insChip: StepStatus = (() => {
    if (topic?.submission_status !== 'approved' || !topic?.last_run_at) return 'idle';
    const s = (topic?.last_run_status || '').toLowerCase();
    return s === 'success' ? 'done'
      : s === 'running' ? 'running'
      : s === 'failed' ? 'failed'
      : 'idle';
  })();

  // 全部 6 段都跳「画像」主流程的对应 step,不再去单独的 review/solution/plan/docs/insight 详情页.
  //   profile→step 1  review→step 3  solution→step 4  plan→step 5  docs→step 6  insight→step 7
  const editBase = `/workbench/topics/${topicId}/edit`;
  const steps: StepDef[] = [
    {
      key: 'profile', label: t('workbench.topicStepper.profile'),
      status: profileOk ? 'done' : 'idle',
      hint: profileOk ? String(topic?.selected_query_count ?? 0) + ' Q' : undefined,
      onClick: () => navigate(`${editBase}?step=1`),
    },
    {
      key: 'review', label: t('workbench.topicStepper.review'),
      status: reviewChip,
      onClick: () => navigate(`${editBase}?step=3`),
    },
    {
      key: 'solution', label: t('workbench.topicStepper.solution'),
      status: solChip,
      onClick: () => navigate(`${editBase}?step=4`),
    },
    {
      key: 'plan', label: t('workbench.topicStepper.plan'),
      status: planChip,
      hint: plan && plan.status === 'draft' ? '编辑中' : undefined,
      onClick: () => navigate(`${editBase}?step=5`),
    },
    {
      key: 'docs', label: t('workbench.topicStepper.docs'),
      status: 'idle',
      onClick: () => navigate(`${editBase}?step=6`),
    },
    {
      key: 'insight', label: t('workbench.topicStepper.insight'),
      status: insChip,
      onClick: () => navigate(`${editBase}?step=7`),
    },
  ];

  return (
    <div className="rounded-md p-4 mb-4" style={{
      background: 'var(--bg-card)', border: '1px solid var(--border-color)',
    }}>
      {/* 头部:面包屑(辅助按钮已合并进 step 4 健康诊断报告) */}
      <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div className="text-xs">
          {topic && (
            <span className="text-muted">
              <button type="button"
                      onClick={() => navigate(`/workbench/accounts/${topic.user_id}/topics`)}
                      className="hover:underline">
                ← {topic.target || topic.user_email || `用户 #${topic.user_id}`}
              </button>
              <span className="mx-1">/</span>
              <span className="text-primary font-medium">{topic.name}</span>
            </span>
          )}
          {err && <span className="text-red-500">{err}</span>}
        </div>
      </div>

      {/* Stepper bar */}
      <div className="flex items-stretch gap-1 overflow-x-auto scrollbar-hide">
        {steps.map((s, i) => (
          <StepCell key={s.key}
                    step={s}
                    active={s.key === active}
                    isLast={i === steps.length - 1} />
        ))}
      </div>
    </div>
  );
}

const STATUS_PALETTE: Record<StepStatus, { fg: string; bg: string; line: string; mark: string }> = {
  done:    { fg: '#10b981', bg: 'rgba(16,185,129,0.10)', line: '#10b981', mark: '✓' },
  running: { fg: '#eab308', bg: 'rgba(234,179,8,0.10)',  line: '#eab308', mark: '⋯' },
  failed:  { fg: '#ef4444', bg: 'rgba(239,68,68,0.10)',  line: '#ef4444', mark: '✗' },
  editing: { fg: '#3b82f6', bg: 'rgba(59,130,246,0.10)', line: '#3b82f6', mark: '✎' },
  idle:    { fg: 'var(--text-muted)', bg: 'var(--bg-tertiary)', line: 'var(--border-color)', mark: '─' },
};

function StepCell({ step, active, isLast }: { step: StepDef; active: boolean; isLast: boolean }) {
  const p = STATUS_PALETTE[step.status];
  return (
    <>
      <button type="button" onClick={step.onClick}
              className="flex-1 min-w-[100px] flex flex-col items-center gap-1 px-2 py-2 rounded transition-colors"
              style={{
                background: active ? p.bg : 'transparent',
                border: active ? `1px solid ${p.line}` : '1px solid transparent',
                cursor: 'pointer',
              }}>
        <div className="flex items-center justify-center w-6 h-6 rounded-full font-semibold text-xs"
             style={{ background: p.bg, color: p.fg, border: `1px solid ${p.line}` }}>
          {p.mark}
        </div>
        <div className="text-xs font-medium" style={{ color: active ? p.fg : 'var(--text-secondary)' }}>
          {step.label}
        </div>
        {step.hint && (
          <div className="text-[10px] text-muted">{step.hint}</div>
        )}
      </button>
      {!isLast && (
        <div className="flex items-center px-0.5">
          <div className="w-3 h-px" style={{ background: 'var(--border-color)' }} />
        </div>
      )}
    </>
  );
}
