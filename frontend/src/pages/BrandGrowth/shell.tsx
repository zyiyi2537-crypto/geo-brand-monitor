import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import { aiTelemetryApi, ALL_TIME_PERIOD, type Topic } from '../../services/aiTelemetryApi';
import { useAuth } from '../../contexts/AuthContext';
import { exportGrowthReportPdf } from '../../utils/exportGrowthReportPdf';
import { useBgLang, engineLabel, sortEngines, visibleEngines } from './lang';

export interface ShellState {
  token: string;
  topics: Topic[];
  topic: Topic | null;
  topicId: number | null;
  setTopicId: (id: number) => void;
  // 全部历史口径(自上线至今)— 不再有 7/30/90 切换,统一传 ALL_TIME_PERIOD
  period: number;
  // 模型多选(2026-05-21):空数组 = 全选/汇总语义
  selectedEngines: string[];
  setSelectedEngines: (es: string[]) => void;
  loading: boolean;
  // admin 正在看一个不属于自己的客户主题(?topic= 指向他人)→ 头部加「客户视角」提示
  isForeign: boolean;
}

export function useShellState(): ShellState {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isAdmin } = useAuth();
  const token = localStorage.getItem('token') || '';
  const [ownTopics, setOwnTopics] = useState<Topic[]>([]);
  // admin 看他人主题时单独解析的那条主题(?topic= 指向非自有主题)
  const [extraTopic, setExtraTopic] = useState<Topic | null>(null);
  const [loadingOwn, setLoadingOwn] = useState(true);
  const [resolving, setResolving] = useState(false);
  const loading = loadingOwn || resolving;

  const urlTopic = Number(searchParams.get('topic') || '0');
  const period = ALL_TIME_PERIOD;
  // 有 extraTopic 时只暴露这条客户主题(picker 显示客户主题名,语义清晰);否则用自有列表
  const topics = extraTopic ? [extraTopic] : ownTopics;
  const topicId = urlTopic > 0 ? urlTopic : (topics[0]?.id ?? null);
  const topic = topics.find(t => t.id === topicId) || null;

  // engines 参数:逗号分隔,空 / 缺省 = 全选语义
  const urlEnginesRaw = searchParams.get('engines') || '';
  const urlEngines = urlEnginesRaw
    .split(',').map(s => s.trim()).filter(Boolean);
  // 与 topic.engines 取交集兜底 — 切 topic 时上一份选择可能不再适用
  const topicEngines = topic?.engines ?? [];
  const selectedEngines = topicEngines.length === 0
    ? urlEngines
    : urlEngines.filter(e => topicEngines.includes(e as Topic['engines'][number]));

  useEffect(() => {
    if (!token) { setLoadingOwn(false); return; }
    setLoadingOwn(true);
    aiTelemetryApi.listTopics(token)
      .then(list => setOwnTopics(list))
      .catch(() => setOwnTopics([]))
      .finally(() => setLoadingOwn(false));
  }, [token]);

  // admin 访问不属于自己的主题 → 单独解析该主题。所有子页都用同一个 ?topic=<id>,
  // 所以只要这里统一兜底,整套面板(含下钻子页)都能看到客户数据,无需逐链接透传参数。
  useEffect(() => {
    if (loadingOwn) return;  // 等自有列表先加载完再判断,避免误把自有主题当外部主题
    if (!token || !isAdmin || urlTopic <= 0 || ownTopics.some(t => t.id === urlTopic)) {
      setExtraTopic(null);
      setResolving(false);
      return;
    }
    let cancelled = false;
    setResolving(true);
    aiTelemetryApi.getTopic(urlTopic, token)
      .then(t => { if (!cancelled) setExtraTopic(t); })
      .catch(() => { if (!cancelled) setExtraTopic(null); })
      .finally(() => { if (!cancelled) setResolving(false); });
    return () => { cancelled = true; };
  }, [token, isAdmin, urlTopic, ownTopics, loadingOwn]);

  const setTopicId = (id: number) => {
    const next = new URLSearchParams(searchParams);
    next.set('topic', String(id));
    setSearchParams(next, { replace: true });
  };
  const setSelectedEngines = (es: string[]) => {
    const next = new URLSearchParams(searchParams);
    if (es.length === 0) next.delete('engines');
    else next.set('engines', es.join(','));
    setSearchParams(next, { replace: true });
  };

  return {
    token, topics, topic, topicId, setTopicId, period,
    selectedEngines, setSelectedEngines, loading,
    isForeign: extraTopic != null,
  };
}

export function BrandGrowthHeader({
  title, breadcrumb, state,
}: {
  title: string;
  breadcrumb?: { label: string; to: string }[];
  state: ShellState;
}) {
  const navigate = useNavigate();
  const L = useBgLang();
  const subtitle = state.topic
    ? `${state.topic.name} · ${L.allTimeLabel}`
    : L.allTimeLabel;
  const isSubPage = (breadcrumb?.length ?? 0) > 0;
  const backTo = breadcrumb && breadcrumb.length > 0 ? breadcrumb[0].to : null;
  return (
    <div className="px-6 py-4 border-b backdrop-blur sticky top-16 z-30"
      style={{ borderColor: 'var(--border-color)', background: 'color-mix(in srgb, var(--bg-card) 90%, transparent)' }}>
      <div className="flex flex-wrap items-center gap-3 justify-between max-w-[1400px] mx-auto">
        <div className="flex items-center gap-3 min-w-0">
          {isSubPage && backTo ? (
            <button
              type="button"
              onClick={() => {
                if (window.history.length > 1) navigate(-1);
                else navigate(backTo);
              }}
              className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 hover:scale-105 transition"
              style={{ background: 'var(--bg-input)', color: 'var(--text-primary)', border: '1px solid var(--border-color)' }}
              title={L.back}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
          ) : (
            <span
              className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{
                background: 'linear-gradient(135deg, var(--accent-primary), color-mix(in srgb, var(--accent-primary) 60%, #8b5cf6))',
                color: 'white',
              }}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"
                  d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </span>
          )}
          <div className="flex flex-col min-w-0">
            {breadcrumb && breadcrumb.length > 0 && (
              <div className="text-[11px] text-muted truncate">
                {breadcrumb.map((b, i) => (
                  <span key={i}>
                    <Link to={b.to} className="hover:underline">{b.label}</Link>
                    {i < breadcrumb.length - 1 ? ' · ' : ''}
                  </span>
                ))}
                <span> · {title}</span>
              </div>
            )}
            <div className="flex items-baseline gap-2 min-w-0">
              <h1 className="text-lg font-semibold text-primary truncate">{title}</h1>
              <span className="text-xs text-muted truncate">{subtitle}</span>
              {state.isForeign && (
                <span
                  className="text-[11px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0"
                  style={{ background: 'rgba(59,130,246,0.12)', color: '#2563eb', border: '1px solid rgba(59,130,246,0.35)' }}
                >
                  {L.adminForeignTag}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <TopicPicker state={state} />
          <EngineChips state={state} />
          <LastRunBadge state={state} />
          <DownloadReportButton state={state} />
        </div>
      </div>
    </div>
  );
}

function TopicPicker({ state }: { state: ShellState }) {
  const L = useBgLang();
  if (state.topics.length === 0) {
    return <span className="text-xs text-muted">{L.noTopic}</span>;
  }
  return (
    <label className="text-xs text-secondary flex items-center gap-2">
      {L.topicPicker}
      <select
        value={state.topicId ?? ''}
        onChange={e => state.setTopicId(Number(e.target.value))}
        className="px-2 py-1 text-sm rounded"
        style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
      >
        {state.topics.map(t => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>
    </label>
  );
}

function EngineChips({ state }: { state: ShellState }) {
  const L = useBgLang();
  const topicEngines = sortEngines(visibleEngines(state.topic?.engines ?? []));
  if (topicEngines.length === 0) return null;
  const sole = state.selectedEngines.length === 1 ? state.selectedEngines[0] : null;
  const allActive =
    state.selectedEngines.length === 0 ||
    state.selectedEngines.length >= topicEngines.length;
  const chipStyle = (active: boolean) => ({
    background: active ? 'var(--accent-primary)' : 'transparent',
    color: active ? 'white' : 'var(--text-secondary)',
  });
  return (
    <div className="flex gap-1 p-0.5 rounded flex-wrap" style={{ background: 'var(--bg-input)' }}>
      <button
        type="button"
        onClick={() => state.setSelectedEngines([])}
        className="px-3 py-1 text-xs rounded"
        style={chipStyle(allActive)}
      >
        {L.engineSelectAll}
      </button>
      {topicEngines.map(eng => (
        <button
          key={eng}
          type="button"
          onClick={() => state.setSelectedEngines([eng])}
          className="px-3 py-1 text-xs rounded"
          style={chipStyle(sole === eng)}
        >
          {engineLabel(eng)}
        </button>
      ))}
    </div>
  );
}

// 上一次跑完出结果的时间 — 取代原 7/30/90 天切换。
function formatLastRun(topic: Topic | null, L: ReturnType<typeof useBgLang>): string {
  const iso = topic?.last_run_at;
  if (!iso) return L.lastRunNever;
  const zh = L.topicPicker === '主题';
  return new Date(iso).toLocaleString(zh ? 'zh-CN' : 'en-US', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

function LastRunBadge({ state }: { state: ShellState }) {
  const L = useBgLang();
  const text = formatLastRun(state.topic, L);
  return (
    <span
      className="px-3 py-1 text-xs rounded flex items-center gap-1.5"
      style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)' }}
      title={`${L.lastRunPrefix} ${text}`}
    >
      <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <circle cx="12" cy="12" r="9" strokeWidth="1.8" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M12 7v5l3 2" />
      </svg>
      <span className="truncate">{L.lastRunPrefix} {text}</span>
    </span>
  );
}

function DownloadReportButton({ state }: { state: ShellState }) {
  const L = useBgLang();
  const { t, i18n } = useTranslation();
  const [busy, setBusy] = useState(false);
  if (!state.topicId) return null;
  const onClick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const report = await aiTelemetryApi.getGrowthReport(state.topicId!, state.token);
      await exportGrowthReportPdf(report, t, i18n.language || 'zh');
    } catch {
      // 静默失败 — 不打断页面;按钮恢复可用让用户重试
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="px-3 py-1 text-xs rounded flex items-center gap-1.5 transition hover:opacity-90 disabled:opacity-60"
      style={{ background: 'var(--accent-primary)', color: 'white' }}
    >
      <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8"
          d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
      </svg>
      {busy ? L.downloadReportGenerating : L.downloadReport}
    </button>
  );
}

export function BrandGrowthShell({
  title, breadcrumb, children,
}: {
  title: string;
  breadcrumb?: { label: string; to: string }[];
  children: (state: ShellState) => React.ReactNode;
}) {
  const state = useShellState();
  return (
    <div className="min-h-[calc(100vh-4rem)]" style={{ background: 'var(--bg-primary)' }}>
      <PageHead titleKey="pageMeta.dashboard.title" descriptionKey="pageMeta.dashboard.description" />
      <BrandGrowthHeader title={title} breadcrumb={breadcrumb} state={state} />
      <ShellMain state={state}>{children}</ShellMain>
    </div>
  );
}

function ShellMain({ state, children }: {
  state: ShellState; children: (state: ShellState) => React.ReactNode;
}) {
  const L = useBgLang();
  return (
    <main className="px-6 py-6">
      <div className="max-w-[1400px] mx-auto">
        {state.loading ? (
          <div className="text-center py-20 text-muted">{L.loading}</div>
        ) : state.topics.length === 0 ? (
          <EmptyState />
        ) : (
          children(state)
        )}
      </div>
    </main>
  );
}

function EmptyState() {
  return (
    <div className="max-w-md mx-auto py-20 text-center">
      <div className="text-lg font-medium text-primary mb-2">还没有任何监测主题</div>
      <div className="text-sm text-muted mb-4">
        监测主题由管理员配置。请联系管理员为您的账户添加主题、种子提示词与扩展提示。
      </div>
    </div>
  );
}
