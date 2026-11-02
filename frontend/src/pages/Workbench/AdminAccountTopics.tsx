import { Fragment, useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { aiTelemetryApi, type AdminAccount, type Topic, type TopicPayload } from '../../services/aiTelemetryApi';
import { adminReviewApi, type StageState, type TopicReviewListItem } from '../../services/adminReviewApi';
import { TopicEditor } from '../Dashboard/AiTelemetry';

// 项目进度 6 段顺序,与 cockpit `AdminCockpit.tsx` 对齐.
type StageKey = 'submit' | 'review' | 'solution' | 'plan' | 'content' | 'insight';
const STAGE_ORDER: StageKey[] = ['submit', 'review', 'solution', 'plan', 'content', 'insight'];

// 每段对应「画像」主流程的 URL step — 与 TopicStepper.tsx 同源.
// 点节点 = 直接进入该步,所以旧版的「编辑 / 健康诊断 / 计划书 / 复审文案」按钮就并到节点里了.
const STAGE_TO_STEP: Record<StageKey, number> = {
  submit: 1, review: 3, solution: 4, plan: 5, content: 6, insight: 7,
};

const PAGE_SIZE = 10;

// 把 cockpit 的 StageState 折算到本卡片 chip 调色板(无 pending,合并到 running).
function stageToChip(s: StageState): PipelineChipState {
  return s === 'done' ? 'done'
    : s === 'running' || s === 'pending' ? 'running'
    : s === 'blocked' ? 'failed'
    : 'idle';
}

// 复刻 cockpit 的 backward-infer:下游已 progress 时,上游 idle 推为 done.
function deriveStages(item: TopicReviewListItem | undefined): Record<StageKey, StageState> {
  const sub = item?.submission_status;
  const reviewRaw: StageState =
    sub === 'approved' ? 'done'
    : sub === 'rejected' ? 'blocked'
    : sub === 'pending' ? 'pending'
    : 'idle';
  const raw: Record<StageKey, StageState> = {
    submit: 'done',
    review: reviewRaw,
    solution: item?.diagnose_status ?? 'idle',
    plan: item?.plan_status ?? 'idle',
    content: item?.content_status ?? 'idle',
    insight: item?.insight_status ?? 'idle',
  };
  const eff = { ...raw };
  let progressed = false;
  for (let i = STAGE_ORDER.length - 1; i >= 0; i--) {
    const k = STAGE_ORDER[i];
    if (progressed && eff[k] === 'idle') eff[k] = 'done';
    if (eff[k] !== 'idle') progressed = true;
  }
  // Forward gate:效果查验依赖内容已发布 — 跟 cockpit AdminCockpit.tsx 同源.
  // batch 跑完但文稿还没发布时,insight 不能领先 content 显示 done.
  if (eff.content !== 'done' && eff.insight === 'done') {
    eff.insight = 'running';
  }
  return eff;
}

export function AdminAccountTopics() {
  const { userId } = useParams<{ userId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = localStorage.getItem('token') || '';
  const { t } = useTranslation();
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  // 客户账号(用于面包屑展示客户名 — brand_target / users.name).没有单条接口,从
  // adminListAccounts 里 find 出本 user.
  const [account, setAccount] = useState<AdminAccount | null>(null);
  // 项目进度 6 段状态,从 admin 列表接口拿,按 user_id 过滤 + topic_id 索引.
  const [stagesByTid, setStagesByTid] = useState<Record<number, TopicReviewListItem>>({});
  // undefined = 列表;null = 新建;Topic = 编辑(admin 也用同一个 editor)
  // URL 带 ?new=1 时(从「画像」注册后跳过来)直接进入新建编辑器
  const [editing, setEditing] = useState<Topic | null | undefined>(
    searchParams.get('new') === '1' ? null : undefined,
  );
  // 启动按钮的 per-topic busy / error state
  const [startBusyId, setStartBusyId] = useState<number | null>(null);
  const [startErrByTopic, setStartErrByTopic] = useState<Record<number, string>>({});
  const [page, setPage] = useState(1);

  // 启动项目(首次) — 走新的 /admin/topics/{id}/start.
  // 「重启」入口在执行计划书页里(走 /start?force=true),不在卡片上.
  const handleStart = async (tp: Topic) => {
    if (startBusyId !== null) return;
    setStartBusyId(tp.id);
    setStartErrByTopic((prev) => { const n = { ...prev }; delete n[tp.id]; return n; });
    try {
      await adminReviewApi.startTopic(tp.id, token);
      // 启动后直接进「画像」主流程的「计划书」step,不再跳到独立的 execution-plan 详情页.
      navigate(`/workbench/topics/${tp.id}/edit?step=5`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setStartErrByTopic((prev) => ({ ...prev, [tp.id]: msg }));
    } finally {
      setStartBusyId(null);
    }
  };

  // 进入新建模式后清掉 URL 参数,避免刷新页面又被自动打开
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      const next = new URLSearchParams(searchParams);
      next.delete('new');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  // 客户名称展示链 — 与 AdminAccounts.tsx (画像列表) 同源:
  //   1. account.brand_target  → 客户填的品牌名(ai_telemetry_topics.target,跨主题取最近)
  //   2. account.name          → admin 注册时填的内部备注(如「测试」)
  //   3. topics[0]?.target     → 兜底,极个别情况下 admin 接口失败但 topic 列表成功
  //   4. `用户 #id`            → 全失败兜底
  const customerName = account?.brand_target
    || account?.name
    || topics[0]?.target
    || `用户 #${userId}`;

  const reload = () => {
    if (!userId) return;
    setLoading(true);
    aiTelemetryApi.adminListUserTopics(Number(userId), token)
      .then(setTopics).catch(() => setTopics([])).finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    setLoading(true);
    aiTelemetryApi.adminListUserTopics(Number(userId), token)
      .then(r => { if (!cancelled) setTopics(r); })
      .catch(() => { if (!cancelled) setTopics([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    // 项目进度 6 段状态拉一次,filter 本用户的,按 topic_id 索引;失败不影响主列表(chip 显示 idle).
    adminReviewApi.listTopicReviews(token)
      .then(items => {
        if (cancelled) return;
        const m: Record<number, TopicReviewListItem> = {};
        const uid = Number(userId);
        for (const it of items) {
          if (it.user_id === uid) m[it.topic_id] = it;
        }
        setStagesByTid(m);
      })
      .catch(() => { if (!cancelled) setStagesByTid({}); });
    // 客户账号信息(为面包屑拿 brand_target / users.name);没有单条 GET,从全表 find.
    aiTelemetryApi.adminListAccounts(token)
      .then(accs => {
        if (cancelled) return;
        setAccount(accs.find(a => a.id === Number(userId)) || null);
      })
      .catch(() => { if (!cancelled) setAccount(null); });
    return () => { cancelled = true; };
  }, [userId, token]);

  // topics 缩短 / 切换客户 → totalPages 变,safePage 在渲染时夹到合法区间.
  const totalPages = Math.max(1, Math.ceil(topics.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pagedTopics = topics.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  if (!userId) return null;

  // 编辑场景 — admin 替别人 PUT,仍走 updateTopic(后端 allow_admin_user 已开)。
  const handleSave = async (payload: TopicPayload): Promise<Topic> => {
    if (editing && editing.id) {
      return aiTelemetryApi.updateTopic(editing.id, payload, token);
    }
    // 新建分支:实际由 TopicEditor 内部走 adminCreateTopicForUser,
    // 这里只是兜底 — onSave 在 admin-new 模式不会被调用。
    return aiTelemetryApi.adminCreateTopicForUser(Number(userId), payload, token);
  };

  if (editing !== undefined) {
    return (
      <div className="max-w-[1100px] mx-auto p-6 space-y-4">
        <div className="text-xs text-muted">
          <Link to="/workbench/accounts" className="hover:underline">
            {t('workbench.adminAccounts.title')}
          </Link>
          {' / '}
          <Link to={`/workbench/accounts/${userId}/topics`} className="hover:underline"
            onClick={(e) => { e.preventDefault(); setEditing(undefined); }}>
            {t('workbench.adminAccountTopics.title', { name: customerName })}
          </Link>
          {' / '}
          {editing ? t('workbench.adminAccountTopics.editTopic') : t('workbench.adminAccountTopics.newTopic')}
        </div>
        <h1 className="text-xl font-semibold text-primary">
          {editing ? t('workbench.adminAccountTopics.editTopic') : t('workbench.adminAccountTopics.newTopic')}
        </h1>
        <TopicEditor
          initial={editing}
          token={token}
          mode="edit"
          adminTargetUserId={Number(userId)}
          onCancel={() => setEditing(undefined)}
          onSave={handleSave}
          onSaveDone={(saved) => {
            // 不再关闭编辑器、不弹「审批报告」模态:TopicEditor 已自动进 step 4 内嵌健康报告,
            // 同步效果在 step 4「查看完整报告」/「重新生成」里;关闭由 step 4 的「完成」按钮触发.
            reload();
            // 让 editing 跟着 saved 同步,确保后续动作(再次编辑等)拿到新 id
            if (saved) setEditing(saved);
          }}
        />
      </div>
    );
  }

  return (
    <div className="max-w-[1100px] mx-auto p-6">
      <div className="text-xs text-muted mb-2">
        <Link to="/workbench/accounts" className="hover:underline">
          {t('workbench.adminAccounts.title')}
        </Link>
        {' / '}
        {t('workbench.adminAccountTopics.title', { name: customerName })}
      </div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-primary">
          {t('workbench.adminAccountTopics.heading')}
        </h1>
        <button
          type="button"
          onClick={() => setEditing(null)}
          className="px-3 py-1.5 text-sm rounded-md text-white"
          style={{ background: 'var(--accent-primary)' }}
        >
          + {t('workbench.adminAccountTopics.newTopic')}
        </button>
      </div>

      {loading ? (
        <div className="text-xs text-muted text-center py-10">
          {t('common.loading')}
        </div>
      ) : topics.length === 0 ? (
        <div className="text-xs text-muted text-center py-10">
          {t('workbench.adminAccountTopics.emptyHint')}
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-3">
          {pagedTopics.map(tp => {
            // 「是否启动过」用 last_run_at 推断:approve_topic / start_topic / rerun 都会拿
            // run_id,有 last_run_at 说明至少触发过一次跑批.老 approved 主题(admin 直建,
            // 未跑过)走 last_run_at == null 分支,显示「启动项目」首发按钮.
            const hasRun = !!tp.last_run_at;
            const isStartBusy = startBusyId === tp.id;
            const startErr = startErrByTopic[tp.id];
            // 项目进度 6 段:走 cockpit 同源 deriveStages,缺数据时退到 idle.
            const stages = deriveStages(stagesByTid[tp.id]);
            // 当前进行到的步骤索引:第一个非 done 的步,用于 stepper 视觉高亮.
            const currentIdx = (() => {
              for (let i = 0; i < STAGE_ORDER.length; i++) {
                const st = stageToChip(stages[STAGE_ORDER[i]]);
                if (st !== 'done') return i;
              }
              return STAGE_ORDER.length - 1;
            })();
            return (
              <li key={tp.id}
                onClick={() => navigate(`/workbench/topics/${tp.id}/edit`)}
                className="flex flex-col p-5 rounded-xl cursor-pointer transition-colors hover:border-[var(--accent-primary)]"
                style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
                {/* 头部:标题 + 客户名 / 行业 + 「启动项目」CTA(未跑过时) */}
                <div className="flex items-start justify-between gap-3 mb-4">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-base font-semibold text-primary truncate" title={tp.name}>
                      {tp.name}
                    </h3>
                    <p className="text-xs text-muted mt-1 truncate">
                      {tp.target || '—'}{tp.industry ? ` · ${tp.industry}` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <div className="text-right text-[11px] leading-tight">
                      <div className="text-secondary">
                        <span className="tabular-nums text-primary">{tp.queries.length}</span>
                        <span className="text-muted ml-1">Q</span>
                        <span className="mx-1 text-muted">/</span>
                        <span className="tabular-nums text-primary">{tp.engines.length}</span>
                        <span className="text-muted ml-1">E</span>
                      </div>
                      <div className="text-muted mt-1">
                        {tp.last_run_status || t('workbench.adminAccountTopics.neverRun')}
                      </div>
                    </div>
                    {!hasRun && (
                      <button
                        type="button"
                        disabled={isStartBusy}
                        onClick={(e) => { e.stopPropagation(); handleStart(tp); }}
                        className="text-xs px-3 py-1.5 rounded-md text-white shrink-0"
                        style={{ background: 'var(--accent-primary)', opacity: isStartBusy ? 0.5 : 1 }}
                      >
                        {isStartBusy ? '…' : t('workbench.adminAccountTopics.startProject')}
                      </button>
                    )}
                  </div>
                </div>

                {/* 项目进度 6 段 stepper — 节点本身是按钮,idle 步骤 disabled 不让点 */}
                <div className="flex items-start mt-1">
                  {STAGE_ORDER.map((k, i) => {
                    const state = stageToChip(stages[k]);
                    const isCurrent = i === currentIdx && state !== 'done';
                    const next = i < STAGE_ORDER.length - 1
                      ? stageToChip(stages[STAGE_ORDER[i + 1]]) : null;
                    const connectorDone = state === 'done' && (next === 'done' || next === 'running');
                    // idle = 后面还没跑到的流程 — 既无结果也不可点;done / running / failed 都可看.
                    const isInteractive = state !== 'idle';
                    return (
                      <Fragment key={k}>
                        <button
                          type="button"
                          disabled={!isInteractive}
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/workbench/topics/${tp.id}/edit?step=${STAGE_TO_STEP[k]}`);
                          }}
                          className={`flex flex-col items-center px-1 py-1 rounded transition-colors ${
                            isInteractive
                              ? 'cursor-pointer hover:bg-[var(--bg-tertiary)]'
                              : 'cursor-default opacity-70'
                          }`}
                          style={{ width: 104 }}
                        >
                          <StepCircle state={state} index={i} isCurrent={isCurrent} />
                          <span className="text-[11px] text-secondary mt-1.5 text-center leading-tight">
                            {t(`workbench.adminCockpit.stage.${k}`)}
                          </span>
                          {/* 节点下面的 action chip — 只在有结果时(非 idle)出现 */}
                          {isInteractive && (
                            <span
                              className="mt-2 inline-block text-[11px] px-2 py-0.5 rounded-full transition-colors"
                              style={{
                                color: 'var(--accent-primary)',
                                border: '1px solid var(--accent-primary)',
                                background: 'transparent',
                              }}
                              // inline style 优先级压过 utility class,hover 同时改 bg + color
                              onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'var(--accent-primary)';
                                e.currentTarget.style.color = '#fff';
                              }}
                              onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'transparent';
                                e.currentTarget.style.color = 'var(--accent-primary)';
                              }}
                            >
                              {t(`workbench.adminAccountTopics.nodeAction.${k}`)}
                            </span>
                          )}
                        </button>
                        {i < STAGE_ORDER.length - 1 && (
                          <div className="flex-1 mt-[18px] h-[2px] rounded-full"
                               style={{ background: connectorDone ? '#10b981' : 'var(--border-color)' }} />
                        )}
                      </Fragment>
                    );
                  })}
                </div>

                {startErr && (
                  <div className="mt-3 text-[11px] text-red-500 break-words">
                    {startErr}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {topics.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-secondary mt-4">
          <span className="tabular-nums text-muted">
            {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, topics.length)} / 共 {topics.length} 个
          </span>
          <div className="flex items-center gap-2">
            <button type="button" disabled={safePage <= 1}
                    onClick={() => setPage(Math.max(1, safePage - 1))}
                    className="px-2 py-1 rounded-md disabled:opacity-40"
                    style={{ background: 'var(--bg-tertiary)' }}>
              上一页
            </button>
            <span className="tabular-nums">{safePage} / {totalPages}</span>
            <button type="button" disabled={safePage >= totalPages}
                    onClick={() => setPage(Math.min(totalPages, safePage + 1))}
                    className="px-2 py-1 rounded-md disabled:opacity-40"
                    style={{ background: 'var(--bg-tertiary)' }}>
              下一页
            </button>
          </div>
        </div>
      )}

    </div>
  );
}

// 6 段 stepper 用的圆 — done 实心绿、running 黄填充 + 黄环、failed 实心红、idle 空心灰.
// 当前步(isCurrent)再额外加 ring,让用户一眼看到走到哪步.
type PipelineChipState = 'idle' | 'running' | 'done' | 'failed';

function StepCircle({ state, index, isCurrent }: {
  state: PipelineChipState; index: number; isCurrent: boolean;
}) {
  const palette: Record<PipelineChipState, { bg: string; fg: string; border: string; mark: string }> = {
    done:    { bg: '#10b981', fg: '#fff',              border: '#10b981',          mark: '✓' },
    running: { bg: '#eab308', fg: '#fff',              border: '#eab308',          mark: String(index + 1) },
    failed:  { bg: '#ef4444', fg: '#fff',              border: '#ef4444',          mark: '✕' },
    idle:    { bg: 'var(--bg-card)', fg: 'var(--text-muted)', border: 'var(--border-color)', mark: String(index + 1) },
  };
  const p = palette[state];
  return (
    <span
      className="inline-flex items-center justify-center rounded-full text-[11px] font-semibold tabular-nums"
      style={{
        width: 28, height: 28,
        background: p.bg, color: p.fg,
        border: `1.5px solid ${p.border}`,
        boxShadow: isCurrent ? '0 0 0 3px rgba(234,179,8,0.25)' : 'none',
      }}
    >{p.mark}</span>
  );
}
