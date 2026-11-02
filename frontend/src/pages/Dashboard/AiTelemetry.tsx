// AI 遥测 工作台页 — 一个组件承载 3 个 route:
//   /dashboard            views=['config']                  — 主题配置(新 dashboard 首页)
//   /dashboard/ai-telemetry  views=['overview','tracking','results'] — 遥测看板
//   /dashboard/insights   views=['briefings']               — 优化建议
//
// 频率由后端固定为 daily,前端不暴露时间选择.
import { Fragment, useEffect, useMemo, useState, type ReactElement } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

import { PageHead } from '../../components/PageHead';
import { TagInput } from './sentiment/components/TagInput';
import { BrandProfileForm } from '../../components/BrandProfileForm';
import { ProfileImporter } from '../../components/ProfileImporter';
import { topicProfileApi } from '../../services/topicProfileApi';
import { adminReviewApi, type TopicStrategicSolution } from '../../services/adminReviewApi';
import { SolutionView } from '../Admin/Solution';
import { ExecutionPlanView } from '../Admin/ExecutionPlan';
import { AdminContentReview } from '../Admin/ContentReview';
import { exportSolutionPdf } from '../../utils/exportSolutionPdf';
import { exportSolutionDocx } from '../../utils/exportSolutionDocx';
import {
  aiTelemetryApi, CN_ENGINES, EMPTY_BRAND_PROFILE,
  type BrandProfile,
  type EngineId, type Topic, type TopicPayload,
  type RunSummary, type ResponseRow, type Overview, type DomainCount,
  type IntentBreakdown,
  type OwnedSplit,
  type TrackingMatrix, type QueryHitCell, type EngineFirstHit,
  type CellDrawer, type CellInsight, type Briefing, type ShareOfVoice,
  type QueryCandidate,
  type SeedPrompt, type ReviewStatus,
  type SceneType,
} from '../../services/aiTelemetryApi';

// 2026-05-28 — 4 维场景标签的展示元数据(label 走 i18n,color 内联避免跨主题串色)
const SCENE_COLORS: Record<SceneType, string> = {
  search: '#6366f1',   // 蓝紫
  qa: '#10b981',       // 绿
  intent: '#f59e0b',   // 黄
  brand: '#ec4899',    // 粉
};
const SCENE_KEYS: SceneType[] = ['search', 'qa', 'intent', 'brand'];

// 品牌基础词 — 纯前端模板拼接,瞬时生成不走 LLM:品牌名 ×一组固定评价/了解后缀。
// 问品牌自己的高频通用词,自有内容最容易覆盖、一批就能搞定(参考竞品「XX怎么样/口碑/实力」批量铺词)。
// 归到 brand 场景展示,不新增维度。
const BRAND_BASIC_SUFFIXES = [
  '怎么样', '好不好', '口碑', '口碑怎么样', '评价如何', '客户评价如何', '用户评价怎么样',
  '实力怎么样', '有实力吗', '专业吗', '正规吗', '可信吗', '值得信任吗', '靠谱吗',
  '性价比怎么样', '服务怎么样', '产品怎么样', '产品好用吗', '满意度怎么样',
  '介绍', '详细介绍', '公司概况', '基本信息', '是做什么的',
];
function buildBrandBasicQueries(brand: string): string[] {
  const b = brand.trim();
  if (!b) return [];
  return [b, ...BRAND_BASIC_SUFFIXES.map(s => `${b}${s}`)];
}

import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip, Legend,
  AreaChart, Area, PieChart, Pie, Cell,
} from 'recharts';
import { Tooltip as HintTooltip } from '../../components/Tooltip';

type TabKey = 'today' | 'overview' | 'tracking' | 'briefings' | 'config' | 'results';

const ENGINE_COLORS: Record<EngineId, string> = {
  deepseek: '#5B6CFF', doubao: '#FF7043', qwen: '#7E57C2',
  wenxin: '#26A69A', yuanbao: '#EF5350',
  chatgpt: '#10A37F', claude: '#C97650', gemini: '#4285F4',
  grok: '#9CA3AF', copilot: '#0078D4',
};

function InfoHint({ text }: { text: string }) {
  return (
    <HintTooltip content={text}>
      <span
        role="img"
        aria-label="info"
        className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-semibold cursor-help align-middle leading-none select-none"
        style={{
          background: 'var(--bg-input)',
          color: 'var(--text-muted)',
          border: '1px solid var(--border-color)',
        }}
      >?</span>
    </HintTooltip>
  );
}

// Phase C — 种子词 / query 审核状态徽章
function ReviewBadge({ status }: { status: ReviewStatus }) {
  const map: Record<ReviewStatus, { fg: string; bg: string; icon: string; key: string }> = {
    approved: { fg: '#10b981', bg: 'rgba(16,185,129,0.15)', icon: '✓', key: 'dashboard.aiTelemetry.form.badgeApproved' },
    pending:  { fg: '#f59e0b', bg: 'rgba(245,158,11,0.15)', icon: '⏳', key: 'dashboard.aiTelemetry.form.badgePending' },
    rejected: { fg: '#ef4444', bg: 'rgba(239,68,68,0.15)', icon: '✕', key: 'dashboard.aiTelemetry.form.badgeRejected' },
  };
  const s = map[status] || map.pending;
  return (
    <span
      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium"
      style={{ color: s.fg, background: s.bg }}
    >
      {s.icon}
      <ReviewBadgeLabel keyName={s.key} />
    </span>
  );
}

function ReviewBadgeLabel({ keyName }: { keyName: string }) {
  const { t } = useTranslation();
  return <>{t(keyName)}</>;
}

const ALL_TABS: TabKey[] = ['today', 'overview', 'tracking', 'briefings', 'config', 'results'];

export function AiTelemetry({ views }: { views?: TabKey[] } = {}) {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';
  const visibleTabs = (views && views.length > 0 ? views : ALL_TABS);
  const showTabBar = visibleTabs.length > 1;
  const showNewTopicBtn = visibleTabs.includes('config');
  const [tab, setTab] = useState<TabKey>(visibleTabs[0]);
  // clamp:若组件被复用(state 残留),把 tab 拉回当前视图允许的范围
  const currentTab: TabKey = visibleTabs.includes(tab) ? tab : visibleTabs[0];
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(false);
  // undefined = modal closed; null = creating; Topic = editing
  const [editing, setEditing] = useState<Topic | null | undefined>(undefined);
  // 进入 editor 时的形态:edit(可写) / view(只读)
  const [editorMode, setEditorMode] = useState<'edit' | 'view'>('edit');
  // 概览 / 引用追踪 / 检测详情 共享的 topic 选择 — 切 tab 时保留
  const [sharedTopicId, setSharedTopicId] = useState<number | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const list = await aiTelemetryApi.listTopics(token);
      setTopics(list);
      // 首次拿到 topics 时把默认选中的 topic 落到共享 state
      setSharedTopicId(prev => (prev !== null ? prev : list[0]?.id ?? null));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh();   }, []);

  const handleSave = async (payload: TopicPayload): Promise<Topic> => {
    const saved = editing && editing.id
      ? await aiTelemetryApi.updateTopic(editing.id, payload, token)
      : await aiTelemetryApi.createTopic(payload, token);
    return saved;
  };

  const handleSaveDone = () => {
    setEditing(undefined);
    refresh();
  };

  const handleToggleEnabled = async (tp: Topic) => {
    // 后端 PUT /topics/{id} 要求完整 payload — 由当前 topic 数据重建
    const payload: TopicPayload = {
      name: tp.name,
      target: tp.target,
      target_aliases: tp.target_aliases,
      industry: tp.industry || '',
      queries: tp.queries,
      query_cluster_ids: tp.query_cluster_ids,
      clusters: tp.clusters,
      engines: tp.engines,
      enabled: !tp.enabled,
    };
    await aiTelemetryApi.updateTopic(tp.id, payload, token);
    refresh();
  };

  // 编辑 / 新建模式:把整页内容换成 inline editor,200+ 候选才有空间选
  if (editing !== undefined) {
    return (
      <div className="space-y-4">
        <PageHead titleKey="dashboard.aiTelemetry.title" titleFallback="AI Telemetry" />
        <header className="flex items-center justify-between gap-4">
          <h1 className="text-xl font-semibold text-primary leading-tight">
            {t(
              editorMode === 'view'
                ? 'dashboard.aiTelemetry.viewTopic'
                : editing
                  ? 'dashboard.aiTelemetry.editTopic'
                  : 'dashboard.aiTelemetry.newTopic',
            )}
          </h1>
          <button
            type="button"
            onClick={() => setEditing(undefined)}
            className="text-sm px-2 py-1 rounded-md"
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-secondary)',
            }}
          >
            ← {t('dashboard.aiTelemetry.backToList')}
          </button>
        </header>
        <TopicEditor
          initial={editing}
          token={token}
          mode={editorMode}
          onCancel={() => setEditing(undefined)}
          onSave={handleSave}
          onSaveDone={handleSaveDone}
        />
      </div>
    );
  }

  // 标题 / 副标题:跟侧边栏菜单同源(用 dashboard.nav.*),subtitle 各 view 独立
  const headTitleKey =
    visibleTabs.length === 1 && visibleTabs[0] === 'config' ? 'dashboard.nav.config' :
    visibleTabs.length === 1 && visibleTabs[0] === 'briefings' ? 'dashboard.nav.insights' :
    'dashboard.nav.aiTelemetry';
  const subtitleKey =
    visibleTabs.length === 1 && visibleTabs[0] === 'config' ? 'dashboard.config.subtitle' :
    visibleTabs.length === 1 && visibleTabs[0] === 'briefings' ? 'dashboard.insights.subtitle' :
    'dashboard.aiTelemetry.subtitle';

  return (
    <div className="space-y-4">
      <PageHead titleKey={headTitleKey} titleFallback="AI Telemetry" />

      <header className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span
            className="inline-flex items-center justify-center w-9 h-9 rounded-lg"
            style={{ background: 'var(--accent-primary)', color: 'white' }}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M2 12h3l2-6 4 12 2-6 2 3h3 4" />
            </svg>
          </span>
          <div>
            <h1 className="text-xl font-semibold text-primary leading-tight">
              {t(headTitleKey)}
            </h1>
            <p className="text-xs text-secondary mt-0.5">{t(subtitleKey)}</p>
          </div>
        </div>
        {showNewTopicBtn && (
          <button
            type="button"
            onClick={() => { setEditorMode('edit'); setEditing(null); }}
            className="px-3 py-1.5 text-sm rounded-md text-white shadow-sm hover:opacity-90 transition-opacity"
            style={{ background: 'var(--accent-primary)' }}
          >
            + {t('dashboard.aiTelemetry.newTopic')}
          </button>
        )}
      </header>

      {showTabBar && (
        <div className="flex gap-1 border-b" style={{ borderColor: 'var(--border-color)' }}>
          {visibleTabs.map(k => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              className="px-3 py-2 text-sm -mb-px"
              style={{
                borderBottom: tab === k ? '2px solid var(--accent-primary)' : '2px solid transparent',
                color: tab === k ? 'var(--accent-primary)' : 'var(--text-secondary)',
              }}
            >
              {t(`dashboard.aiTelemetry.tab${k.charAt(0).toUpperCase() + k.slice(1)}`)}
            </button>
          ))}
        </div>
      )}

      {currentTab ==='today' && (
        <TodayTab topics={topics} token={token}
          topicId={sharedTopicId} onTopicChange={setSharedTopicId} />
      )}
      {currentTab ==='overview' && (
        <OverviewTab topics={topics} token={token}
          topicId={sharedTopicId} onTopicChange={setSharedTopicId} />
      )}
      {currentTab ==='tracking' && (
        <TrackingTab topics={topics} token={token}
          topicId={sharedTopicId} onTopicChange={setSharedTopicId} />
      )}
      {currentTab ==='briefings' && <BriefingsTab topics={topics} token={token} />}
      {currentTab ==='config' && (
        <TopicTable
          topics={topics} loading={loading}
          onView={(tp) => { setEditorMode('view'); setEditing(tp); }}
          onEdit={(tp) => { setEditorMode('edit'); setEditing(tp); }}
          onToggleEnabled={handleToggleEnabled}
        />
      )}
      {currentTab ==='results' && (
        <ResultsTab topics={topics} token={token}
          topicId={sharedTopicId} onTopicChange={setSharedTopicId} />
      )}
    </div>
  );
}

// ── 主题卡片网格(每个 topic 渲染成一个独立卡片,响应式 2/3 列)──────────────

function TopicTable({
  topics, loading, onView, onEdit, onToggleEnabled,
}: {
  topics: Topic[]; loading: boolean;
  onView: (t: Topic) => void;
  onEdit: (t: Topic) => void;
  onToggleEnabled: (t: Topic) => void;
}) {
  const { t } = useTranslation();
  if (loading) return <div className="py-12 text-center text-sm text-muted">…</div>;
  if (topics.length === 0) {
    return (
      <div
        className="py-12 text-center text-sm text-muted rounded-lg"
        style={{ background: 'var(--bg-card)', border: '1px dashed var(--border-color)' }}
      >
        {t('dashboard.aiTelemetry.empty')}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {topics.map(tp => (
        <TopicBlock key={tp.id} topic={tp}
                    onView={onView} onEdit={onEdit} onToggleEnabled={onToggleEnabled} />
      ))}
    </div>
  );
}

function TopicBlock({
  topic: tp, onView, onEdit, onToggleEnabled,
}: {
  topic: Topic;
  onView: (t: Topic) => void;
  onEdit: (t: Topic) => void;
  onToggleEnabled: (t: Topic) => void;
}) {
  const { t } = useTranslation();
  const s = deriveTopicStatus(tp);
  const stat = TOPIC_STATUS_STYLE[s];
  return (
    <section className="rounded-lg p-4 flex flex-col gap-3"
             style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-base font-semibold text-primary truncate flex-1 min-w-0" title={tp.name}>
          {tp.name}
        </h3>
        <span className="inline-block px-2 py-0.5 rounded text-xs shrink-0"
              style={{ background: stat.bg, color: stat.fg,
                       border: '1px solid var(--border-color)' }}>
          {t(`dashboard.aiTelemetry.statuses.${s}`)}
        </span>
      </div>

      {typeof tp.version === 'number' && tp.version > 1 && (
        <span className="text-[10px] px-1.5 py-0.5 rounded-full tabular-nums self-start"
              style={{ background: 'var(--bg-tertiary)', color: 'var(--text-muted)' }}
              title={`第 ${tp.version} 次修订(每次编辑自增)`}>
          v{tp.version}
        </span>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-secondary">
        <span>
          <span className="text-muted">{t('dashboard.aiTelemetry.col.queries')}:</span>{' '}
          <span className="text-primary tabular-nums">{tp.queries.length}</span>
        </span>
        <span>
          <span className="text-muted">{t('dashboard.aiTelemetry.col.engines')}:</span>{' '}
          <span className="text-primary tabular-nums">{tp.engines.length}/10</span>
        </span>
      </div>

      <div className="flex items-center gap-2 mt-auto pt-1 flex-wrap">
        <button type="button" onClick={() => onView(tp)}
                className="text-xs px-3 py-1.5 rounded-md"
                style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)',
                         border: '1px solid var(--border-color)' }}>
          {t('dashboard.aiTelemetry.actions.view')}
        </button>
        <button type="button" onClick={() => onEdit(tp)}
                className="text-xs px-3 py-1.5 rounded-md text-white"
                style={{ background: 'var(--accent-primary)' }}>
          {t('dashboard.aiTelemetry.actions.edit')}
        </button>
        <button type="button" onClick={() => onToggleEnabled(tp)}
                className="text-xs px-3 py-1.5 rounded-md"
                style={{ background: 'transparent',
                         color: tp.enabled ? 'var(--text-muted)' : 'var(--accent-primary)',
                         border: '1px solid var(--border-color)' }}>
          {tp.enabled
            ? t('dashboard.aiTelemetry.actions.disable')
            : t('dashboard.aiTelemetry.actions.enable')}
        </button>
      </div>
    </section>
  );
}

type TopicStatus = 'incomplete' | 'draft' | 'reviewing' | 'rejected' | 'enabled' | 'disabled';

function deriveTopicStatus(tp: Topic): TopicStatus {
  // submission_status 是审核主真相;旧逻辑(看 seed_prompts.pending)会让"draft 但种子是 pending"
  // 错误显示为"审核中",于是用户以为提交了,但 admin 那边查 submission_status='pending' 看不到。
  const sub = tp.submission_status;
  if (sub === 'pending') return 'reviewing';
  if (sub === 'rejected') return 'rejected';
  if (sub === 'approved') return tp.enabled === false ? 'disabled' : 'enabled';
  // draft 或 undefined。step1「下一步」只落了资料、还没配监测问题的骨架草稿(queries 为空)
  // 单独标「草稿」,跟已配置好的可编辑主题区分,方便识别 / 清理中途放弃的半成品。
  if ((tp.queries?.length ?? 0) === 0) return 'incomplete';
  if (!tp.enabled) return 'disabled';
  return 'draft';
}

const TOPIC_STATUS_STYLE: Record<TopicStatus, { bg: string; fg: string }> = {
  incomplete:{ bg: 'rgba(148,163,184,0.18)', fg: '#64748b' },
  draft:    { bg: 'rgba(59,130,246,0.15)', fg: '#3b82f6' },
  reviewing:{ bg: 'rgba(234,179,8,0.15)',  fg: '#b45309' },
  rejected: { bg: 'rgba(239,68,68,0.15)',  fg: '#dc2626' },
  enabled:  { bg: 'rgba(34,197,94,0.15)',  fg: '#16a34a' },
  disabled: { bg: 'var(--bg-input)',       fg: 'var(--text-muted)' },
};

function formatTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return d.toLocaleDateString();
}

// ── 今日 ───────────────────────────────────────────────────────

function TodayTab({ topics, token, topicId, onTopicChange }: {
  topics: Topic[]; token: string;
  topicId: number | null; onTopicChange: (id: number | null) => void;
}) {
  const { t } = useTranslation();
  const setTopicId = onTopicChange;
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [responsesByRun, setResponsesByRun] = useState<Record<number, ResponseRow[]>>({});
  const [loading, setLoading] = useState(false);
  const [triggering, setTriggering] = useState(false);

  useEffect(() => {
    if (topicId === null && topics.length > 0) setTopicId(topics[0].id);
  }, [topics, topicId, setTopicId]);

  const load = async (tid: number) => {
    setLoading(true);
    try {
      const rs = await aiTelemetryApi.listRuns(tid, token);
      setRuns(rs);
      // 加载今天 + 昨天的 runs 的 responses(昨天用于算 citations 增量)
      const dayStart = startOfDay(new Date()).getTime();
      const need = rs.filter(r => {
        const ts = parseApiTs(r.started_at).getTime();
        return ts >= dayStart - 86400000 && ts < dayStart + 86400000;
      });
      const pairs = await Promise.all(need.map(async r => {
        try { return [r.id, await aiTelemetryApi.listResponses(r.id, token)] as const; }
        catch { return [r.id, [] as ResponseRow[]] as const; }
      }));
      const map: Record<number, ResponseRow[]> = {};
      for (const [id, rows] of pairs) map[id] = rows;
      setResponsesByRun(map);
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (topicId === null) return;
    load(topicId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicId, token]);

  if (topics.length === 0) {
    return <EmptyHint text={t('dashboard.aiTelemetry.today.noTopics')} />;
  }

  const topic = topics.find(tp => tp.id === topicId) ?? null;
  const dayStart = startOfDay(new Date()).getTime();
  const todayRuns = runs.filter(r => parseApiTs(r.started_at).getTime() >= dayStart);
  const yesterdayRuns = runs.filter(r => {
    const ts = parseApiTs(r.started_at).getTime();
    return ts >= dayStart - 86400000 && ts < dayStart;
  });
  const todayResponses = todayRuns.flatMap(r => responsesByRun[r.id] ?? []);
  const yesterdayResponses = yesterdayRuns.flatMap(r => responsesByRun[r.id] ?? []);

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-input)', border: '1px solid var(--border-color)',
    color: 'var(--text-primary)',
  };

  const handleRunNow = async () => {
    if (topicId === null || triggering) return;
    setTriggering(true);
    try {
      await aiTelemetryApi.triggerRun(topicId, token);
      // 后端异步,等一下再 refresh
      setTimeout(() => { if (topicId !== null) load(topicId); }, 1500);
    } finally { setTriggering(false); }
  };

  return (
    <div className="space-y-4">
      {/* 顶部:topic 选 + 立即检测 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="text-xs text-secondary">
          {t('dashboard.aiTelemetry.today.selectTopic')}
          <select
            value={topicId ?? ''} onChange={e => setTopicId(Number(e.target.value))}
            className="ml-2 px-2 py-1 text-sm rounded" style={inputStyle}
          >
            {topics.map(tp => <option key={tp.id} value={tp.id}>{tp.name}</option>)}
          </select>
        </label>
        <button
          type="button"
          onClick={handleRunNow}
          disabled={triggering || topicId === null}
          className="px-3 py-1.5 text-xs rounded-md text-white disabled:opacity-50"
          style={{ background: 'var(--accent-primary)' }}
        >
          {triggering
            ? t('dashboard.aiTelemetry.actions.running')
            : t('dashboard.aiTelemetry.today.runNow')}
        </button>
      </div>

      {loading && <div className="text-sm text-muted py-6 text-center">…</div>}

      {!loading && todayRuns.length === 0 && (
        <EmptyHint text={t('dashboard.aiTelemetry.today.noRunToday')} />
      )}

      {!loading && todayRuns.length > 0 && topic && (
        <TodayBody
          topic={topic}
          todayRuns={todayRuns}
          todayResponses={todayResponses}
          yesterdayResponses={yesterdayResponses}
        />
      )}
    </div>
  );
}

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

// 后端 datetime.utcnow() 序列化为 naive ISO(无 Z),JS 默认按本地时区解析会偏 8h —
// 这里显式补 Z,让它按 UTC 解析,本地化的活交给 toLocaleString 之类
function parseApiTs(s: string): Date {
  if (!s) return new Date(NaN);
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : s + 'Z');
}

function TodayBody({ topic, todayRuns, todayResponses, yesterdayResponses }: {
  topic: Topic;
  todayRuns: RunSummary[];
  todayResponses: ResponseRow[];
  yesterdayResponses: ResponseRow[];
}) {
  const { t } = useTranslation();
  const enginesAll = topic.engines.length > 0 ? topic.engines : CN_ENGINES;
  const queriesAll = topic.queries;

  // 每引擎状态:done(有成功) / failed(只有 error) / pending(还没回来)
  const engineStatus = useMemo(() => {
    const map: Record<string, 'done' | 'failed' | 'pending'> = {};
    const anyRunning = todayRuns.some(r => r.status === 'running');
    for (const e of enginesAll) {
      const rows = todayResponses.filter(r => r.engine === e);
      const ok = rows.filter(r => !r.error).length;
      const err = rows.filter(r => r.error).length;
      if (ok > 0) map[e] = 'done';
      else if (err > 0) map[e] = 'failed';
      else map[e] = anyRunning ? 'pending' : 'failed';
    }
    return map;
  }, [enginesAll, todayResponses, todayRuns]);

  const enginesDone = enginesAll.filter(e => engineStatus[e] === 'done').length;
  const enginesFailed = enginesAll.filter(e => engineStatus[e] === 'failed');
  const enginesRunning = enginesAll.filter(e => engineStatus[e] === 'pending').length;
  const allDone = enginesDone === enginesAll.length;
  const elapsedSecs = (() => {
    const finished = todayRuns.filter(r => r.finished_at);
    if (finished.length === 0) return 0;
    const start = Math.min(...todayRuns.map(r => parseApiTs(r.started_at).getTime()));
    const end = Math.max(...finished.map(r => parseApiTs(r.finished_at!).getTime()));
    return Math.max(1, Math.round((end - start) / 1000));
  })();

  // KPIs
  const okResponses = todayResponses.filter(r => !r.error);
  const hits = okResponses.filter(r => r.hit === true).length;
  const mentionRate = okResponses.length > 0 ? Math.round(hits / okResponses.length * 100) : 0;
  const citationsToday = okResponses.reduce((s, r) => s + r.citations.length, 0);
  const citationsYesterday = yesterdayResponses
    .filter(r => !r.error)
    .reduce((s, r) => s + r.citations.length, 0);
  const citationsDelta = citationsToday - citationsYesterday;

  // 矩阵:queries × engines
  const cellMap = useMemo(() => {
    const m: Record<string, ResponseRow[]> = {};
    for (const r of todayResponses) {
      const k = `${r.query}|${r.engine}`;
      (m[k] = m[k] || []).push(r);
    }
    return m;
  }, [todayResponses]);
  const cellState = (q: string, e: string): 'hit' | 'miss' | 'err' | 'none' => {
    const rows = cellMap[`${q}|${e}`] || [];
    if (rows.length === 0) return 'none';
    if (rows.some(r => r.hit === true)) return 'hit';
    if (rows.some(r => !r.error && r.hit === false)) return 'miss';
    if (rows.some(r => r.error)) return 'err';
    return 'none';
  };
  const queryHitCount = (q: string) => {
    let hit = 0, ran = 0;
    for (const e of enginesAll) {
      const s = cellState(q, e);
      if (s === 'hit') { hit++; ran++; }
      else if (s === 'miss' || s === 'err') ran++;
    }
    return { hit, ran };
  };

  // 今日新增引用
  const citedDomains = useMemo(() => {
    const map = new Map<string, { url: string; title: string; domain: string; count: number; engines: Set<string> }>();
    for (const r of okResponses) {
      for (const c of r.citations) {
        const k = c.url;
        const cur = map.get(k);
        if (cur) { cur.count++; cur.engines.add(r.engine); }
        else map.set(k, { url: c.url, title: c.title, domain: c.domain, count: 1, engines: new Set([r.engine]) });
      }
    }
    return Array.from(map.values()).sort((a, b) => b.count - a.count);
  }, [okResponses]);

  // 盲区:今日所有 engine 都未提及的 query
  const blindQueries = queriesAll.filter(q => {
    const { hit, ran } = queryHitCount(q);
    return ran > 0 && hit === 0;
  });

  const cardBg: React.CSSProperties = {
    background: 'var(--bg-card)', border: '1px solid var(--border-color)',
  };

  return (
    <div className="space-y-4">
      {/* 状态条 */}
      <div className="px-4 py-2.5 rounded-lg flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" style={cardBg}>
        <span className="text-secondary">{t('dashboard.aiTelemetry.today.runStatus')}:</span>
        {allDone
          ? <span className="text-emerald-500">
              ● {t('dashboard.aiTelemetry.today.runStatusAllDone', { total: enginesAll.length, secs: elapsedSecs })}
            </span>
          : <span className="text-blue-500">
              ● {t('dashboard.aiTelemetry.today.runStatusRunning', {
                  done: enginesDone, total: enginesAll.length, running: enginesRunning,
                })}
            </span>}
        {enginesFailed.length > 0 && (
          <span className="text-rose-500">
            ⚠ {t('dashboard.aiTelemetry.today.runStatusFailed', { failed: enginesFailed.length })}
          </span>
        )}
        <span className="text-muted ml-auto">
          {t('dashboard.aiTelemetry.today.runStartedAt', {
            time: new Date(Math.min(...todayRuns.map(r => parseApiTs(r.started_at).getTime()))).toLocaleTimeString(),
          })}
        </span>
      </div>

      {/* KPI 4 张卡 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <TodayKpiCard
          label={t('dashboard.aiTelemetry.today.kpiQueries')}
          value={queriesAll.length}
          sub={t('dashboard.aiTelemetry.today.kpiQueriesUnit', {
            engines: enginesAll.length,
            calls: queriesAll.length * enginesAll.length,
          })}
        />
        <TodayKpiCard
          label={t('dashboard.aiTelemetry.today.kpiMentionRate')}
          value={`${mentionRate}%`}
          sub={t('dashboard.aiTelemetry.today.kpiMentionRateUnit', { hits, total: okResponses.length })}
          hint={t('dashboard.aiTelemetry.today.tipMentionRate')}
        />
        <TodayKpiCard
          label={t('dashboard.aiTelemetry.today.kpiCitations')}
          value={citationsToday}
          sub={citationsDelta > 0
            ? t('dashboard.aiTelemetry.today.kpiCitationsDeltaUp', { n: citationsDelta })
            : citationsDelta < 0
              ? t('dashboard.aiTelemetry.today.kpiCitationsDeltaDown', { n: citationsDelta })
              : t('dashboard.aiTelemetry.today.kpiCitationsDeltaSame')}
          subColor={citationsDelta > 0 ? '#10b981' : citationsDelta < 0 ? '#ef4444' : undefined}
          hint={t('dashboard.aiTelemetry.today.tipCitations')}
        />
        <TodayKpiCard
          label={t('dashboard.aiTelemetry.today.kpiEngines')}
          value={t('dashboard.aiTelemetry.today.kpiEnginesUnit', { done: enginesDone, total: enginesAll.length })}
          sub={enginesFailed.length > 0
            ? t('dashboard.aiTelemetry.today.kpiEnginesFailed', {
                names: enginesFailed.map(e => engineName(e, t)).join(' / '),
              })
            : ''}
          subColor={enginesFailed.length > 0 ? '#ef4444' : undefined}
          hint={t('dashboard.aiTelemetry.today.tipEngines')}
        />
      </div>

      {/* 命中矩阵 */}
      <div className="rounded-lg overflow-hidden" style={cardBg}>
        <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <div className="text-sm font-medium text-primary">
            {t('dashboard.aiTelemetry.today.matrixTitle')}
          </div>
          <div className="text-xs text-muted mt-0.5">
            {t('dashboard.aiTelemetry.today.matrixHint')}
          </div>
        </div>
        {queriesAll.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted">
            {t('dashboard.aiTelemetry.today.matrixEmpty')}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}>
                  <th className="text-left px-3 py-2 font-medium sticky left-0 z-10"
                      style={{ background: 'var(--bg-secondary)', minWidth: 240 }}>
                    {t('dashboard.aiTelemetry.today.matrixColQuery')}
                  </th>
                  {enginesAll.map(e => (
                    <th key={e} className="text-center px-2 py-2 font-medium">
                      <div>{engineName(e, t)}</div>
                      <EngineStatusDot status={engineStatus[e]} />
                    </th>
                  ))}
                  <th className="text-center px-3 py-2 font-medium">
                    {t('dashboard.aiTelemetry.today.matrixColHits')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {queriesAll.map((q, i) => {
                  const { hit, ran } = queryHitCount(q);
                  return (
                    <tr key={i} style={{ borderTop: '1px solid var(--border-color)' }}>
                      <td className="px-3 py-2 text-secondary sticky left-0"
                          style={{ background: 'var(--bg-card)', maxWidth: 320 }}
                          title={q}>
                        <span className="line-clamp-2">{q}</span>
                      </td>
                      {enginesAll.map(e => (
                        <td key={e} className="text-center px-2 py-2">
                          <CellGlyph state={cellState(q, e)} />
                        </td>
                      ))}
                      <td className="text-center px-3 py-2 text-secondary tabular-nums">
                        {ran === 0
                          ? '—'
                          : t('dashboard.aiTelemetry.today.matrixRowHitRate', { hits: hit, total: ran })}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 今日新增引用 + 盲区 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-lg" style={cardBg}>
          <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border-color)' }}>
            <div className="text-sm font-medium text-primary">
              {t('dashboard.aiTelemetry.today.citedTitle')}
            </div>
            <div className="text-xs text-muted mt-0.5">
              {t('dashboard.aiTelemetry.today.citedHint')}
            </div>
          </div>
          {citedDomains.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted">
              {t('dashboard.aiTelemetry.today.citedEmpty')}
            </div>
          ) : (
            <div className="max-h-80 overflow-y-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}>
                    <th className="text-left px-3 py-2 font-medium w-8">
                      {t('dashboard.aiTelemetry.today.citedColRank')}
                    </th>
                    <th className="text-left px-3 py-2 font-medium">
                      {t('dashboard.aiTelemetry.today.citedColTitle')}
                    </th>
                    <th className="text-left px-3 py-2 font-medium">
                      {t('dashboard.aiTelemetry.today.citedColEngines')}
                    </th>
                    <th className="text-right px-3 py-2 font-medium w-16">
                      {t('dashboard.aiTelemetry.today.citedColCount')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {citedDomains.map((c, i) => (
                    <tr key={c.url} style={{ borderTop: '1px solid var(--border-color)' }}>
                      <td className="px-3 py-2 text-muted tabular-nums">{i + 1}</td>
                      <td className="px-3 py-2">
                        <a href={c.url} target="_blank" rel="noreferrer"
                           className="hover:underline block truncate max-w-[18rem]"
                           style={{ color: 'var(--accent-primary)' }}
                           title={c.title || c.url}>
                          {c.title || c.url}
                        </a>
                        <div className="text-[10px] text-muted">{c.domain}</div>
                      </td>
                      <td className="px-3 py-2 text-secondary">
                        {Array.from(c.engines).map(e => engineName(e, t)).join(', ')}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-primary">{c.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="rounded-lg" style={cardBg}>
          <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border-color)' }}>
            <div className="text-sm font-medium text-primary">
              {t('dashboard.aiTelemetry.today.blindTitle')}
            </div>
            <div className="text-xs text-muted mt-0.5">
              {t('dashboard.aiTelemetry.today.blindHint')}
            </div>
          </div>
          {blindQueries.length === 0 ? (
            <div className="py-8 text-center text-sm text-emerald-500">
              ✓ {t('dashboard.aiTelemetry.today.blindEmpty')}
            </div>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {blindQueries.map((q, i) => (
                <li key={i}
                    className="px-4 py-2 text-sm text-primary"
                    style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-color)' }}>
                  <span className="text-rose-500 mr-2">✕</span>{q}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function engineName(e: string, t: ReturnType<typeof useTranslation>['t']): string {
  return t(`dashboard.aiTelemetry.engine.${e}`, e);
}

function TodayKpiCard({ label, value, sub, subColor, hint }: {
  label: string; value: number | string; sub?: string; subColor?: string; hint?: string;
}) {
  return (
    <div className="rounded-lg px-4 py-3"
         style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="text-xs text-secondary flex items-center gap-1">
        {label}{hint && <InfoHint text={hint} />}
      </div>
      <div className="text-xl font-semibold text-primary mt-1 tabular-nums">{value}</div>
      {sub && (
        <div className="text-[11px] mt-0.5" style={{ color: subColor || 'var(--text-muted)' }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function CellGlyph({ state }: { state: 'hit' | 'miss' | 'err' | 'none' }) {
  if (state === 'hit') return <span className="inline-block w-5 h-5 rounded-full text-emerald-500" title="hit">✓</span>;
  return <span className="inline-block w-5 h-5 text-muted" title="not mentioned">✕</span>;
}

function EngineStatusDot({ status }: { status?: 'done' | 'failed' | 'pending' }) {
  const color = status === 'done' ? '#10b981'
    : status === 'failed' ? '#ef4444'
    : '#f59e0b';
  return (
    <span className="inline-block w-1.5 h-1.5 rounded-full mt-0.5" style={{ background: color }} />
  );
}

// ── 概览 ───────────────────────────────────────────────────────

function OverviewTab({ topics, token, topicId, onTopicChange }: {
  topics: Topic[]; token: string;
  topicId: number | null; onTopicChange: (id: number | null) => void;
}) {
  const { t } = useTranslation();
  const setTopicId = onTopicChange;
  const [period, setPeriod] = useState<7 | 30 | 90>(30);
  const [data, setData] = useState<Overview | null>(null);
  const [sov, setSoV] = useState<ShareOfVoice | null>(null);
  const [intent, setIntent] = useState<IntentBreakdown | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (topicId === null && topics.length > 0) setTopicId(topics[0].id);
  }, [topics, topicId, setTopicId]);

  useEffect(() => {
    if (topicId === null) return;
    setLoading(true);
    Promise.all([
      aiTelemetryApi.getOverview(topicId, period, token),
      aiTelemetryApi.getShareOfVoice(topicId, period, token).catch(() => null),
      aiTelemetryApi.getIntentBreakdown(topicId, period, token).catch(() => null),
    ]).then(([ov, s, ib]) => {
      setData(ov);
      setSoV(s);
      setIntent(ib);
    }).finally(() => setLoading(false));
  }, [topicId, period, token]);

  if (topics.length === 0) {
    return <EmptyHint text={t('dashboard.aiTelemetry.empty')} />;
  }

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-input)', border: '1px solid var(--border-color)',
    color: 'var(--text-primary)',
  };

  return (
    <div className="space-y-4">
      {/* 顶部控制行 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="text-xs text-secondary">
          {t('dashboard.aiTelemetry.overview.selectTopic')}
          <select
            value={topicId ?? ''} onChange={e => setTopicId(Number(e.target.value))}
            className="ml-2 px-2 py-1 text-sm rounded" style={inputStyle}
          >
            {topics.map(tp => <option key={tp.id} value={tp.id}>{tp.name}</option>)}
          </select>
        </label>
        <div className="flex gap-1" style={{ background: 'var(--bg-input)', borderRadius: 6, padding: 2 }}>
          {([7, 30, 90] as const).map(p => (
            <button
              key={p} type="button"
              onClick={() => setPeriod(p)}
              className="px-3 py-1 text-xs rounded"
              style={{
                background: period === p ? 'var(--accent-primary)' : 'transparent',
                color: period === p ? 'white' : 'var(--text-secondary)',
              }}
            >
              {t(`dashboard.aiTelemetry.overview.period${p}`)}
            </button>
          ))}
        </div>
      </div>

      {data && data.brand_keywords.length === 0 && (
        <div className="text-xs text-amber-500 px-3 py-2 rounded"
          style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.3)' }}>
          ⚠ {t('dashboard.aiTelemetry.overview.noBrand')}
        </div>
      )}

      {/* 4 KPI 卡 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard
          label={t('dashboard.aiTelemetry.overview.kpiVisibility')}
          value={data?.visibility.value ?? 0}
          unit={t('dashboard.aiTelemetry.overview.kpiVisibilityUnit')}
          delta={data?.visibility.delta_pct ?? null}
          sparkline={data?.visibility.sparkline ?? []}
          loading={loading}
          icon="eye"
          hint={t('dashboard.aiTelemetry.overview.tipVisibility')}
        />
        <KpiCard
          label={t('dashboard.aiTelemetry.overview.kpiCitations')}
          value={data?.citations.value ?? 0}
          delta={data?.citations.delta_pct ?? null}
          sparkline={data?.citations.sparkline ?? []}
          loading={loading}
          fmt="int"
          icon="link"
          hint={t('dashboard.aiTelemetry.overview.tipCitations')}
        />
        <KpiCard
          label={t('dashboard.aiTelemetry.overview.kpiGrowth')}
          value={data?.growth.value ?? 0}
          unit="%"
          delta={null}
          sparkline={[]}
          loading={loading}
          accentByValue
          icon="trend"
          hint={t('dashboard.aiTelemetry.overview.tipGrowth')}
        />
        <KpiCard
          label={t('dashboard.aiTelemetry.overview.kpiEngines')}
          value={data?.engines_covered.value ?? 0}
          unit={`/${data?.engines_total ?? 0}`}
          delta={data?.engines_covered.delta_pct ?? null}
          sparkline={[]}
          loading={loading}
          fmt="int"
          icon="cpu"
          hint={t('dashboard.aiTelemetry.overview.tipEngines')}
        />
      </div>

      {/* v1.3 — SAIV 声量份额 + 竞品引用份额差 */}
      <ShareOfVoiceBlock data={sov} loading={loading} />

      {/* 趋势图 */}
      <TrendChart data={data} loading={loading} />

      {/* intent 分布(picker 端聚出的簇 × 本期 mention 率)*/}
      <IntentBreakdownBlock data={intent} loading={loading} />

      {/* 引用分析:Top 10 + Owned vs Other */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="md:col-span-2">
          <TopDomainsBlock data={data?.top_domains ?? []} loading={loading} />
        </div>
        <OwnedSplitBlock data={data?.owned_split} loading={loading} />
      </div>

      {/* 引擎 × 平台 heatmap */}
      <EngineDomainMatrix
        engines={data?.engines ?? []}
        topDomains={data?.top_domains ?? []}
        matrix={data?.engine_domain_matrix ?? {}}
        loading={loading}
      />
    </div>
  );
}

// ── v1.3 SAIV 声量份额 + 竞品引用份额差 + 命中位置分布 ───────────

function ShareOfVoiceBlock({ data, loading }: { data: ShareOfVoice | null; loading: boolean }) {
  const { t } = useTranslation();
  if (loading && !data) {
    return (
      <div className="rounded-lg p-4 text-sm text-muted text-center"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>…</div>
    );
  }
  if (!data) return null;
  const hasSignal = data.brand_count + data.competitors_count_total > 0;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      {/* SAIV KPI 卡 */}
      <div className="rounded-lg p-4"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <h3 className="text-sm font-medium text-primary mb-2 flex items-center gap-1">
          <span style={{ color: 'var(--accent-primary)' }}>📣</span>
          {t('dashboard.aiTelemetry.overview.saivTitle')}
          <InfoHint text={t('dashboard.aiTelemetry.overview.tipSaiv')} />
        </h3>
        <div className="flex items-baseline gap-1">
          <span className="text-3xl font-semibold tabular-nums text-primary">
            {data.saiv_pct.toFixed(1)}
          </span>
          <span className="text-muted text-sm">%</span>
        </div>
        <p className="text-[11px] text-muted mt-1">
          {t('dashboard.aiTelemetry.overview.saivHint', {
            brand: data.brand_count,
            total: data.brand_count + data.competitors_count_total,
          })}
        </p>
        {/* 命中位置分布(检索排名简化版) */}
        {hasSignal && data.brand_count > 0 && (
          <div className="mt-3">
            <div className="text-[11px] font-semibold text-secondary uppercase tracking-wider mb-1 inline-flex items-center gap-1">
              {t('dashboard.aiTelemetry.overview.positionTitle')}
              <InfoHint text={t('dashboard.aiTelemetry.overview.tipPosition')} />
            </div>
            <PositionBar dist={data.position_dist} />
          </div>
        )}
        <div className="mt-3 text-[11px] text-muted">
          {t('dashboard.aiTelemetry.overview.optimalRate')}
          <InfoHint text={t('dashboard.aiTelemetry.overview.tipOptimalRate')} />:
          <span className="text-primary font-semibold ml-1">
            {data.optimal_rate_pct.toFixed(1)}%
          </span>
          <span className="ml-1">
            ({t('dashboard.aiTelemetry.overview.optimalRateHint', { runs: data.total_runs })})
          </span>
        </div>
      </div>

      {/* 竞品份额对比 */}
      <div className="rounded-lg p-4 md:col-span-2"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <h3 className="text-sm font-medium text-primary mb-3 inline-flex items-center gap-1">
          {t('dashboard.aiTelemetry.overview.competitorShareTitle')}
          <InfoHint text={t('dashboard.aiTelemetry.overview.tipCompetitorShare')} />
        </h3>
        {!hasSignal && (
          <div className="text-xs text-muted py-6 text-center">
            {t('dashboard.aiTelemetry.overview.competitorShareEmpty')}
          </div>
        )}
        {hasSignal && (
          <ul className="space-y-1.5">
            {/* 把品牌自身和竞品一起排序展示 */}
            {[
              { name: `★ ${data.target}`, count: data.brand_count,
                pct: data.brand_count / Math.max(1, data.brand_count + data.competitors_count_total) * 100,
                isBrand: true },
              ...data.competitors.map(c => ({ ...c, isBrand: false })),
            ]
              .sort((a, b) => b.count - a.count)
              .slice(0, 8)
              .map((c, i) => {
                const max = Math.max(
                  data.brand_count,
                  ...data.competitors.map(x => x.count),
                );
                const width = Math.max(4, (c.count / Math.max(1, max)) * 100);
                return (
                  <li key={i} className="flex items-center gap-2 text-xs">
                    <span className="w-32 truncate"
                      style={{
                        color: c.isBrand ? 'var(--accent-primary)' : 'var(--text-primary)',
                        fontWeight: c.isBrand ? 600 : 400,
                      }}>{c.name}</span>
                    <div className="flex-1 h-3 rounded relative"
                      style={{ background: 'var(--bg-input)' }}>
                      <div className="h-3 rounded transition-all" style={{
                        width: `${width}%`,
                        background: c.isBrand ? 'var(--accent-primary)' : '#94a3b8',
                      }} />
                    </div>
                    <span className="w-10 text-right text-primary tabular-nums">{c.count}</span>
                    <span className="w-12 text-right text-muted tabular-nums">
                      {c.pct.toFixed(1)}%
                    </span>
                  </li>
                );
              })}
          </ul>
        )}
      </div>
    </div>
  );
}

function PositionBar({ dist }: { dist: ShareOfVoice['position_dist'] }) {
  const total = dist.lead + dist.body + dist.tail + dist.unknown;
  if (total === 0) return <p className="text-[11px] text-muted">—</p>;
  const segs = [
    { key: 'lead', color: '#10b981', n: dist.lead },     // 绿:开头
    { key: 'body', color: '#3b82f6', n: dist.body },     // 蓝:中段
    { key: 'tail', color: '#f59e0b', n: dist.tail },     // 黄:末尾
    { key: 'unknown', color: '#9ca3af', n: dist.unknown },
  ];
  return (
    <div>
      <div className="flex rounded overflow-hidden h-2"
        style={{ background: 'var(--bg-tertiary)' }}>
        {segs.map(s => s.n > 0 && (
          <div key={s.key} title={`${s.key}: ${s.n}`}
            style={{ width: `${s.n / total * 100}%`, background: s.color }} />
        ))}
      </div>
      <div className="flex gap-2 mt-1 text-[10px] text-muted">
        {segs.filter(s => s.n > 0).map(s => (
          <span key={s.key}>
            <span style={{ color: s.color }}>●</span> {s.key} {s.n}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── intent 分布 ────────────────────────────────────────────

function IntentBreakdownBlock({ data, loading }: { data: IntentBreakdown | null; loading: boolean }) {
  const { t } = useTranslation();
  if (loading && !data) {
    return (
      <div className="rounded-lg p-4 text-sm text-muted text-center"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>…</div>
    );
  }
  if (!data) return null;
  const hasSignal = data.clusters.length > 0 || data.uncategorized.response_count > 0;
  if (!hasSignal) return null;

  // 一行显示所有有 response 的簇 + 兜底桶。按 mention_rate 升序排,先看到弱簇 → 内容补强目标
  const items = [
    ...data.clusters,
    ...(data.uncategorized.response_count > 0 ? [data.uncategorized] : []),
  ].filter(c => c.response_count > 0)
    .sort((a, b) => a.mention_rate - b.mention_rate);

  if (items.length === 0) return null;

  const maxRate = Math.max(...items.map(c => c.mention_rate), 0.01);
  return (
    <div className="rounded-lg p-4"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <h3 className="text-sm font-medium text-primary mb-3 inline-flex items-center gap-1">
        {t('dashboard.aiTelemetry.overview.intentTitle')}
        <InfoHint text={t('dashboard.aiTelemetry.overview.tipIntent')} />
      </h3>
      <div className="text-xs text-muted mb-3">
        {t('dashboard.aiTelemetry.overview.intentHint')}
      </div>
      <div className="space-y-2">
        {items.map(c => {
          const rate = c.mention_rate * 100;
          const barPct = (c.mention_rate / maxRate) * 100;
          const barColor = c.mention_rate >= 0.5 ? 'var(--accent-primary)'
            : c.mention_rate >= 0.25 ? '#f59e0b'
            : '#ef4444';
          return (
            <div key={c.cluster_id} className="flex items-center gap-3 text-xs">
              <div className="w-40 shrink-0 break-all" style={{ color: 'var(--text-primary)' }}>
                {c.cluster_id === -1
                  ? t('dashboard.aiTelemetry.overview.intentUncategorized')
                  : c.label}
              </div>
              <div className="flex-1 relative h-4 rounded"
                style={{ background: 'var(--bg-input)' }}>
                <div className="absolute inset-y-0 left-0 rounded"
                  style={{ width: `${barPct}%`, background: barColor }} />
              </div>
              <div className="w-12 text-right tabular-nums font-mono shrink-0"
                style={{ color: 'var(--text-primary)' }}>
                {rate.toFixed(0)}%
              </div>
              <div className="w-24 text-right text-muted shrink-0">
                {t('dashboard.aiTelemetry.overview.intentResponseCount', {
                  m: c.mention_count, n: c.response_count,
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


// ── 引用分析:Top 10 ────────────────────────────────────────────

function TopDomainsBlock({ data, loading }: { data: DomainCount[]; loading: boolean }) {
  const { t } = useTranslation();
  const max = Math.max(1, ...data.map(d => d.count));

  return (
    <div
      className="rounded-lg p-4 h-full"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
      }}
    >
      <h3 className="text-sm font-medium text-primary mb-3 inline-flex items-center gap-1">
        {t('dashboard.aiTelemetry.overview.topDomainsTitle')}
        <InfoHint text={t('dashboard.aiTelemetry.overview.tipTopDomains')} />
      </h3>
      {loading && <div className="text-sm text-muted py-6 text-center">…</div>}
      {!loading && data.length === 0 && (
        <div className="text-sm text-muted py-6 text-center">
          {t('dashboard.aiTelemetry.overview.topDomainsEmpty')}
        </div>
      )}
      {!loading && data.length > 0 && (
        <ul className="space-y-1">
          {data.map((d, i) => {
            const rank = i + 1;
            const rankBg = rank <= 3 ? 'var(--accent-primary)' : 'var(--bg-input)';
            const rankFg = rank <= 3 ? 'white' : 'var(--text-muted)';
            return (
              <li
                key={d.domain}
                className="flex items-center gap-2 text-xs py-1 px-1 rounded transition-colors hover:bg-[var(--bg-input)]"
              >
                <span
                  className="inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-semibold"
                  style={{ background: rankBg, color: rankFg }}
                >
                  {rank}
                </span>
                <img
                  src={`https://www.google.com/s2/favicons?domain=${d.domain}&sz=32`}
                  alt="" width={16} height={16}
                  className="rounded flex-shrink-0"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden'; }}
                />
                <span className="text-primary truncate flex-shrink-0 w-40">{d.domain}</span>
                <div className="flex-1 h-2.5 rounded-full overflow-hidden" style={{ background: 'var(--bg-input)' }}>
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(d.count / max) * 100}%`,
                      background: 'linear-gradient(90deg, var(--accent-primary), var(--accent-primary))',
                      opacity: 0.9,
                    }}
                  />
                </div>
                <span className="text-primary w-10 text-right tabular-nums font-medium">{d.count}</span>
                <span className="text-muted w-12 text-right tabular-nums">{d.pct.toFixed(1)}%</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── 引用分析:自家 vs 其他 ─────────────────────────────────────

function OwnedSplitBlock({ data, loading }: { data: OwnedSplit | undefined; loading: boolean }) {
  const { t } = useTranslation();
  const empty = !data || (data.owned === 0 && data.other === 0);
  const pieData = data ? [
    { name: 'owned', value: data.owned },
    { name: 'other', value: data.other },
  ] : [];

  return (
    <div
      className="rounded-lg p-4 h-full flex flex-col"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
      }}
    >
      <h3 className="text-sm font-medium text-primary mb-3 inline-flex items-center gap-1">
        {t('dashboard.aiTelemetry.overview.ownedTitle')}
        <InfoHint text={t('dashboard.aiTelemetry.overview.tipOwned')} />
      </h3>
      {loading && <div className="flex-1 flex items-center justify-center text-sm text-muted">…</div>}
      {!loading && empty && (
        <div className="flex-1 flex items-center justify-center text-sm text-muted text-center px-2">
          {t('dashboard.aiTelemetry.overview.topDomainsEmpty')}
        </div>
      )}
      {!loading && !empty && data && (
        <>
          <div className="h-44 relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData} dataKey="value" nameKey="name"
                  cx="50%" cy="50%" innerRadius={52} outerRadius={76}
                  paddingAngle={data.owned > 0 && data.other > 0 ? 2 : 0}
                  strokeWidth={0} isAnimationActive={false}
                >
                  <Cell fill="var(--accent-primary)" />
                  <Cell fill="var(--bg-input)" />
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-3xl font-semibold text-primary tabular-nums">
                {data.owned_pct.toFixed(1)}<span className="text-lg text-muted">%</span>
              </span>
              <span className="text-[11px] text-muted mt-0.5">
                {t('dashboard.aiTelemetry.overview.ownedLegendOwned')}
              </span>
            </div>
          </div>
          {data.delta_pct !== null && data.delta_pct !== undefined && (
            <div className="text-xs text-center mb-2">
              <span className={data.delta_pct >= 0 ? 'text-emerald-500' : 'text-rose-500'}>
                {data.delta_pct >= 0 ? '↑' : '↓'} {Math.abs(data.delta_pct).toFixed(1)}%
              </span>
              <span className="text-muted ml-1">vs 上期</span>
            </div>
          )}
          <div className="flex justify-around text-xs">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: 'var(--accent-primary)' }} />
              <span className="text-secondary">{t('dashboard.aiTelemetry.overview.ownedLegendOwned')}</span>
              <span className="text-primary font-semibold tabular-nums">{data.owned}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)' }} />
              <span className="text-secondary">{t('dashboard.aiTelemetry.overview.ownedLegendOther')}</span>
              <span className="text-primary font-semibold tabular-nums">{data.other}</span>
            </div>
          </div>
          <div className="text-[10px] text-muted mt-3 text-center leading-relaxed">
            {t('dashboard.aiTelemetry.overview.ownedHint')}
          </div>
        </>
      )}
    </div>
  );
}

// ── 引用分析:引擎 × 平台 heatmap ──────────────────────────────

function EngineDomainMatrix({
  engines, topDomains, matrix, loading,
}: {
  engines: EngineId[];
  topDomains: DomainCount[];
  matrix: Partial<Record<EngineId, Record<string, number>>>;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const empty = engines.length === 0 || topDomains.length === 0;

  let maxVal = 0;
  for (const e of engines) {
    const row = matrix[e] || {};
    for (const d of topDomains) {
      maxVal = Math.max(maxVal, row[d.domain] || 0);
    }
  }
  if (maxVal === 0) maxVal = 1;

  const cellBg = (v: number): string => {
    if (v === 0) return 'var(--bg-card)';
    // 5 段量化色阶,跨度 0.30 - 0.95 alpha,对比清晰
    const ratio = v / maxVal;
    const alpha = 0.30 + ratio * 0.65;
    return `rgba(91, 108, 255, ${alpha.toFixed(2)})`;
  };

  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
      }}
    >
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-sm font-medium text-primary inline-flex items-center gap-1">
          {t('dashboard.aiTelemetry.overview.matrixTitle')}
          <InfoHint text={t('dashboard.aiTelemetry.overview.tipMatrix')} />
        </h3>
        {!empty && (
          <div className="flex items-center gap-1.5 text-[10px] text-muted">
            <span>{t('dashboard.aiTelemetry.overview.matrixHint')}</span>
            <span className="flex items-center gap-px ml-1">
              {[0.30, 0.45, 0.60, 0.78, 0.95].map(a => (
                <span
                  key={a}
                  className="w-3 h-3 inline-block"
                  style={{ background: `rgba(91, 108, 255, ${a})` }}
                />
              ))}
            </span>
          </div>
        )}
      </div>
      {loading && <div className="text-sm text-muted py-6 text-center">…</div>}
      {!loading && empty && (
        <div className="text-sm text-muted py-6 text-center">
          {t('dashboard.aiTelemetry.overview.matrixEmpty')}
        </div>
      )}
      {!loading && !empty && (
        <div className="overflow-x-auto">
          <table className="text-xs border-separate" style={{ borderSpacing: 2 }}>
            <thead>
              <tr>
                <th
                  className="text-left text-muted font-normal sticky left-0 z-10 pr-3"
                  style={{ background: 'var(--bg-card)' }}
                />
                {topDomains.map(d => (
                  <th
                    key={d.domain}
                    className="font-normal text-secondary tabular-nums text-[10px] px-1 align-bottom"
                    style={{ minWidth: 42 }}
                  >
                    <div
                      className="whitespace-nowrap leading-tight inline-block origin-bottom-left"
                      style={{
                        transform: 'rotate(-45deg)',
                        transformOrigin: 'bottom left',
                        height: 70,
                        paddingTop: 14,
                      }}
                    >
                      {d.domain}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {engines.map(e => {
                const row = matrix[e] || {};
                return (
                  <tr key={e}>
                    <td
                      className="text-primary sticky left-0 font-medium pr-3 whitespace-nowrap"
                      style={{ background: 'var(--bg-card)' }}
                    >
                      <span className="flex items-center gap-1.5">
                        <span
                          className="inline-block w-2 h-2 rounded-full flex-shrink-0"
                          style={{ background: ENGINE_COLORS[e] || '#888' }}
                        />
                        {t(`dashboard.aiTelemetry.engine.${e}`, e)}
                      </span>
                    </td>
                    {topDomains.map(d => {
                      const v = row[d.domain] || 0;
                      return (
                        <td
                          key={d.domain}
                          className="text-center tabular-nums rounded transition-transform hover:scale-110 cursor-default"
                          style={{
                            background: cellBg(v),
                            color: v >= maxVal * 0.55 ? 'white' : (v === 0 ? 'transparent' : 'var(--text-primary)'),
                            width: 42, height: 32,
                            fontWeight: v >= maxVal * 0.7 ? 600 : 500,
                            border: v === 0 ? '1px dashed var(--border-color)' : 'none',
                          }}
                          title={`${e} × ${d.domain}: ${v}`}
                        >
                          {v || '·'}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface KpiCardProps {
  label: string;
  value: number;
  unit?: string;
  delta: number | null;
  sparkline: number[];
  loading: boolean;
  fmt?: 'int' | 'float';
  /** 大数字的颜色:value 为正绿、负红 */
  accentByValue?: boolean;
  icon?: 'eye' | 'link' | 'trend' | 'cpu';
  hint?: string;
}

const KPI_ICONS: Record<string, ReactElement> = {
  eye: <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6} d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z M12 9a3 3 0 100 6 3 3 0 000-6z" />,
  link: <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6} d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71 M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />,
  trend: <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6} d="M23 6l-9.5 9.5-5-5L1 18 M17 6h6v6" />,
  cpu: <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6} d="M4 4h16v16H4z M9 9h6v6H9z M9 1v3 M15 1v3 M9 20v3 M15 20v3 M20 9h3 M20 14h3 M1 9h3 M1 14h3" />,
};

function KpiCard({ label, value, unit, delta, sparkline, loading, fmt, accentByValue, icon, hint }: KpiCardProps) {
  const display = fmt === 'int'
    ? Math.round(value).toLocaleString()
    : (Number.isInteger(value) ? value.toString() : value.toFixed(1));
  const accent = accentByValue
    ? (value > 0 ? 'text-emerald-500' : value < 0 ? 'text-rose-500' : 'text-primary')
    : 'text-primary';
  const hasSparkline = sparkline.length > 1 && sparkline.some(v => v > 0);
  const hasDelta = delta !== null && delta !== undefined;

  return (
    <div
      className="rounded-lg px-4 py-3 transition-all hover:shadow-md"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
      }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-secondary inline-flex items-center gap-1">
          {label}
          {hint && <InfoHint text={hint} />}
        </span>
        {icon && (
          <svg
            className="w-4 h-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor"
            style={{ color: 'var(--accent-primary)' }}
          >
            {KPI_ICONS[icon]}
          </svg>
        )}
      </div>
      <div className="flex items-baseline gap-1">
        <span className={`text-3xl font-semibold tabular-nums ${accent}`}>
          {loading ? '…' : (accentByValue && value > 0 ? '+' : '') + display}
        </span>
        {unit && <span className="text-sm text-muted">{unit}</span>}
      </div>
      {(hasDelta || hasSparkline) && (
        <div className="flex items-center justify-between mt-2 h-8">
          {hasDelta ? (
            <span className={`text-xs ${delta! >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
              {delta! >= 0 ? '↑' : '↓'} {Math.abs(delta!).toFixed(0)}%
            </span>
          ) : <span />}
          {hasSparkline && (
            <div className="w-20 h-8">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={sparkline.map((v, i) => ({ i, v }))}>
                  <defs>
                    <linearGradient id={`spark-${label}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--accent-primary)" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="var(--accent-primary)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone" dataKey="v"
                    stroke="var(--accent-primary)" fill={`url(#spark-${label})`}
                    strokeWidth={1.8} dot={false} isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TrendChart({ data, loading }: { data: Overview | null; loading: boolean }) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <div
        className="h-64 rounded-lg flex items-center justify-center text-sm text-muted"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
      >…</div>
    );
  }

  if (!data || data.engines.length === 0) {
    return (
      <div
        className="h-64 rounded-lg flex items-center justify-center text-sm text-muted px-4 text-center"
        style={{ background: 'var(--bg-card)', border: '1px dashed var(--border-color)' }}
      >
        {t('dashboard.aiTelemetry.overview.trendEmpty')}
      </div>
    );
  }

  const chartData = data.trend.map(p => {
    const row: any = { date: p.date.slice(5) };
    for (const e of data.engines) {
      row[e] = p.values[e] ?? 0;
    }
    return row;
  });

  // X 轴稀疏:总点数 ≤ 14 时全显示;否则每 N 个显示一次,目标 8-10 个 tick
  const totalPoints = chartData.length;
  const tickInterval = totalPoints <= 14 ? 0 : Math.ceil(totalPoints / 8) - 1;

  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
      }}
    >
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-sm font-medium text-primary inline-flex items-center gap-1">
          {t('dashboard.aiTelemetry.overview.trendTitle')}
          <InfoHint text={t('dashboard.aiTelemetry.overview.tipTrend')} />
        </h3>
        <div className="flex flex-wrap gap-3 text-xs">
          {data.engines.map(e => (
            <span key={e} className="flex items-center gap-1.5 text-secondary">
              <span
                className="inline-block w-2.5 h-2.5 rounded-full"
                style={{ background: ENGINE_COLORS[e] || '#888' }}
              />
              {t(`dashboard.aiTelemetry.engine.${e}`, e)}
            </span>
          ))}
        </div>
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 8, right: 24, left: 0, bottom: 4 }}>
            <defs>
              {data.engines.map(e => (
                <linearGradient key={e} id={`g-${e}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={ENGINE_COLORS[e] || '#888'} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={ENGINE_COLORS[e] || '#888'} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" opacity={0.3} vertical={false} />
            <XAxis
              dataKey="date"
              interval={tickInterval}
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
              axisLine={{ stroke: 'var(--border-color)' }}
              tickLine={false}
              padding={{ left: 8, right: 8 }}
            />
            <YAxis
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              allowDecimals={false}
              width={40}
            />
            <RTooltip
              contentStyle={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border-color)',
                borderRadius: 8,
                fontSize: 12,
                boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
              }}
              labelStyle={{ color: 'var(--text-primary)', fontWeight: 600 }}
              cursor={{ stroke: 'var(--accent-primary)', strokeDasharray: '3 3', strokeOpacity: 0.5 }}
            />
            <Legend wrapperStyle={{ display: 'none' }} />
            {data.engines.map(e => (
              <Line
                key={e}
                type="monotone"
                dataKey={e}
                stroke={ENGINE_COLORS[e] || '#888'}
                strokeWidth={2.2}
                dot={{ r: 3, strokeWidth: 0, fill: ENGINE_COLORS[e] || '#888' }}
                activeDot={{ r: 6, strokeWidth: 2, stroke: '#fff' }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── 跑批结果 ───────────────────────────────────────────────────

function ResultsTab({ topics, token, topicId, onTopicChange }: {
  topics: Topic[]; token: string;
  topicId: number | null; onTopicChange: (id: number | null) => void;
}) {
  const { t } = useTranslation();
  const setTopicId = onTopicChange;
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [responses, setResponses] = useState<ResponseRow[]>([]);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [loadingResp, setLoadingResp] = useState(false);

  useEffect(() => {
    if (topicId === null && topics.length > 0) setTopicId(topics[0].id);
  }, [topics, topicId, setTopicId]);

  useEffect(() => {
    if (topicId === null) return;
    setLoadingRuns(true);
    aiTelemetryApi.listRuns(topicId, token)
      .then(rs => {
        setRuns(rs);
        setRunId(rs[0]?.id ?? null);
      })
      .finally(() => setLoadingRuns(false));
  }, [topicId, token]);

  useEffect(() => {
    if (runId === null) { setResponses([]); return; }
    setLoadingResp(true);
    aiTelemetryApi.listResponses(runId, token)
      .then(setResponses)
      .finally(() => setLoadingResp(false));
  }, [runId, token]);

  if (topics.length === 0) {
    return <EmptyHint text={t('dashboard.aiTelemetry.results.noTopics')} />;
  }

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-input)', border: '1px solid var(--border-color)',
    color: 'var(--text-primary)',
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs text-secondary">
          {t('dashboard.aiTelemetry.results.selectTopic')}
          <select
            value={topicId ?? ''} onChange={e => setTopicId(Number(e.target.value))}
            className="ml-2 px-2 py-1 text-sm rounded" style={inputStyle}
          >
            {topics.map(tp => <option key={tp.id} value={tp.id}>{tp.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-secondary">
          {t('dashboard.aiTelemetry.results.selectRun')}
          <select
            value={runId ?? ''} onChange={e => setRunId(Number(e.target.value))}
            disabled={runs.length === 0}
            className="ml-2 px-2 py-1 text-sm rounded disabled:opacity-50" style={inputStyle}
          >
            {runs.map(r => (
              <option key={r.id} value={r.id}>
                {`#${r.id} ${r.status} · ${formatTime(r.started_at)} · ${r.response_count} 条`}
              </option>
            ))}
          </select>
        </label>
        {runId !== null && runs.find(r => r.id === runId) && (
          <RunStatusChip run={runs.find(r => r.id === runId)!} />
        )}
      </div>

      {loadingRuns && <div className="text-sm text-muted py-6 text-center">…</div>}
      {!loadingRuns && runs.length === 0 && (
        <EmptyHint text={t('dashboard.aiTelemetry.results.noRuns')} />
      )}

      {runs.length > 0 && (
        <ResponseTable
          responses={responses}
          loading={loadingResp}
          expanded={expanded}
          onToggle={(id) => {
            setExpanded(prev => {
              const next = new Set(prev);
              if (next.has(id)) next.delete(id); else next.add(id);
              return next;
            });
          }}
        />
      )}
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div
      className="py-12 text-center text-sm text-muted rounded-lg"
      style={{ background: 'var(--bg-card)', border: '1px dashed var(--border-color)' }}
    >
      {text}
    </div>
  );
}

function RunStatusChip({ run }: { run: RunSummary }) {
  const color = run.status === 'success' ? 'text-emerald-500'
    : run.status === 'failed' ? 'text-rose-500'
    : 'text-blue-500';
  return (
    <span className={`text-xs ${color}`}>
      ● {run.status}
      {run.finished_at && (
        <span className="text-muted ml-2">
          ({Math.max(1, Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000))}s)
        </span>
      )}
    </span>
  );
}

function ResponseTable({
  responses, loading, expanded, onToggle,
}: {
  responses: ResponseRow[]; loading: boolean;
  expanded: Set<number>; onToggle: (id: number) => void;
}) {
  const { t } = useTranslation();
  if (loading) return <div className="text-sm text-muted py-6 text-center">…</div>;
  if (responses.length === 0) return null;

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
    >
      <table className="w-full text-sm">
        <thead>
          <tr style={{ background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}>
            <th className="text-left px-3 py-2 font-medium w-8"></th>
            <th className="text-left px-3 py-2 font-medium">{t('dashboard.aiTelemetry.results.colEngine')}</th>
            <th className="text-left px-3 py-2 font-medium">{t('dashboard.aiTelemetry.results.colQuery')}</th>
            <th className="text-left px-3 py-2 font-medium">{t('dashboard.aiTelemetry.results.colAnswer')}</th>
            <th className="text-left px-3 py-2 font-medium">{t('dashboard.aiTelemetry.results.colCitations')}</th>
          </tr>
        </thead>
        <tbody>
          {responses.map(r => {
            const open = expanded.has(r.id);
            return (
              <Fragment key={r.id}>
                <tr
                  style={{ borderTop: '1px solid var(--border-color)', cursor: 'pointer' }}
                  onClick={() => onToggle(r.id)}
                >
                  <td className="px-3 py-2 text-muted">{open ? '▼' : '▶'}</td>
                  <td className="px-3 py-2 text-primary font-medium">
                    <EngineLabel id={r.engine} />
                  </td>
                  <td className="px-3 py-2 text-secondary max-w-[18rem] truncate">{r.query}</td>
                  <td className="px-3 py-2 text-secondary max-w-[28rem] truncate">
                    {r.error ? (
                      <span className="text-rose-500">⚠ {r.error}</span>
                    ) : (
                      r.answer || <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{r.citations.length}</td>
                </tr>
                {open && (
                  <tr style={{ borderTop: '1px solid var(--border-color)', background: 'var(--bg-secondary)' }}>
                    <td colSpan={5} className="px-4 py-3">
                      <ResponseDetail row={r} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function EngineLabel({ id }: { id: EngineId }) {
  const { t } = useTranslation();
  return <span>{t(`dashboard.aiTelemetry.engine.${id}`, id)}</span>;
}

function ResponseDetail({ row }: { row: ResponseRow }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2 text-sm">
      <div>
        <div className="text-xs text-muted mb-1">Answer</div>
        <div className="text-primary whitespace-pre-wrap leading-relaxed">
          {row.answer || <span className="text-muted">—</span>}
        </div>
      </div>
      <div>
        <div className="text-xs text-muted mb-1">Citations ({row.citations.length})</div>
        {row.citations.length === 0 ? (
          <div className="text-muted text-xs">{t('dashboard.aiTelemetry.results.noCitations')}</div>
        ) : (
          <ul className="text-xs space-y-1">
            {row.citations.map((c, i) => (
              <li key={i}>
                <span className="text-muted mr-2">[{i + 1}]</span>
                <a
                  href={c.url} target="_blank" rel="noreferrer"
                  className="hover:underline" style={{ color: 'var(--accent-primary)' }}
                >{c.title || c.url}</a>
                <span className="text-muted ml-2">· {c.domain}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ── 新建/编辑 Modal ───────────────────────────────────────────

interface TopicEditorProps {
  initial: Topic | null;
  token: string;
  mode?: 'edit' | 'view';
  onCancel: () => void;
  onSave: (payload: TopicPayload) => Promise<Topic>;
  // 回调可选接收 saved topic;admin 流程会用 saved.id 跳后续步骤。
  // 老 callsite(用户端)忽略参数,签名兼容。
  onSaveDone: (saved?: Topic) => void;
  // admin 替别人配主题:传 user_id 后,新建走 admin 通道直接 approved,
  // 跳过 submit-for-review;编辑沿用 onSave。
  adminTargetUserId?: number;
  // 项目进度看板把 6 段 chip 都接入这个 wizard,通过 initialStep 直跳对应步骤:
  // submit→1 / review→3 / diagnose→4 / plan→5 / content→6 / insight→7
  initialStep?: 1 | 2 | 3 | 4 | 5 | 6 | 7;
}

export function TopicEditor({
  initial, token, mode = 'edit', onCancel, onSave, onSaveDone, adminTargetUserId, initialStep,
}: TopicEditorProps) {
  const readOnly = mode === 'view';
  const { t } = useTranslation();
  // Phase D — 资料作为 Step 1 的核心;name/target/industry 从资料取值;只保留 aliases 单独输入
  const [profile, setProfile] = useState<BrandProfile>(
    () => ({ ...EMPTY_BRAND_PROFILE, ...(initial?.profile || {}) }),
  );
  // 资料里没有 aliases 字段,单独留一个文本输入 — 仅 topic 表用
  const name = profile.profile_name;
  const target = profile.company_short_name;
  const [aliasesText, setAliasesText] = useState((initial?.target_aliases || []).join(', '));
  // 没 topicId 时图片 / 视频先暂存在浏览器,持久化到 TopicEditor 这一层避免 step 切换丢失.
  // persistTopic 拿到 saved.id 后一次性 flush 到服务器.
  const [pendingMediaFiles, setPendingMediaFiles] = useState<File[]>([]);
  // 引擎选择 UI 已隐藏 — 默认走 5 个国内引擎,编辑场景保留原配置;
  // enabled 同样固定 true(产品口径:种子提示词都按每天跑)
  const engines = useMemo<Set<EngineId>>(
    () => new Set((initial?.engines && initial.engines.length > 0) ? initial.engines : CN_ENGINES),
    [initial?.engines],
  );
  const enabled = true;
  // 1-4 是编辑器 wizard 表单步;5-7 是项目进度下游(计划书 / 内容与投放 / 效果检查),内联展示.
  // initialStep 由 cockpit/项目进度 的 chip 链接 ?step=N 传入;5-7 需要 initial.id 否则退回 1.
  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5 | 6 | 7>(() => {
    const s = initialStep ?? 1;
    if (s >= 5 && !initial?.id) return 1;
    return s;
  });
  // 新建场景下 initial.id 为空,保存后才能拿到 id;step 4 健康报告组件依赖这个 id
  const [savedTopicId, setSavedTopicId] = useState<number | null>(initial?.id ?? null);
  const [saving, setSaving] = useState(false);
  // Step1「下一步」即落库:资料填完就建 draft / 存 profile,不拖到最后一次性保存。
  const [step1Saving, setStep1Saving] = useState(false);
  const [step1Err, setStep1Err] = useState<string | null>(null);

  // Query picker — 不再允许手填,候选全部走 DeepSeek 生成
  // 编辑场景:把 initial.queries 当作"已存在候选",默认勾选
  const SUGGEST_COUNT = 200;
  const QUERY_MAX_PICK = 200;
  // 种子提示词 — 多条,用户手填。Phase C 起会经过审核固化(已固化只能新增)
  const [seeds, setSeeds] = useState<string[]>(() =>
    (initial?.seed_prompts || []).map(s => s.text).filter(Boolean)
  );
  // industry 也从 profile 取(同步 profile.industry,跟 name/target 同源)
  const industry = profile.industry;
  const [suggesting, setSuggesting] = useState(false);
  const [suggestErr, setSuggestErr] = useState<string | null>(null);
  // 编辑场景:initial.queries 当作"已存在候选"塞进 suggestions(无分数);
  // 2026-05-20 起 picker 按 seed 分组,seed 来自 initial.query_seeds(legacy 为 "")。
  // 2026-05-28 起 scene 来自 initial.query_scene_types(legacy 为 search)
  const [suggestions, setSuggestions] = useState<QueryCandidate[]>(() => {
    const qs = initial?.queries || [];
    const seedsArr = initial?.query_seeds || [];
    const sceneArr = initial?.query_scene_types || [];
    return qs.map((text, i) => ({
      text, score: 0, sources: [],
      ...(seedsArr[i] ? { seed: seedsArr[i] } : {}),
      ...(sceneArr[i] ? { scene: sceneArr[i] } : {}),
    }));
  });
  const [collapsedSeeds, setCollapsedSeeds] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<Set<string>>(new Set(initial?.queries || []));
  const [queryFilter, setQueryFilter] = useState('');
  const [sortByScore, setSortByScore] = useState(true);
  // 2026-05-28 — 候选 scene filter:null 表示全显示,否则只显示选中的场景
  const [sceneFilter, setSceneFilter] = useState<SceneType | null>(null);

  const queries = useMemo(() => Array.from(picked).slice(0, QUERY_MAX_PICK), [picked]);
  const aliases = useMemo(
    () => aliasesText.split(/[,,\n]/).map(s => s.trim()).filter(Boolean).slice(0, 10),
    [aliasesText],
  );

  // 4 维场景计数 — 给场景 filter 按钮上的徽章用,显示每场景在 suggestions 池中的条数
  const sceneCounts = useMemo<Record<SceneType, number>>(() => {
    const c: Record<SceneType, number> = { search: 0, qa: 0, intent: 0, brand: 0 };
    for (const q of suggestions) {
      const s = q.scene;
      if (s && s in c) c[s] += 1;
    }
    return c;
  }, [suggestions]);

  const filteredSuggestions = useMemo(() => {
    const f = queryFilter.trim().toLowerCase();
    let out = suggestions;
    if (sceneFilter) out = out.filter(q => (q.scene || 'search') === sceneFilter);
    if (f) out = out.filter(q => q.text.toLowerCase().includes(f));
    if (sortByScore) {
      // 纯按评分降序;不再把已勾选项拉到顶部,免得用户每次勾/取消都看到位置漂移
      out = [...out].sort((a, b) => b.score - a.score);
    }
    return out;
  }, [suggestions, queryFilter, sortByScore, sceneFilter]);

  // 按种子提示词分组渲染。组顺序:先按 `seeds`(用户编辑器里现存的种子),再补
  // suggestions 里出现但 seeds 没列的(防止数据漂移)。
  // 只有 ≥2 个 seed 时才分组;单 seed / 零 seed 直接平铺。
  // q.seed 为空(legacy 或手动添加无 seed)的归"未分组",作为最后一组。
  const groupedBySeed = useMemo<{ seed: string; items: QueryCandidate[] }[] | null>(() => {
    const order: string[] = [];
    const seen = new Set<string>();
    for (const s of seeds) {
      const t = s.trim();
      if (t && !seen.has(t)) { seen.add(t); order.push(t); }
    }
    for (const q of suggestions) {
      const t = (q.seed || '').trim();
      if (t && !seen.has(t)) { seen.add(t); order.push(t); }
    }
    if (order.length < 2) return null;
    const groups: { seed: string; items: QueryCandidate[] }[] = order.map(s => ({ seed: s, items: [] }));
    const byKey = new Map(groups.map(g => [g.seed, g]));
    const ungrouped: QueryCandidate[] = [];
    for (const q of filteredSuggestions) {
      const t = (q.seed || '').trim();
      const g = t ? byKey.get(t) : undefined;
      if (g) g.items.push(q);
      else ungrouped.push(q);
    }
    const out = groups.filter(g => g.items.length > 0);
    if (ungrouped.length > 0) out.push({ seed: '', items: ungrouped });
    return out;
  }, [filteredSuggestions, seeds, suggestions]);

  const toggleSeedCollapse = (seed: string) => {
    setCollapsedSeeds(prev => {
      const next = new Set(prev);
      if (next.has(seed)) next.delete(seed); else next.add(seed);
      return next;
    });
  };
  const pickAllInSeed = (seed: string) => {
    setPicked(prev => {
      const next = new Set(prev);
      const items = suggestions.filter(q => (q.seed || '').trim() === seed);
      for (const q of items) {
        if (next.size >= QUERY_MAX_PICK) break;
        next.add(q.text);
      }
      return next;
    });
  };

  const pickedCap = picked.size >= QUERY_MAX_PICK;
  const valid = name.trim().length > 0 && target.trim().length > 0
    && queries.length > 0 && engines.size > 0;

  const buildPayload = (): TopicPayload => {
    // 按 queries 顺序回填 seed — suggestions 里 q.seed 是这条候选当时被哪条种子词扩展出来的。
    // backend `_queries_with_meta` 会把 seed 持久化进 queries_json[].seed。
    const textToSeed = new Map<string, string>();
    const textToScene = new Map<string, SceneType>();
    for (const q of suggestions) {
      if (q.seed && !textToSeed.has(q.text)) textToSeed.set(q.text, q.seed);
      if (q.scene && !textToScene.has(q.text)) textToScene.set(q.text, q.scene);
    }
    const query_seeds = queries.map(q => textToSeed.get(q) || '');
    const hasAnySeed = query_seeds.some(s => s);
    // 2026-06-11 — 场景标签同 seed 一样按 queries 顺序回填;缺省条目空串(后端忽略,沿用已有标签)
    const query_scene_types = queries.map(q => textToScene.get(q) || ('' as SceneType));
    const hasAnyScene = query_scene_types.some(s => s);
    // Phase C — 把所有种子词附带提交;后端去重 + 自动追加为 pending
    const seedTexts = seeds.map(s => s.trim()).filter(Boolean);
    return {
      name: name.trim(),
      target: target.trim(),
      target_aliases: aliases,
      industry: industry.trim(),
      queries,
      ...(hasAnySeed ? { query_seeds } : {}),
      ...(hasAnyScene ? { query_scene_types } : {}),
      engines: Array.from(engines),
      enabled,
      ...(seedTexts.length > 0 ? { seed_drafts: seedTexts } : {}),
      profile,
    };
  };

  // 把"保存"流程抽成纯函数,返回 saved topic;handleSave / handleSubmitForReview 复用
  const persistTopic = async (): Promise<Topic | null> => {
    if (!valid) return null;
    // step1 已可能建过 draft(savedTopicId);此时它和"编辑已有主题"一样走 update,
    // 不能再 create 否则会重复建一条。effectiveId 为空才是真·全新(admin 新建 / draft 没建成)。
    const effectiveId = savedTopicId ?? initial?.id ?? null;
    if (effectiveId) {
      const existingTexts = new Set(seedPrompts.map(s => s.text));
      const newSeeds = seeds.map(s => s.trim()).filter(s => s && !existingTexts.has(s));
      for (const s of newSeeds) {
        await handleSubmitSeed(s);
      }
    }
    // admin 替别人新建主题:走 admin 通道,seeds 一次性进 payload + 落库即 approved;
    // 跳过下面的 submitSeedPrompt 二次循环(那条接口会把 seed 强制设回 pending)。
    const isAdminNew = !effectiveId && typeof adminTargetUserId === 'number';
    let saved: Topic | null;
    if (effectiveId) {
      // 已有主题(含 step1 建的 draft)→ 增量更新;补 queries/engines + 走提交审核
      saved = await aiTelemetryApi.updateTopic(effectiveId, buildPayload(), token);
    } else if (isAdminNew) {
      saved = await aiTelemetryApi.adminCreateTopicForUser(adminTargetUserId, buildPayload(), token);
    } else {
      // 兜底:step1 没建成 draft 的全新主题,仍走 create
      saved = await onSave(buildPayload());
      if (saved?.id) {
        const cleanSeeds = seeds.map(s => s.trim()).filter(Boolean);
        for (const s of cleanSeeds) {
          try {
            await aiTelemetryApi.submitSeedPrompt(saved.id, s, token);
          } catch (e) {
            setSeedSubmitErr(e instanceof Error ? e.message : String(e));
          }
        }
      }
    }
    // 把浏览器里暂存的图片 / 视频 flush 到刚保存的 topic 上。
    // 失败一个不影响其它 — 错误聚合后通过 setSubmitErr 暴露,不阻断主流程。
    if (saved?.id && pendingMediaFiles.length > 0) {
      const failed: string[] = [];
      for (const f of pendingMediaFiles) {
        try {
          await topicProfileApi.uploadMedia(saved.id, f, token);
        } catch (e) {
          failed.push(`${f.name}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      if (failed.length > 0) {
        setSubmitErr(`部分素材上传失败:\n${failed.join('\n')}`);
      }
      setPendingMediaFiles([]);
    }
    return saved;
  };

  // 「保存」按钮已合并到「提交」(handleSubmitForReview),用户保存即触发审核。
  // 如未来要恢复"草稿保存"功能,可重新加 const handleSave = ... 包 persistTopic。

  // 「保存」— 去审核流后不再「提交审核」,统一只 save.admin 模式走 adminCreateTopicForUser,
  // 普通用户走 updateTopic.随后 onSaveDone 把保存好的 topic 传出去(供模态/外层用).
  const adminMode = typeof adminTargetUserId === 'number';
  const handleSubmitForReview = async () => {
    if (!valid || saving) return;
    setSaving(true); setSubmitErr(null);
    try {
      const saved = await persistTopic();
      if (saved?.id) setSavedTopicId(saved.id);
      // 顺序很关键:先 setStep(4) 再 onSaveDone,避免父组件关闭编辑器时 setStep 失效.
      // 父组件 onSaveDone 实现应不再 unmount 编辑器(由 step 4 的「完成」按钮负责关闭).
      setStep(4);
      onSaveDone(saved ?? undefined);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setSubmitErr(msg);
    } finally { setSaving(false); }
  };

  const handleSuggest = async () => {
    const validSeeds = selectedSeedsForMining;
    if (validSeeds.length === 0 || suggesting) return;
    setSuggesting(true);
    setSuggestErr(null);
    try {
      // 多个种子串行扇出;每个种子走 SSE 流式扩展 —— 某场景生成完就立刻把候选追加进 picker,
      // 不必等整包(慢模型下体验差别明显)。每条候选打上 `seed` 字段,picker 按 seed 分组渲染。
      // queries 全局去重(相同文本不同 seed 视作同一候选,沿用先到的 seed)。
      const seenText = new Set(suggestions.map(q => q.text));

      // 品牌基础词:瞬时模板拼接(品牌名 + 固定后缀),不走 LLM,点击即铺满。
      // 单独按品牌名分组、归 brand 场景;问品牌自己的词自有内容最容易覆盖。
      const brandName = target.trim();
      if (brandName) {
        const basicAdds: QueryCandidate[] = [];
        for (const text of buildBrandBasicQueries(brandName)) {
          if (seenText.has(text)) continue;
          seenText.add(text);
          basicAdds.push({ text, score: 0, sources: [], scene: 'brand', seed: brandName });
        }
        if (basicAdds.length) setSuggestions(prev => [...prev, ...basicAdds]);
      }

      for (let i = 0; i < validSeeds.length; i++) {
        await aiTelemetryApi.suggestQueriesStream({
          seed: validSeeds[i], count: SUGGEST_COUNT,
          target: target.trim(),
          aliases,
          industry: industry.trim(),
          // 主体类型 — 让后端按 服务/制造/品牌 切换扩展词措辞
          entity_type: profile.entity_type || '',
          // 资料里的服务地域 — 让 LLM 把地点维度锁在用户实际经营区域
          service_geo: (profile.service_geo || '').trim(),
          // 2026-05-28 — 画像字段透传给后端;后端按 scene 自动取舍:
          //   intent: 用 profile_cases(案例追溯型 query)
          //   brand:  全用(资质 / 标签 / 业务说明 + 案例)
          //   search / qa: 后端忽略,所以传了也不影响产出
          profile_cases: profile.case_stories || [],
          core_credentials: profile.core_credentials || [],
          brand_diff_tags: profile.brand_diff_tags || [],
          core_service_overview: profile.core_service_overview || '',
        }, token, (_scene, queries) => {
          // 某场景到货 — 去重后增量追加,UI 立即可见
          const additions: QueryCandidate[] = [];
          for (const q of queries) {
            if (seenText.has(q.text)) continue;
            seenText.add(q.text);
            additions.push({ ...q, seed: validSeeds[i] });
          }
          if (additions.length) setSuggestions(prev => [...prev, ...additions]);
        });
      }

      setCollapsedSeeds(new Set());
    } catch (e: unknown) {
      setSuggestErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSuggesting(false);
    }
  };

  // Phase C — 种子提示词审核固化:列表 + 提交 + 锁定 query 集
  const [seedPrompts, setSeedPrompts] = useState<SeedPrompt[]>(
    () => initial?.seed_prompts || []
  );
  const [seedSubmitErr, setSeedSubmitErr] = useState<string | null>(null);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  // step 3 用于挖掘候选的"种子选择" — 来源是 step 2 新加 + 服务端已固化的种子词;
  // 默认全选,用户在 step 3 可勾掉个别种子只针对剩下的去扇出
  const allSeedTexts = useMemo<string[]>(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const s of seedPrompts) {
      if (s.text && !seen.has(s.text)) { seen.add(s.text); out.push(s.text); }
    }
    for (const raw of seeds) {
      const t = raw.trim();
      if (t && !seen.has(t)) { seen.add(t); out.push(t); }
    }
    return out;
  }, [seedPrompts, seeds]);
  const [deselectedSeeds, setDeselectedSeeds] = useState<Set<string>>(() => new Set());
  const selectedSeedsForMining = useMemo<string[]>(
    () => allSeedTexts.filter(t => !deselectedSeeds.has(t)),
    [allSeedTexts, deselectedSeeds],
  );
  const toggleSeedSelection = (t: string) => {
    setDeselectedSeeds(prev => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };

  const lockedQueryTexts = useMemo<Set<string>>(() => {
    const out = new Set<string>();
    const qs = initial?.queries || [];
    const sts = initial?.query_statuses || [];
    qs.forEach((q, i) => { if (sts[i] === 'approved') out.add(q); });
    return out;
  }, [initial?.queries, initial?.query_statuses]);
  const queryStatusByText = useMemo<Map<string, ReviewStatus>>(() => {
    const m = new Map<string, ReviewStatus>();
    const qs = initial?.queries || [];
    const sts = initial?.query_statuses || [];
    qs.forEach((q, i) => { m.set(q, (sts[i] || 'approved') as ReviewStatus); });
    return m;
  }, [initial?.queries, initial?.query_statuses]);

  const handleSubmitSeed = async (rawText: string): Promise<boolean> => {
    const text = rawText.trim();
    // savedTopicId 初值即 initial?.id;step1 建草稿后变成草稿 id,种子也能立即落库
    const topicId = savedTopicId ?? initial?.id ?? null;
    if (!text || !topicId) return false;
    setSeedSubmitErr(null);
    try {
      const updated = await aiTelemetryApi.submitSeedPrompt(topicId, text, token);
      setSeedPrompts(updated.seed_prompts || []);
      return true;
    } catch (e: unknown) {
      setSeedSubmitErr(e instanceof Error ? e.message : String(e));
      return false;
    }
  };

  const togglePicked = (q: string) => {
    if (lockedQueryTexts.has(q)) return;   // approved 不允许取消勾选
    setPicked(prev => {
      const next = new Set(prev);
      if (next.has(q)) {
        next.delete(q);
      } else if (next.size < QUERY_MAX_PICK) {
        next.add(q);
      }
      return next;
    });
  };

  const clearPicked = () => setPicked(new Set());
  const clearSuggestions = () => {
    // 只清掉未勾选的候选,保留已勾选的(否则 valid 状态会瞬间崩)
    setSuggestions(prev => prev.filter(q => picked.has(q.text)));
  };

  const step1Valid = name.trim().length > 0 && target.trim().length > 0;
  const step2Valid = seeds.map(s => s.trim()).filter(Boolean).length > 0;

  // step1「下一步」即落库:资料(6 大模块)+ 名称/简称/行业立即存,不拖到 step3 才一次性保存。
  //   - 已有主题 / step1 已建过 draft → PUT /profile 增量存资料
  //   - 全新主题 → POST /topics/draft 建 draft 草稿,拿到 id 给后续 step 用
  //   - admin 替别人 / 只读 → 不预存,沿用 step3 权威保存(admin 走 adminCreate,避开锁状态校验)
  const persistStep1 = async () => {
    if (readOnly || typeof adminTargetUserId === 'number') { setStep(2); return; }
    if (step1Saving) return;
    setStep1Saving(true); setStep1Err(null);
    try {
      if (savedTopicId) {
        await topicProfileApi.updateProfile(savedTopicId, profile, token);
      } else {
        const saved = await aiTelemetryApi.createDraftTopic({
          name: name.trim(), target: target.trim(),
          target_aliases: aliases, industry: industry.trim(),
          engines: Array.from(engines), enabled, profile,
        }, token);
        if (saved?.id) setSavedTopicId(saved.id);
      }
      setStep(2);
    } catch (e) {
      setStep1Err(e instanceof Error ? e.message : String(e));
    } finally { setStep1Saving(false); }
  };

  const goNext = () => {
    if (step === 1 && step1Valid) { void persistStep1(); }
    else if (step === 2 && step2Valid) setStep(3);
    else if (step === 3 && valid) setStep(4);
    else if (step === 4 && savedTopicId) setStep(5);
    else if (step === 5 && savedTopicId) setStep(6);
    else if (step === 6 && savedTopicId) setStep(7);
  };
  const goPrev = () => {
    if (step === 7) setStep(6);
    else if (step === 6) setStep(5);
    else if (step === 5) setStep(4);
    else if (step === 4) setStep(3);
    else if (step === 3) setStep(2);
    else if (step === 2) setStep(1);
  };

  return (
    <section
      className="rounded-xl"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
    >
      <StepHeader
        step={step}
        onJump={(s) => {
          // 1-4:wizard 表单步,setStep 切表单
          if (s === 1) setStep(1);
          else if (s === 2 && step1Valid) setStep(2);
          else if (s === 3 && step1Valid && step2Valid) setStep(3);
          else if (s === 4 && step1Valid && step2Valid) setStep(4);
          // 5-7:项目进度下游阶段,内联展示;需要已保存的 topic_id
          else if (s >= 5 && savedTopicId) {
            setStep(s as 5 | 6 | 7);
          }
        }}
        labels={[
          t('dashboard.aiTelemetry.form.step1'),
          t('dashboard.aiTelemetry.form.step2'),
          t('dashboard.aiTelemetry.form.step3'),
          t('dashboard.aiTelemetry.form.step4'),
          t('dashboard.aiTelemetry.form.step5'),
          t('dashboard.aiTelemetry.form.step6'),
          t('dashboard.aiTelemetry.form.step7'),
        ]}
      />

      <div className="px-5 pt-3 pb-1 text-xs text-muted">
        {step === 1 && t('dashboard.aiTelemetry.form.step1Hint')}
        {step === 2 && t('dashboard.aiTelemetry.form.step2Hint')}
        {step === 3 && t('dashboard.aiTelemetry.form.step3Hint')}
        {step === 4 && t('dashboard.aiTelemetry.form.step4Hint')}
      </div>

      <div className="px-5 py-5">
        <fieldset disabled={readOnly} className="border-0 p-0 m-0 min-w-0">
        {step === 1 && (
          <div className="space-y-4">
            <p className="text-xs text-muted">
              {t('dashboard.aiTelemetry.form.profileHint')}
            </p>
            <ProfileImporter profile={profile} onApply={setProfile}
                             token={token} disabled={readOnly}
                             topicId={initial?.id}
                             pendingMediaFiles={pendingMediaFiles}
                             onPendingMediaFilesChange={setPendingMediaFiles}
                             onApplySeeds={suggestions => {
                               // LLM 顺手给的种子词候选 — 跟用户已填的合并去重(用户已填的优先保留)
                               setSeeds(prev => {
                                 const have = new Set(prev.map(s => s.trim()).filter(Boolean));
                                 const merged = [...prev];
                                 for (const s of suggestions) {
                                   if (s && !have.has(s)) { merged.push(s); have.add(s); }
                                 }
                                 return merged;
                               });
                             }} />
            {/* 6 模块资料表单(名称/简称/行业 同时是 topic.name/target/industry)
                别名(target_aliases)已收纳到「基础标识」tab 内,不再单独成节 */}
            <BrandProfileForm
              profile={profile}
              onChange={setProfile}
              readOnly={readOnly}
              aliasesText={aliasesText}
              onAliasesTextChange={setAliasesText}
              aliasesCount={aliases.length}
              aliasesLabel={t('dashboard.aiTelemetry.form.aliases')}
              aliasesPlaceholder={t('dashboard.aiTelemetry.form.aliasesPlaceholder') || ''}
              aliasesHint={t('dashboard.aiTelemetry.form.aliasesHint', { count: aliases.length })}
            />
          </div>
        )}

        {step === 2 && (
          <div className="max-w-2xl space-y-4">
            {/* Phase C — 已提交种子词的审核状态(编辑场景才显示) */}
            {seedPrompts.length > 0 && (
              <div
                className="rounded-md p-3 space-y-2"
                style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}
              >
                <div className="text-xs font-semibold text-secondary">
                  {t('dashboard.aiTelemetry.form.seedPromptsTitle')}
                </div>
                <ul className="space-y-1">
                  {seedPrompts.map((s, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs">
                      <ReviewBadge status={s.status} />
                      <span className="text-primary">{s.text}</span>
                      {s.submitted_at && (
                        <span className="text-muted ml-auto">
                          {new Date(s.submitted_at).toLocaleString()}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <label className="block">
              <span className="text-xs text-secondary">
                {t('dashboard.aiTelemetry.form.seedPromptsLabel')}*
              </span>
              <div className="mt-1.5">
                <TagInput
                  value={seeds}
                  onChange={setSeeds}
                  placeholder={t('dashboard.aiTelemetry.form.seedPromptsPlaceholder') || ''}
                  reserved={seedPrompts.map(s => s.text)}
                />
              </div>
              <span className="text-xs text-muted">
                {t('dashboard.aiTelemetry.form.seedPromptsListHint', { count: seeds.length })}
              </span>
            </label>

            {seedSubmitErr && (
              <div className="text-xs text-rose-500">⚠ {seedSubmitErr}</div>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="space-y-5">
            {/* ── 第 1 段:选种子 + 触发挖掘 ─────────────────────── */}
            <section
              className="rounded-md p-4 space-y-3"
              style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-primary">
                  {t('dashboard.aiTelemetry.form.expandSectionTitle')}
                </div>
                <span className="text-xs text-muted whitespace-nowrap">
                  {t('dashboard.aiTelemetry.form.seedPickerLabel', {
                    selected: selectedSeedsForMining.length,
                    total: allSeedTexts.length,
                  })}
                </span>
              </div>

              {allSeedTexts.length === 0 ? (
                <div
                  className="rounded-md p-3 text-xs text-muted"
                  style={{ background: 'var(--bg-input)', border: '1px dashed var(--border-color)' }}
                >
                  {t('dashboard.aiTelemetry.form.seedPickerEmpty')}
                </div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {allSeedTexts.map(t1 => {
                    const active = !deselectedSeeds.has(t1);
                    return (
                      <button
                        key={t1}
                        type="button"
                        onClick={() => toggleSeedSelection(t1)}
                        className="px-2.5 py-1 rounded-full text-xs"
                        style={{
                          background: active ? 'var(--accent-primary)' : 'var(--bg-input)',
                          color: active ? '#fff' : 'var(--text-secondary)',
                          border: '1px solid var(--border-color)',
                        }}
                      >
                        {active ? '✓ ' : ''}{t1}
                      </button>
                    );
                  })}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button" onClick={handleSuggest}
                  disabled={selectedSeedsForMining.length === 0 || suggesting}
                  className="px-4 py-2 rounded-md text-sm font-medium whitespace-nowrap disabled:opacity-50"
                  style={{ background: 'var(--accent-primary)', color: '#fff' }}
                >
                  {suggesting
                    ? t('dashboard.aiTelemetry.form.suggestRunningLong', { count: SUGGEST_COUNT })
                    : t('dashboard.aiTelemetry.form.suggestFromSeeds', { count: selectedSeedsForMining.length })}
                </button>
                <span className="text-xs text-muted">
                  {target.trim()
                    ? t('dashboard.aiTelemetry.form.suggestContextOn', { target: target.trim() })
                    : t('dashboard.aiTelemetry.form.suggestContextOff')}
                </span>
              </div>
              {suggestErr && (
                <div className="text-xs text-rose-500">⚠ {suggestErr}</div>
              )}
            </section>

            {/* ── 第 2 段:候选 Query 列表 ────────────────────────── */}
            <section
              className="rounded-md p-4 space-y-3"
              style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-primary">
                    {t('dashboard.aiTelemetry.form.candidateSectionTitle')}
                  </div>
                  <div className="text-xs text-muted mt-0.5">
                    {t('dashboard.aiTelemetry.form.queriesPickerHint', { max: QUERY_MAX_PICK, count: SUGGEST_COUNT })}
                  </div>
                </div>
                <span
                  className="text-sm font-mono tabular-nums shrink-0"
                  style={{ color: pickedCap ? 'var(--accent-primary)' : 'var(--text-secondary)' }}
                >
                  {picked.size} / {QUERY_MAX_PICK}
                </span>
              </div>

              {/* 手动添加 — 必须选一条种子提示词归属;写入 suggestions(score=0)
                  并打 seed 字段 + 自动勾进 picked. */}
              <ManualQueryAdder
                disabled={readOnly}
                pickedCap={pickedCap}
                seeds={allSeedTexts}
                addQuery={(text, seed, scene) => {
                  const v = text.trim();
                  if (!v) return false;
                  if (suggestions.some(q => q.text === v) || picked.has(v)) return false;
                  if (picked.size >= QUERY_MAX_PICK) return false;
                  setSuggestions(prev => [...prev, { text: v, score: 0, sources: [], seed, scene }]);
                  setPicked(prev => new Set(prev).add(v));
                  return true;
                }}
              />

              {suggestions.length === 0 ? (
                <div
                  className="rounded-md p-6 text-xs text-muted text-center"
                  style={{ background: 'var(--bg-input)', border: '1px dashed var(--border-color)' }}
                >
                  {t('dashboard.aiTelemetry.form.queriesPickerEmpty')}
                </div>
              ) : (
                <>
                  {/* 2026-05-28 — 4 维场景 filter:点 chip 单选一个场景查看,再点取消(回到全部) */}
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-muted">
                      {t('dashboard.aiTelemetry.form.sceneFilterLabel')}
                    </span>
                    <button
                      type="button" onClick={() => setSceneFilter(null)}
                      className="px-2 py-0.5 rounded-full text-xs"
                      style={{
                        background: sceneFilter === null ? 'var(--accent-primary)' : 'var(--bg-input)',
                        color: sceneFilter === null ? '#fff' : 'var(--text-secondary)',
                        border: '1px solid var(--border-color)',
                      }}
                    >
                      {t('dashboard.aiTelemetry.form.sceneFilterAll')}
                      <span className="ml-1 opacity-70">({suggestions.length})</span>
                    </button>
                    {SCENE_KEYS.map(s => {
                      const c = sceneCounts[s];
                      const isActive = sceneFilter === s;
                      const color = SCENE_COLORS[s];
                      return (
                        <button
                          key={s} type="button"
                          onClick={() => setSceneFilter(isActive ? null : s)}
                          disabled={c === 0}
                          className="px-2 py-0.5 rounded-full text-xs"
                          style={{
                            background: isActive ? color : `${color}33`,
                            color: isActive ? '#fff' : color,
                            border: `1px solid ${color}`,
                            fontWeight: 700,
                            opacity: c === 0 ? 0.6 : 1,
                            cursor: c === 0 ? 'not-allowed' : 'pointer',
                          }}
                        >
                          {t(`topic.profile.monitor.scene.${s}.label`)}
                          <span className="ml-1 opacity-80">({c})</span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="text" value={queryFilter} onChange={e => setQueryFilter(e.target.value)}
                      placeholder={t('dashboard.aiTelemetry.form.queriesFilterPlaceholder') || ''}
                      className="flex-1 px-3 py-1 rounded-md text-xs"
                      style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
                    />
                    <button
                      type="button" onClick={() => setSortByScore(s => !s)}
                      className="px-2 py-1 rounded text-xs whitespace-nowrap"
                      style={{
                        background: sortByScore ? 'var(--accent-primary)' : 'transparent',
                        color: sortByScore ? '#fff' : 'var(--text-secondary)',
                        border: '1px solid var(--border-color)',
                      }}
                    >
                      {sortByScore
                        ? t('dashboard.aiTelemetry.form.sortByScoreOn')
                        : t('dashboard.aiTelemetry.form.sortByScoreOff')}
                    </button>
                    <span className="text-xs text-muted whitespace-nowrap">
                      {t('dashboard.aiTelemetry.form.queriesFilterCount', {
                        shown: filteredSuggestions.length, total: suggestions.length,
                      })}
                    </span>
                  </div>
                  <div
                    className="overflow-y-auto rounded-md p-2"
                    style={{
                      maxHeight: 'clamp(360px, 60vh, 640px)',
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-color)',
                    }}
                  >
                    {(() => {
                      const renderRow = (q: QueryCandidate) => {
                        const isPicked = picked.has(q.text);
                        const isLocked = lockedQueryTexts.has(q.text);
                        const reviewStatus = queryStatusByText.get(q.text);
                        const disabled = isLocked || (!isPicked && pickedCap);
                        const showScore = q.score > 0;
                        const scoreColor = q.score >= 75 ? 'var(--accent-primary)'
                          : q.score >= 60 ? 'var(--text-primary)'
                          : 'var(--text-muted)';
                        return (
                          <label
                            key={q.text}
                            className="flex items-start gap-2 text-xs px-1 py-0.5 rounded"
                            style={{
                              cursor: isLocked ? 'default' : disabled ? 'not-allowed' : 'pointer',
                              opacity: !isLocked && disabled ? 0.4 : 1,
                              background: isPicked ? 'var(--bg-card)' : 'transparent',
                              color: 'var(--text-primary)',
                            }}
                            title={isLocked ? (t('dashboard.aiTelemetry.form.queryLockedHint') || '') : undefined}
                          >
                            <input
                              type="checkbox" checked={isPicked} disabled={disabled}
                              onChange={() => togglePicked(q.text)}
                              className="mt-0.5"
                            />
                            {showScore && (
                              <span
                                className="font-mono shrink-0 tabular-nums"
                                style={{ color: scoreColor, minWidth: '1.8rem' }}
                                title={q.sources.join(', ')}
                              >
                                {q.score}
                              </span>
                            )}
                            {/* 2026-05-28 — 4 维场景 badge;2026-06-04 改实心填充 + 白字,原 13% 半透明底太淡看不清 */}
                            {q.scene && (
                              <span
                                className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold leading-none tracking-wide"
                                style={{
                                  background: SCENE_COLORS[q.scene],
                                  color: '#fff',
                                  boxShadow: `0 1px 2px ${SCENE_COLORS[q.scene]}55`,
                                }}
                                title={t(`topic.profile.monitor.scene.${q.scene}.label`) as string}
                              >
                                {t(`topic.profile.monitor.scene.${q.scene}.label`)}
                              </span>
                            )}
                            <span className="break-all flex-1">{q.text}</span>
                            {reviewStatus && (
                              <span className="shrink-0"><ReviewBadge status={reviewStatus} /></span>
                            )}
                          </label>
                        );
                      };
                      if (!groupedBySeed) {
                        return (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-3 gap-y-1">
                            {filteredSuggestions.map(renderRow)}
                          </div>
                        );
                      }
                      return (
                        <div className="space-y-2">
                          {groupedBySeed.map(({ seed, items }) => {
                            const collapsed = collapsedSeeds.has(seed);
                            const pickedInGroup = items.filter(q => picked.has(q.text)).length;
                            const headerLabel = seed
                              || (t('dashboard.aiTelemetry.form.seedGroupUngrouped') || '未分组');
                            return (
                              <div key={seed || '__ungrouped__'}>
                                <div
                                  className="flex items-center gap-2 px-1 py-1 rounded sticky top-0"
                                  style={{
                                    background: 'var(--bg-secondary)',
                                    borderBottom: '1px solid var(--border-color)',
                                  }}
                                >
                                  <button
                                    type="button"
                                    onClick={() => toggleSeedCollapse(seed)}
                                    className="text-xs px-1"
                                    style={{ color: 'var(--text-secondary)', cursor: 'pointer' }}
                                  >
                                    {collapsed ? '▶' : '▼'}
                                  </button>
                                  <span className="text-xs font-medium break-all flex-1"
                                        style={{ color: 'var(--text-primary)' }}>
                                    {headerLabel}
                                  </span>
                                  <span className="text-xs font-mono tabular-nums shrink-0"
                                        style={{ color: 'var(--text-muted)' }}>
                                    {pickedInGroup} / {items.length}
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => pickAllInSeed(seed)}
                                    disabled={pickedCap}
                                    className="text-xs px-2 py-0.5 rounded shrink-0"
                                    style={{
                                      background: 'transparent',
                                      border: '1px solid var(--border-color)',
                                      color: 'var(--text-secondary)',
                                      opacity: pickedCap ? 0.4 : 1,
                                    }}
                                  >
                                    {t('dashboard.aiTelemetry.form.clusterPickAll')}
                                  </button>
                                </div>
                                {!collapsed && (
                                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-3 gap-y-1 pl-3 pt-1">
                                    {items.map(renderRow)}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      );
                    })()}
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <button
                      type="button" onClick={clearPicked} disabled={picked.size === 0}
                      className="px-2 py-1 rounded disabled:opacity-45"
                      style={{
                        background: 'transparent',
                        border: '1px solid var(--border-color)',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      {t('dashboard.aiTelemetry.form.queriesClearPicked')}
                    </button>
                    <button
                      type="button" onClick={clearSuggestions}
                      className="px-2 py-1 rounded"
                      style={{
                        background: 'transparent',
                        border: '1px solid var(--border-color)',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      {t('dashboard.aiTelemetry.form.queriesClearUnpicked')}
                    </button>
                  </div>
                </>
              )}
            </section>

            <p className="text-xs text-muted text-center">
              {t('dashboard.aiTelemetry.form.scheduleNote')}
            </p>
          </div>
        )}
        {step === 4 && (
          <HealthReportStep topicId={savedTopicId}
                            initialWebsite={profile.website || ''}
                            token={token} />
        )}
        {step === 5 && savedTopicId && (
          <ExecutionPlanView topicId={savedTopicId} />
        )}
        {step === 6 && savedTopicId && (
          <AdminContentReview lockedTopicId={savedTopicId} />
        )}
        {step === 7 && savedTopicId && (
          <TopicBriefingsEmbed topicId={savedTopicId} token={token} />
        )}
        {step >= 5 && !savedTopicId && (
          <div className="py-12 text-center text-sm text-muted">
            {t('dashboard.aiTelemetry.form.step4NoTopic')}
          </div>
        )}
        </fieldset>
      </div>

      <footer
        className="px-5 py-3 flex items-center justify-between gap-2"
        style={{ borderTop: '1px solid var(--border-color)' }}
      >
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-sm rounded-md text-secondary">
          {t('dashboard.aiTelemetry.form.cancel')}
        </button>
        <div className="flex items-center gap-2">
          {step > 1 && (
            <button
              type="button" onClick={goPrev}
              className="px-3 py-1.5 text-sm rounded-md"
              style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', border: '1px solid var(--border-color)' }}
            >
              ← {t('dashboard.aiTelemetry.form.prev')}
            </button>
          )}
          {(step < 3 || (step >= 4 && step < 7 && !!savedTopicId)) && (
            <button
              type="button" onClick={goNext}
              disabled={(step === 1 && (!step1Valid || step1Saving)) || (step === 2 && !step2Valid)}
              className="px-3 py-1.5 text-sm rounded-md text-white disabled:opacity-40"
              style={{ background: 'var(--accent-primary)' }}
            >
              {step === 1 && step1Saving ? '…' : `${t('dashboard.aiTelemetry.form.next')} →`}
            </button>
          )}
          {step === 3 && !readOnly && (
            <button
              type="button" onClick={handleSubmitForReview} disabled={!valid || saving}
              className="px-3 py-1.5 text-sm rounded-md text-white disabled:opacity-40"
              style={{ background: 'var(--accent-primary)' }}
            >
              {saving
                ? '…'
                : t(
                  adminMode
                    ? 'dashboard.aiTelemetry.form.adminCreate'
                    : 'dashboard.aiTelemetry.form.submit',
                )}
            </button>
          )}
          {step >= 4 && (
            <button
              type="button" onClick={onCancel}
              className="px-3 py-1.5 text-sm rounded-md text-white"
              style={{ background: 'var(--accent-primary)' }}
            >
              {t('dashboard.aiTelemetry.form.done')}
            </button>
          )}
        </div>
      </footer>
      {submitErr && (
        <div className="px-5 pb-3 text-xs" style={{ color: '#ef4444' }}>
          ⚠ {submitErr}
        </div>
      )}
      {step1Err && (
        <div className="px-5 pb-3 text-xs" style={{ color: '#ef4444' }}>
          ⚠ {step1Err}
        </div>
      )}
    </section>
  );
}

function ManualQueryAdder({
  disabled, pickedCap, seeds, addQuery,
}: {
  disabled: boolean;
  pickedCap: boolean;
  seeds: string[];
  addQuery: (text: string, seed: string, scene: SceneType) => boolean;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState('');
  const [chosenSeed, setChosenSeed] = useState<string>(seeds[0] || '');
  // 2026-06-11 — 手动添加也必须归属一个场景标签(搜索/问答/意图/品牌),默认搜索
  const [chosenScene, setChosenScene] = useState<SceneType>('search');
  const [hint, setHint] = useState<string | null>(null);

  // seeds 列表变化(用户在 step 2 新加/删除种子)时,若当前选中的不在了就重置
  useEffect(() => {
    if (!seeds.includes(chosenSeed)) setChosenSeed(seeds[0] || '');
  }, [seeds, chosenSeed]);

  const noSeeds = seeds.length === 0;
  const cantSubmit = disabled || pickedCap || noSeeds || !chosenSeed || !draft.trim();

  const submit = () => {
    if (noSeeds || !chosenSeed) {
      setHint(t('dashboard.aiTelemetry.form.manualAddNeedSeed')
        || '请先填一条种子提示词');
      return;
    }
    const v = draft.trim();
    if (!v) return;
    const ok = addQuery(v, chosenSeed, chosenScene);
    if (ok) {
      setDraft('');
      setHint(null);
    } else {
      setHint(
        pickedCap
          ? t('dashboard.aiTelemetry.form.manualAddCap')
          : t('dashboard.aiTelemetry.form.manualAddDuplicate'),
      );
    }
  };

  return (
    <div className="flex items-start gap-2">
      <select
        value={chosenSeed}
        onChange={e => { setChosenSeed(e.target.value); if (hint) setHint(null); }}
        disabled={disabled || pickedCap || noSeeds}
        className="px-2 py-1.5 rounded-md text-xs shrink-0"
        style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border-color)',
          color: 'var(--text-primary)',
          minWidth: 140, maxWidth: 220,
          opacity: (disabled || pickedCap || noSeeds) ? 0.5 : 1,
        }}
        title={noSeeds
          ? (t('dashboard.aiTelemetry.form.manualAddNeedSeed') || '请先填种子提示词')
          : (t('dashboard.aiTelemetry.form.manualAddSeedTitle') || '关联到种子提示词')}
      >
        {noSeeds ? (
          <option value="">
            {t('dashboard.aiTelemetry.form.manualAddSeedEmpty') || '无可用种子'}
          </option>
        ) : (
          seeds.map(s => <option key={s} value={s}>{s}</option>)
        )}
      </select>
      <select
        value={chosenScene}
        onChange={e => { setChosenScene(e.target.value as SceneType); if (hint) setHint(null); }}
        disabled={disabled || pickedCap || noSeeds}
        className="px-2 py-1.5 rounded-md text-xs shrink-0"
        style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border-color)',
          color: SCENE_COLORS[chosenScene],
          minWidth: 84,
          opacity: (disabled || pickedCap || noSeeds) ? 0.5 : 1,
        }}
        title={t('dashboard.aiTelemetry.form.manualAddSceneTitle') || '场景标签'}
      >
        {SCENE_KEYS.map(s => (
          <option key={s} value={s}>{t(`topic.profile.monitor.scene.${s}.label`)}</option>
        ))}
      </select>
      <div className="flex-1">
        <input
          type="text" value={draft}
          disabled={disabled || pickedCap || noSeeds}
          onChange={e => { setDraft(e.target.value); if (hint) setHint(null); }}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submit(); } }}
          placeholder={t('dashboard.aiTelemetry.form.manualAddPlaceholder') || ''}
          className="w-full px-3 py-1.5 rounded-md text-xs"
          style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)',
                   color: 'var(--text-primary)', opacity: (disabled || pickedCap || noSeeds) ? 0.5 : 1 }}
        />
        {hint && <div className="mt-1 text-[11px]" style={{ color: '#f59e0b' }}>{hint}</div>}
      </div>
      <button
        type="button" onClick={submit}
        disabled={cantSubmit}
        className="px-3 py-1.5 text-xs rounded-md text-white whitespace-nowrap"
        style={{
          background: 'var(--accent-primary)',
          opacity: cantSubmit ? 0.4 : 1,
        }}
      >
        {t('dashboard.aiTelemetry.form.manualAddBtn')}
      </button>
    </div>
  );
}

function StepHeader({
  step, labels, onJump,
}: {
  step: number;
  labels: string[];
  onJump: (s: number) => void;
}) {
  return (
    <div
      className="px-5 py-4 flex items-center gap-2"
      style={{ borderBottom: '1px solid var(--border-color)' }}
    >
      {labels.map((label, i) => {
        const idx = i + 1;
        const isActive = idx === step;
        const isDone = idx < step;
        const dotBg = isActive
          ? 'var(--accent-primary)'
          : isDone ? 'var(--accent-primary)' : 'var(--bg-input)';
        const dotColor = isActive || isDone ? '#fff' : 'var(--text-muted)';
        const labelColor = isActive
          ? 'var(--text-primary)'
          : isDone ? 'var(--text-secondary)' : 'var(--text-muted)';
        return (
          <Fragment key={idx}>
            <button
              type="button"
              onClick={() => onJump(idx)}
              className="flex items-center gap-2 px-1 py-0.5 rounded"
              style={{ cursor: 'pointer' }}
            >
              <span
                className="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-semibold"
                style={{
                  background: dotBg,
                  color: dotColor,
                  border: isActive ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
                }}
              >
                {isDone ? '✓' : idx}
              </span>
              <span
                className="text-sm"
                style={{ color: labelColor, fontWeight: isActive ? 600 : 400 }}
              >
                {label}
              </span>
            </button>
            {i < labels.length - 1 && (
              <span
                className="flex-1 h-px mx-1"
                style={{
                  background: idx < step ? 'var(--accent-primary)' : 'var(--border-color)',
                  maxWidth: '6rem',
                }}
              />
            )}
          </Fragment>
        );
      })}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
//  v1 引用追踪 Tab
// ═══════════════════════════════════════════════════════════════

function TrackingTab({ topics, token, topicId, onTopicChange }: {
  topics: Topic[]; token: string;
  topicId: number | null; onTopicChange: (id: number | null) => void;
}) {
  const { t } = useTranslation();
  const setTopicId = onTopicChange;
  const [matrix, setMatrix] = useState<TrackingMatrix | null>(null);
  const [sov, setSoV] = useState<ShareOfVoice | null>(null);
  const [loading, setLoading] = useState(false);
  const [openCell, setOpenCell] = useState<{ query: string; engine: EngineId } | null>(null);

  useEffect(() => {
    if (topicId === null && topics.length > 0) setTopicId(topics[0].id);
  }, [topics, topicId, setTopicId]);

  useEffect(() => {
    if (topicId == null) return;
    setLoading(true);
    Promise.all([
      aiTelemetryApi.getTrackingMatrix(topicId, token),
      aiTelemetryApi.getShareOfVoice(topicId, 90, token).catch(() => null),
    ]).then(([m, s]) => {
      setMatrix(m);
      setSoV(s);
    }).finally(() => setLoading(false));
  }, [topicId, token]);

  if (topics.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-muted">
        {t('dashboard.aiTelemetry.tracking.noTopics')}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label className="text-xs text-secondary">{t('dashboard.aiTelemetry.tracking.selectTopic')}</label>
        <select
          value={topicId ?? ''} onChange={e => setTopicId(Number(e.target.value))}
          className="px-3 py-1.5 rounded-md text-sm"
          style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
        >
          {topics.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>

      {loading && <div className="py-12 text-center text-sm text-muted">…</div>}
      {!loading && matrix && (
        <>
          <TrackingHeader matrix={matrix} sov={sov} />
          <TimelineRow timeline={matrix.timeline} />
          <MatrixGrid matrix={matrix} onPick={(q, e) => setOpenCell({ query: q, engine: e })} />
        </>
      )}

      {openCell && topicId != null && (
        <CellDrawerView
          topicId={topicId} query={openCell.query} engine={openCell.engine}
          token={token} onClose={() => setOpenCell(null)}
        />
      )}
    </div>
  );
}

function TrackingHeader({ matrix, sov }: { matrix: TrackingMatrix; sov: ShareOfVoice | null }) {
  const { t } = useTranslation();
  const started = matrix.started_at ? new Date(matrix.started_at).toLocaleDateString() : '-';
  return (
    <div className="rounded-md p-3 text-xs flex flex-wrap items-center gap-x-4 gap-y-1"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}>
      <span className="text-secondary">
        {t('dashboard.aiTelemetry.tracking.targetLabel')}:
        <strong className="text-primary ml-1">{matrix.target || '-'}</strong>
        {matrix.target_aliases.length > 0 && (
          <span className="text-muted ml-1">
            ({matrix.target_aliases.join(' / ')})
          </span>
        )}
      </span>
      <span className="text-secondary">
        {t('dashboard.aiTelemetry.tracking.startedAt')}: <span className="text-primary">{started}</span>
      </span>
      <span className="text-secondary">
        {t('dashboard.aiTelemetry.tracking.totalRuns')}: <span className="text-primary tabular-nums">{matrix.total_runs}</span>
      </span>
      <span className="text-secondary">
        {t('dashboard.aiTelemetry.tracking.hitCells')}:
        <span className="text-primary tabular-nums ml-1">{matrix.hit_cells}</span>
        <span className="text-muted ml-0.5">/{matrix.total_cells}</span>
        <span className="ml-1 px-1.5 py-0.5 rounded text-[10px]"
          style={{ background: 'rgba(14,165,233,0.15)', color: 'var(--accent-primary)' }}>
          {matrix.hit_cells_pct.toFixed(1)}%
        </span>
      </span>
      {sov && (
        <>
          <span className="text-secondary">
            {t('dashboard.aiTelemetry.tracking.optimalRate')}:
            <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] font-bold"
              style={{
                background: sov.optimal_rate_pct >= 70
                  ? 'rgba(16,185,129,0.18)' : sov.optimal_rate_pct >= 40
                    ? 'rgba(245,158,11,0.18)' : 'rgba(239,68,68,0.18)',
                color: sov.optimal_rate_pct >= 70
                  ? '#10b981' : sov.optimal_rate_pct >= 40 ? '#f59e0b' : '#ef4444',
              }}>
              {sov.optimal_rate_pct.toFixed(1)}%
            </span>
          </span>
          <span className="text-secondary">
            {t('dashboard.aiTelemetry.tracking.saivLabel')}:
            <span className="text-primary tabular-nums ml-1">{sov.saiv_pct.toFixed(1)}%</span>
            <span className="text-muted ml-1">
              ({sov.brand_count} vs {sov.competitors_count_total})
            </span>
          </span>
        </>
      )}
    </div>
  );
}

function TimelineRow({ timeline }: { timeline: EngineFirstHit[] }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-md p-3 text-xs space-y-1.5"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="text-xs font-semibold text-secondary uppercase tracking-wider mb-1">
        {t('dashboard.aiTelemetry.tracking.timelineTitle')}
      </div>
      {timeline.map(e => {
        const hit = e.first_hit_at;
        return (
          <div key={e.engine} className="flex items-center gap-2">
            <span style={{
              display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
              background: hit ? '#10b981' : 'var(--border-color)',
            }} />
            <span className="w-20" style={{ color: ENGINE_COLORS[e.engine] }}>
              {t(`dashboard.aiTelemetry.engine.${e.engine}`)}
            </span>
            {hit ? (
              <>
                <span className="text-primary tabular-nums">
                  {new Date(hit).toLocaleDateString()}
                </span>
                <span className="text-muted">
                  · {t('dashboard.aiTelemetry.tracking.firstHitDay', { n: e.days_after_start ?? '?' })}
                </span>
                {e.first_hit_query && (
                  <span className="text-muted truncate flex-1">· {e.first_hit_query}</span>
                )}
              </>
            ) : (
              <span className="text-muted">{t('dashboard.aiTelemetry.tracking.notYet')}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function MatrixGrid({ matrix, onPick }: {
  matrix: TrackingMatrix;
  onPick: (query: string, engine: EngineId) => void;
}) {
  const { t } = useTranslation();
  const byKey = useMemo(() => {
    const m = new Map<string, QueryHitCell>();
    for (const c of matrix.cells) m.set(`${c.query}${c.engine}`, c);
    return m;
  }, [matrix.cells]);

  return (
    <div className="rounded-md overflow-x-auto"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <table className="text-xs border-collapse w-full">
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
            <th className="text-left px-3 py-2 font-medium text-secondary sticky left-0"
              style={{ background: 'var(--bg-card)', minWidth: 240 }}>
              {t('dashboard.aiTelemetry.tracking.queryEngineHeader')}
            </th>
            {matrix.engines.map(e => (
              <th key={e} className="px-3 py-2 font-medium text-center"
                style={{ color: ENGINE_COLORS[e] }}>
                {t(`dashboard.aiTelemetry.engine.${e}`)}
              </th>
            ))}
            <th className="px-3 py-2 font-medium text-center text-secondary">
              {t('dashboard.aiTelemetry.tracking.rowHits')}
            </th>
          </tr>
        </thead>
        <tbody>
          {matrix.queries.map(q => {
            let rowHits = 0;
            let rowTotal = 0;
            for (const e of matrix.engines) {
              const c = byKey.get(`${q}${e}`);
              if (c) { rowTotal += 1; if (c.total_hits >= 1) rowHits += 1; }
            }
            return (
              <tr key={q} style={{ borderBottom: '1px solid var(--border-color)' }}>
                <td className="px-3 py-2 sticky left-0" style={{ background: 'var(--bg-card)' }}>
                  <div className="truncate text-primary">{q}</div>
                </td>
                {matrix.engines.map(e => {
                  const cell = byKey.get(`${q}${e}`);
                  return (
                    <td key={e} className="px-1 py-1.5 text-center">
                      <CellBadge cell={cell} onClick={() => onPick(q, e)} />
                    </td>
                  );
                })}
                <td className="px-3 py-2 text-center text-secondary tabular-nums">
                  {rowHits}/{rowTotal}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="px-3 py-2 text-[11px] text-muted"
        style={{ borderTop: '1px solid var(--border-color)' }}>
        {t('dashboard.aiTelemetry.tracking.legend')}
      </div>
    </div>
  );
}

function CellBadge({ cell, onClick }: { cell: QueryHitCell | undefined; onClick: () => void }) {
  if (!cell || cell.status === 'pending') {
    return (
      <button type="button" onClick={onClick}
        className="px-2 py-1 rounded text-muted cursor-pointer"
        title="待做">⌛</button>
    );
  }
  if (cell.status === 'running') {
    return (
      <button type="button" onClick={onClick}
        className="px-2 py-1 rounded text-muted cursor-pointer"
        title="进行中">⏳</button>
    );
  }
  // done
  const hit = cell.total_hits >= 1;
  const date = cell.first_hit_at ? new Date(cell.first_hit_at).toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }) : '';
  return (
    <button type="button" onClick={onClick}
      className="px-2 py-1 rounded transition-colors cursor-pointer"
      style={{
        background: hit ? 'rgba(16,185,129,0.15)' : 'transparent',
        color: hit ? '#10b981' : 'var(--text-muted)',
        border: hit ? '1px solid rgba(16,185,129,0.4)' : '1px solid transparent',
      }}
      title={hit ? `${cell.total_hits}/${cell.total_runs} 命中` : `${cell.total_runs} 次跑批 0 命中`}>
      {hit ? `✓ ${date}` : '✕'}
    </button>
  );
}

// ── drawer:cell 详情 + 历次答复 + 诊断按钮 ────────────────────

function CellDrawerView({
  topicId, query, engine, token, onClose,
}: {
  topicId: number; query: string; engine: EngineId; token: string; onClose: () => void;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<CellDrawer | null>(null);
  const [insight, setInsight] = useState<CellInsight | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  useEffect(() => {
    aiTelemetryApi.getCellDrawer(topicId, query, engine, token).then(d => {
      setData(d);
      setInsight(d.insight);
    });
  }, [topicId, query, engine, token]);

  const handleAnalyze = async (force = false) => {
    setAnalyzing(true);
    try {
      const r = await aiTelemetryApi.fetchCellInsight(topicId, query, engine, token, force);
      setInsight(r);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleFeedback = async (f: 'helpful' | 'not_helpful' | 'wrong') => {
    if (!insight) return;
    await aiTelemetryApi.postCellInsightFeedback(insight.id, f, token);
    setInsight({ ...insight, feedback: f });
  };

  const node = (
    <div className="fixed inset-0 z-[1100] flex" onMouseDown={onClose}
      style={{ background: 'rgba(0,0,0,0.35)' }}>
      <div className="ml-auto h-full overflow-y-auto"
        style={{ width: 560, background: 'var(--bg-card)', borderLeft: '1px solid var(--border-color)' }}
        onMouseDown={e => e.stopPropagation()}>
        <header className="sticky top-0 px-5 py-3 flex items-center justify-between z-10"
          style={{ background: 'var(--bg-card)', borderBottom: '1px solid var(--border-color)' }}>
          <div>
            <div className="text-sm font-semibold text-primary">
              {t(`dashboard.aiTelemetry.engine.${engine}`)} · {query}
            </div>
            {data && (
              <div className="text-[11px] text-muted mt-0.5">
                {data.cell.total_hits}/{data.cell.total_runs} {t('dashboard.aiTelemetry.tracking.hits')}
                {data.cell.first_hit_at && (
                  <> · {t('dashboard.aiTelemetry.tracking.firstHit')}: {new Date(data.cell.first_hit_at).toLocaleDateString()}</>
                )}
              </div>
            )}
          </div>
          <button type="button" onClick={onClose} className="text-muted hover:text-primary text-lg px-2">✕</button>
        </header>

        <div className="px-5 py-4 space-y-4 text-xs">
          {!data && <div className="text-muted py-6 text-center">…</div>}

          {/* 诊断块(LLM) */}
          {data && (
            <section className="rounded-md p-3"
              style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}>
              <div className="flex items-center justify-between mb-2">
                <strong className="text-primary">🔍 {t('dashboard.aiTelemetry.insight.title')}</strong>
                {insight ? (
                  <button type="button" onClick={() => handleAnalyze(true)} disabled={analyzing}
                    className="text-[11px] text-muted hover:text-primary">
                    ↻ {t('dashboard.aiTelemetry.insight.refresh')}
                  </button>
                ) : (
                  <button type="button" onClick={() => handleAnalyze(false)} disabled={analyzing}
                    className="text-[11px] px-2 py-1 rounded text-white"
                    style={{ background: 'var(--accent-primary)' }}>
                    {analyzing ? '…' : t('dashboard.aiTelemetry.insight.analyze')}
                  </button>
                )}
              </div>
              {analyzing && <div className="text-muted">🤔 {t('dashboard.aiTelemetry.insight.analyzing')}</div>}
              {!analyzing && !insight && (
                <p className="text-muted">{t('dashboard.aiTelemetry.insight.empty')}</p>
              )}
              {insight && <InsightBlock insight={insight} onFeedback={handleFeedback} />}
            </section>
          )}

          {/* 历次答复 */}
          {data && data.evidence.length > 0 && (
            <section>
              <div className="text-xs font-semibold text-secondary uppercase tracking-wider mb-2">
                {t('dashboard.aiTelemetry.tracking.evidenceTitle')}
              </div>
              <div className="space-y-2">
                {data.evidence.map(e => <EvidenceCard key={e.response_id} ev={e} />)}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );

  return createPortal(node, document.body);
}

function InsightBlock({ insight, onFeedback }: {
  insight: CellInsight;
  onFeedback: (f: 'helpful' | 'not_helpful' | 'wrong') => void;
}) {
  const { t } = useTranslation();
  const verdictColor: Record<string, string> = {
    hit_stable: '#10b981', hit_unstable: '#f59e0b', near_miss: '#3b82f6',
    no_signal: '#9ca3af', negative_mention: '#ef4444',
  };
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] px-1.5 py-0.5 rounded font-bold"
          style={{ background: 'rgba(0,0,0,0.05)', color: verdictColor[insight.verdict] || '#9ca3af' }}>
          {t(`dashboard.aiTelemetry.insight.verdict.${insight.verdict}`)}
        </span>
        <span className="text-muted">{insight.llm_model}</span>
      </div>
      <p className="text-primary">{insight.summary}</p>

      {insight.competitors_top3.length > 0 && (
        <div>
          <div className="text-[11px] font-semibold text-muted uppercase mb-0.5">
            {t('dashboard.aiTelemetry.insight.competitors')}
          </div>
          <ul className="space-y-0.5 ml-3">
            {insight.competitors_top3.map((c, i) => (
              <li key={i} className="text-muted">
                ▸ <span className="text-primary">{c.name}</span>
                <span className="ml-1">({c.count})</span>
                {c.snippet && <span className="text-muted text-[11px] block ml-3">「{c.snippet}」</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {insight.answer_format && (
        <div className="text-muted">
          {t('dashboard.aiTelemetry.insight.format')}:
          <span className="text-primary ml-1">{insight.answer_format}</span>
        </div>
      )}

      {insight.citation_domains.length > 0 && (
        <div className="text-muted">
          {t('dashboard.aiTelemetry.insight.citationDomains')}:
          <span className="text-primary ml-1">{insight.citation_domains.slice(0, 6).join(' · ')}</span>
        </div>
      )}

      {insight.recommendations.length > 0 && (
        <div>
          <div className="text-[11px] font-semibold text-muted uppercase mb-1">
            {t('dashboard.aiTelemetry.insight.recommendations')}
          </div>
          <ul className="space-y-1.5">
            {insight.recommendations.map((r, i) => (
              <li key={i} className="rounded p-2"
                style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
                <span className="text-[10px] px-1.5 py-0.5 rounded font-bold mr-2"
                  style={{
                    background: r.priority === 'P0' ? '#ef4444' : r.priority === 'P1' ? '#f59e0b' : '#9ca3af',
                    color: 'white',
                  }}>{r.priority}</span>
                <strong className="text-primary">{r.title}</strong>
                <p className="mt-1 text-secondary">{r.action}</p>
                {r.why && <p className="mt-0.5 text-muted text-[11px]">— {r.why}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <span className="text-muted text-[11px]">{t('dashboard.aiTelemetry.insight.feedbackQ')}:</span>
        {(['helpful', 'not_helpful', 'wrong'] as const).map(f => (
          <button key={f} type="button" onClick={() => onFeedback(f)}
            className="text-[11px] px-2 py-0.5 rounded"
            style={{
              background: insight.feedback === f ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
              color: insight.feedback === f ? 'white' : 'var(--text-secondary)',
            }}>
            {f === 'helpful' ? '👍' : f === 'not_helpful' ? '👎' : '⚠'}
            {' '}{t(`dashboard.aiTelemetry.insight.feedback.${f}`)}
          </button>
        ))}
      </div>
    </div>
  );
}

function EvidenceCard({ ev }: { ev: CellDrawer['evidence'][number] }) {
  const { t } = useTranslation();
  const dt = ev.created_at ? new Date(ev.created_at).toLocaleString() : '';
  const posColor: Record<string, { bg: string; fg: string }> = {
    lead: { bg: 'rgba(16,185,129,0.18)', fg: '#10b981' },
    body: { bg: 'rgba(59,130,246,0.18)', fg: '#3b82f6' },
    tail: { bg: 'rgba(245,158,11,0.18)', fg: '#f59e0b' },
    unknown: { bg: 'rgba(156,163,175,0.18)', fg: '#9ca3af' },
  };
  const pos = ev.mention_position;
  return (
    <div className="rounded p-2"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="flex items-center gap-2 text-[11px] text-muted flex-wrap">
        <span className={ev.hit ? 'text-emerald-500' : 'text-muted'}>
          {ev.hit ? '✓' : '○'}
        </span>
        <span>{dt}</span>
        {ev.hit && pos && (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold"
            style={{
              background: (posColor[pos] || posColor.unknown).bg,
              color: (posColor[pos] || posColor.unknown).fg,
            }}>
            {t(`dashboard.aiTelemetry.insight.position.${pos}`)}
          </span>
        )}
        {ev.source_url && (
          <a href={ev.source_url} target="_blank" rel="noreferrer" className="text-primary hover:underline truncate">
            📎 {ev.source_url.replace(/^https?:\/\//, '').slice(0, 40)}…
          </a>
        )}
      </div>
      {ev.hit && ev.hit_excerpt && (
        <p className="mt-1 text-primary text-xs italic">「{ev.hit_excerpt}」</p>
      )}
      {!ev.hit && ev.answer && (
        <p className="mt-1 text-muted text-[11px] line-clamp-3">{ev.answer.slice(0, 200)}…</p>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
//  v1.2 优化建议(周报) Tab
// ═══════════════════════════════════════════════════════════════

function BriefingsTab({ topics, token }: { topics: Topic[]; token: string }) {
  const { t } = useTranslation();
  const [topicId, setTopicId] = useState<number | null>(topics[0]?.id ?? null);
  const [briefings, setBriefings] = useState<Briefing[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (topicId == null) return;
    setLoading(true);
    aiTelemetryApi.listBriefings(topicId, token).then(list => {
      setBriefings(list);
      setSelectedId(list[0]?.id ?? null);
    }).finally(() => setLoading(false));
  }, [topicId, token]);

  const selected = useMemo(
    () => briefings.find(b => b.id === selectedId) ?? null,
    [briefings, selectedId],
  );

  const handleGenerate = async () => {
    if (topicId == null) return;
    setGenerating(true);
    try {
      const fresh = await aiTelemetryApi.triggerBriefing(topicId, token);
      const list = await aiTelemetryApi.listBriefings(topicId, token);
      setBriefings(list);
      setSelectedId(fresh.id);
    } finally {
      setGenerating(false);
    }
  };

  if (topics.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-muted">
        {t('dashboard.aiTelemetry.briefings.noTopics')}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-xs text-secondary">{t('dashboard.aiTelemetry.briefings.selectTopic')}</label>
        <select
          value={topicId ?? ''} onChange={e => setTopicId(Number(e.target.value))}
          className="px-3 py-1.5 rounded-md text-sm"
          style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
        >
          {topics.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        {briefings.length > 0 && (
          <select value={selectedId ?? ''} onChange={e => setSelectedId(Number(e.target.value))}
            className="px-3 py-1.5 rounded-md text-sm"
            style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
            {briefings.map(b => (
              <option key={b.id} value={b.id}>
                {new Date(b.period_start).toLocaleDateString()} ~ {new Date(b.period_end).toLocaleDateString()}
              </option>
            ))}
          </select>
        )}
        <button type="button" onClick={handleGenerate} disabled={generating || topicId == null}
          className="text-xs px-3 py-1.5 rounded-md text-white"
          style={{ background: 'var(--accent-primary)' }}>
          {generating ? '…' : `📧 ${t('dashboard.aiTelemetry.briefings.regenerate')}`}
        </button>
      </div>

      {loading && <div className="py-12 text-center text-sm text-muted">…</div>}
      {!loading && briefings.length === 0 && (
        <div className="py-12 text-center text-sm text-muted">
          {t('dashboard.aiTelemetry.briefings.empty')}
        </div>
      )}
      {!loading && selected && <BriefingView briefing={selected} token={token} />}
    </div>
  );
}

// 嵌入版:固定 topicId,无 topic 选择器.用于 TopicEditor 7 步 wizard 的第 7 步.
function TopicBriefingsEmbed({ topicId, token }: { topicId: number; token: string }) {
  const { t } = useTranslation();
  const [briefings, setBriefings] = useState<Briefing[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    setLoading(true);
    aiTelemetryApi.listBriefings(topicId, token)
      .then(list => {
        setBriefings(list);
        setSelectedId(list[0]?.id ?? null);
      })
      .finally(() => setLoading(false));
  }, [topicId, token]);

  const selected = useMemo(
    () => briefings.find(b => b.id === selectedId) ?? null,
    [briefings, selectedId],
  );

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const fresh = await aiTelemetryApi.triggerBriefing(topicId, token);
      const list = await aiTelemetryApi.listBriefings(topicId, token);
      setBriefings(list);
      setSelectedId(fresh.id);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        {briefings.length > 0 && (
          <select value={selectedId ?? ''} onChange={e => setSelectedId(Number(e.target.value))}
            className="px-3 py-1.5 rounded-md text-sm"
            style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
            {briefings.map(b => (
              <option key={b.id} value={b.id}>
                {new Date(b.period_start).toLocaleDateString()} ~ {new Date(b.period_end).toLocaleDateString()}
              </option>
            ))}
          </select>
        )}
        <button type="button" onClick={handleGenerate} disabled={generating}
          className="text-xs px-3 py-1.5 rounded-md text-white disabled:opacity-50"
          style={{ background: 'var(--accent-primary)' }}>
          {generating ? '…' : `📧 ${t('dashboard.aiTelemetry.briefings.regenerate')}`}
        </button>
      </div>

      {loading && <div className="py-12 text-center text-sm text-muted">…</div>}
      {!loading && briefings.length === 0 && (
        <div className="py-12 text-center text-sm text-muted">
          {t('dashboard.aiTelemetry.briefings.empty')}
        </div>
      )}
      {!loading && selected && <BriefingView briefing={selected} token={token} />}
    </div>
  );
}

function BriefingView({ briefing, token }: { briefing: Briefing; token: string }) {
  const { t } = useTranslation();
  const [score, setScore] = useState<number | null>(briefing.feedback_score);

  const handleScore = async (n: number) => {
    setScore(n);
    await aiTelemetryApi.postBriefingFeedback(briefing.id, n, token);
  };

  return (
    <article className="rounded-md p-5"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <header className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-sm font-semibold text-primary">
          📰 {new Date(briefing.period_start).toLocaleDateString()} - {new Date(briefing.period_end).toLocaleDateString()}
        </h3>
        <span className="text-[11px] text-muted">
          {briefing.llm_model} · {t('dashboard.aiTelemetry.briefings.generatedAt')} {new Date(briefing.generated_at).toLocaleString()}
        </span>
      </header>

      <div className="prose prose-sm max-w-none text-primary whitespace-pre-wrap">
        {briefing.body_md}
      </div>

      {briefing.top_actions.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold text-secondary uppercase tracking-wider mb-2">
            🎯 {t('dashboard.aiTelemetry.briefings.topActions')}
          </div>
          <ul className="space-y-2">
            {briefing.top_actions.map((a, i) => (
              <li key={i} className="rounded p-2 text-xs"
                style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}>
                <span className="text-[10px] px-1.5 py-0.5 rounded font-bold mr-2"
                  style={{
                    background: a.priority === 'P0' ? '#ef4444' : a.priority === 'P1' ? '#f59e0b' : '#9ca3af',
                    color: 'white',
                  }}>{a.priority}</span>
                <strong className="text-primary">{a.title}</strong>
                <p className="mt-1 text-muted">{a.why}</p>
                <p className="mt-0.5 text-secondary">→ {a.how}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex items-center gap-2 text-xs">
        <span className="text-muted">{t('dashboard.aiTelemetry.briefings.rate')}:</span>
        {[1, 2, 3, 4, 5].map(n => (
          <button key={n} type="button" onClick={() => handleScore(n)}
            className="hover:scale-110 transition-transform">
            <span style={{ color: (score ?? 0) >= n ? '#f59e0b' : 'var(--text-muted)' }}>★</span>
          </button>
        ))}
      </div>
    </article>
  );
}

// TopicEditor step 4 — 内嵌健康诊断报告.idle 时显示生成按钮,generating 时轮询,ready 时
// 显示状态 + 跳转到完整报告页.不重复实现 AdminSolution 的全部 UI(那个 ~600 行),只做摘要 +
// 入口,真要看细节 admin 点「查看完整报告」跳走.
function HealthReportStep({ topicId, initialWebsite, token }: {
  topicId: number | null;
  initialWebsite: string;
  token: string;
}) {
  const { t, i18n } = useTranslation();
  const [sol, setSol] = useState<TopicStrategicSolution | null>(null);
  const [loaded, setLoaded] = useState(false);   // 首次拉完才能决定 UI,避免 idle 占位闪一下
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleExportPdf = async () => {
    if (!sol || sol.status !== 'ready' || exporting) return;
    setExporting(true); setErr(null);
    try { await exportSolutionPdf(sol, t, i18n.language || 'zh'); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setExporting(false); }
  };

  const handleExportDocx = async () => {
    if (!sol || sol.status !== 'ready' || exporting) return;
    setExporting(true); setErr(null);
    try { await exportSolutionDocx(sol, t, i18n.language || 'zh'); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setExporting(false); }
  };

  useEffect(() => {
    if (!topicId) { setLoaded(true); return; }
    let cancelled = false;
    let pollHandle: number | null = null;
    const tick = async () => {
      try {
        const s = await adminReviewApi.getStrategicSolution(topicId, token);
        if (cancelled) return;
        setSol(s);
        setLoaded(true);
        if (s.status !== 'generating' && pollHandle) {
          window.clearInterval(pollHandle);
          pollHandle = null;
        }
      } catch (e) {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : String(e));
          setLoaded(true);
        }
      }
    };
    tick();
    pollHandle = window.setInterval(tick, 3000);
    return () => {
      cancelled = true;
      if (pollHandle) window.clearInterval(pollHandle);
    };
  }, [topicId, token]);

  // 自动生成 — 不再让用户输入 website,直接用 topic 资料里填的(initialWebsite).
  // 空串也允许传:后端 generate 会走 4 块降级.
  const handleGenerate = async () => {
    if (!topicId || busy) return;
    setBusy(true); setErr(null);
    try {
      const s = await adminReviewApi.generateStrategicSolution(topicId, (initialWebsite || '').trim(), token);
      setSol(s);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!topicId) {
    return (
      <div className="rounded-md p-4 text-sm text-muted text-center"
           style={{ background: 'var(--bg-secondary)', border: '1px dashed var(--border-color)' }}>
        {t('dashboard.aiTelemetry.form.step4NoTopic')}
      </div>
    );
  }

  // 首次拉完前显示 loading,避免 idle 占位先闪一下再被 ready 替换.
  if (!loaded) {
    return (
      <div className="py-12 flex flex-col items-center gap-3 text-sm text-muted">
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-t-transparent"
             style={{ borderColor: 'var(--accent-primary)', borderTopColor: 'transparent' }} />
        <div>{t('common.loading')}</div>
      </div>
    );
  }

  const status = sol?.status || 'idle';
  return (
    <div className="space-y-3">
      {err && (
        <div className="rounded-md p-3 text-xs"
             style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                      border: '1px solid rgba(239,68,68,0.3)' }}>
          {err}
        </div>
      )}

      {status === 'idle' && (
        <div className="rounded-md p-4 space-y-3"
             style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}>
          <div className="text-sm text-secondary">
            {t('dashboard.aiTelemetry.form.step4Idle')}
          </div>
          <button type="button" disabled={busy}
                  onClick={handleGenerate}
                  className="px-3 py-1.5 text-sm rounded-md text-white disabled:opacity-40"
                  style={{ background: 'var(--accent-primary)' }}>
            {busy ? '…' : t('dashboard.aiTelemetry.form.step4Generate')}
          </button>
        </div>
      )}

      {status === 'generating' && (
        <div className="rounded-md p-4 flex items-center gap-3"
             style={{ background: 'rgba(99,102,241,0.10)', color: 'var(--accent-primary)',
                      border: '1px solid rgba(99,102,241,0.30)' }}>
          <div className="animate-spin rounded-full h-4 w-4 border-2 border-t-transparent"
               style={{ borderColor: 'var(--accent-primary)', borderTopColor: 'transparent' }} />
          <div className="text-sm">{t('dashboard.aiTelemetry.form.step4Generating')}</div>
        </div>
      )}

      {status === 'ready' && sol && (
        <div className="space-y-4">
          {/* 顶栏:状态条 + 导出 PDF / Word + 重新生成,完整内容直接在下方铺开 */}
          <div className="rounded-md p-3 flex items-center justify-between gap-3 flex-wrap"
               style={{ background: 'rgba(16,185,129,0.08)',
                        border: '1px solid rgba(16,185,129,0.30)' }}>
            <div className="text-sm text-primary">
              ✓ {t('dashboard.aiTelemetry.form.step4Ready', {
                at: sol.updated_at ? new Date(sol.updated_at).toLocaleString() : '',
              })}
            </div>
            <div className="flex items-center gap-2">
              <button type="button" disabled={exporting} onClick={handleExportPdf}
                      className="text-xs px-3 py-1.5 rounded-md text-white whitespace-nowrap disabled:opacity-50"
                      style={{ background: 'var(--accent-primary)' }}>
                {exporting ? t('admin.solution.exporting') : t('admin.solution.export')}
              </button>
              <button type="button" disabled={exporting} onClick={handleExportDocx}
                      className="text-xs px-3 py-1.5 rounded-md text-white whitespace-nowrap disabled:opacity-50"
                      style={{ background: '#2563eb' }}>
                {exporting ? t('admin.solution.exporting') : t('admin.solution.exportDocx')}
              </button>
              <button type="button" disabled={busy} onClick={handleGenerate}
                      className="text-xs px-3 py-1.5 rounded-md whitespace-nowrap"
                      style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>
                {t('dashboard.aiTelemetry.form.step4Regen')}
              </button>
            </div>
          </div>
          <SolutionView sol={sol} />
        </div>
      )}

      {status === 'failed' && (
        <div className="rounded-md p-4 space-y-3"
             style={{ background: 'rgba(239,68,68,0.08)',
                      border: '1px solid rgba(239,68,68,0.30)' }}>
          <div className="text-sm" style={{ color: '#ef4444' }}>
            {t('dashboard.aiTelemetry.form.step4Failed', { err: sol?.error || '—' })}
          </div>
          <button type="button" disabled={busy} onClick={handleGenerate}
                  className="px-3 py-1.5 text-sm rounded-md text-white"
                  style={{ background: 'var(--accent-primary)' }}>
            {t('dashboard.aiTelemetry.form.step4Regen')}
          </button>
        </div>
      )}
    </div>
  );
}
