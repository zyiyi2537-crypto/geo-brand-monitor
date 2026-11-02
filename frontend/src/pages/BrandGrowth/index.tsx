import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BrandGrowthShell, type ShellState } from './shell';
import {
  aiTelemetryApi, type Overview, type PositionBreakdown, type PositionBreakdownResp,
  type Topic, type TrackingMatrix,
} from '../../services/aiTelemetryApi';
import { contentApi, type ContentDoc } from '../../services/contentApi';
import { useBgLang, engineLabel } from './lang';
import { InfoHint } from './charts';

export function BrandGrowth() {
  const L = useBgLang();
  return (
    <BrandGrowthShell title={L.pageTitle}>
      {(state) => <Body state={state} />}
    </BrandGrowthShell>
  );
}

function Body({ state }: { state: ShellState }) {
  const { token, topic, period } = state;
  const [overview, setOverview] = useState<Overview | null>(null);
  const [pb, setPb] = useState<PositionBreakdownResp | null>(null);
  const [matrix, setMatrix] = useState<TrackingMatrix | null>(null);
  const [published, setPublished] = useState<ContentDoc[]>([]);

  useEffect(() => {
    if (!topic) return;
    aiTelemetryApi.getOverview(topic.id, period, token).then(setOverview).catch(() => setOverview(null));
    aiTelemetryApi.getPositionBreakdown(topic.id, period, token).then(setPb).catch(() => setPb(null));
    aiTelemetryApi.getTrackingMatrix(topic.id, token).then(setMatrix).catch(() => setMatrix(null));
    contentApi.listDocs(topic.id, { status: 'published' }, token).then(setPublished).catch(() => setPublished([]));
  }, [token, topic?.id, period]);

  if (!topic) return null;

  return (
    <div className="grid gap-4 max-w-[1400px] mx-auto">
      <TopMetricsRow overview={overview} matrix={matrix} published={published} topic={topic}
        selectedEngines={state.selectedEngines} />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <RadarBlock pb={pb} selectedEngines={state.selectedEngines} />
        <EntryCardGrid overview={overview} pb={pb} />
        <CoreMetricsPanel pb={pb} selectedEngines={state.selectedEngines} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <TrackingDetailBlock matrix={matrix} topic={topic} />
        <PublishedFeedBlock published={published} topic={topic} />
      </div>
    </div>
  );
}

// ── 顶部 3 大数 ───────────────────────────────────────
function TopMetricsRow({ overview, matrix, published, topic, selectedEngines }: {
  overview: Overview | null; matrix: TrackingMatrix | null;
  published: ContentDoc[]; topic: Topic; selectedEngines: string[];
}) {
  const navigate = useNavigate();
  const L = useBgLang();
  // 推荐词总数 = 扩展的问题总数(全量,与引擎过滤无关)
  const recommendedQueryCount = matrix?.queries.length ?? 0;
  const publishedCount = published.length;

  // 引用总数:有 engine 过滤时从 trend 切片求和(per-engine citation),否则用 overview.value
  const allEngines = overview?.engines ?? [];
  const isFiltered =
    selectedEngines.length > 0 && selectedEngines.length < allEngines.length;
  const citationsTotal = (() => {
    if (!overview) return 0;
    if (!isFiltered) return overview.citations.value;
    let sum = 0;
    for (const t of overview.trend) {
      for (const eng of selectedEngines) {
        sum += (t.values as Record<string, number>)[eng] ?? 0;
      }
    }
    return sum;
  })();
  // 过滤后 delta 不准(后端按全量算),先隐藏
  const citationsDelta = isFiltered ? null : (overview?.citations.delta_pct ?? null);
  const tq = topic.id;
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <BigMetric
        label={L.metricCitations}
        value={recommendedQueryCount}
        hint={L.hintTopMetrics}
        onClick={() => navigate(`/brand-growth/queries?topic=${tq}`)}
      />
      <BigMetric label={L.metricPublishedTotal} value={publishedCount} hint={L.hintPublishedTotal}
        onClick={() => navigate(`/brand-growth/published?topic=${tq}`)} />
      <BigMetric label={L.metricCitedTotal} value={citationsTotal} delta={citationsDelta} hint={L.hintCitedTotal}
        onClick={() => navigate(`/brand-growth/sources?topic=${tq}`)} />
    </div>
  );
}

function BigMetric({ label, value, delta, onClick, hint, sub }: {
  label: string; value: number; delta?: number | null; onClick?: () => void; hint?: string; sub?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="p-5 rounded-lg text-left transition hover:scale-[1.01]"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
    >
      <div className="text-xs text-muted mb-2 flex items-center gap-1.5">
        {label}{hint && <InfoHint text={hint} />}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-3xl font-bold text-primary tabular-nums">{value.toLocaleString()}</span>
        {sub && <span className="text-xs text-muted">{sub}</span>}
        {typeof delta === 'number' && delta !== 0 && (
          <span className="text-xs tabular-nums"
            style={{ color: delta > 0 ? '#10b981' : '#ef4444' }}>
            {delta > 0 ? '↑' : '↓'} {Math.abs(delta).toFixed(1)}%
          </span>
        )}
      </div>
    </button>
  );
}

// 单 engine 筛选 helper — 返回该 engine 的 breakdown,否则返回全量汇总
function pickBreakdown(pb: PositionBreakdownResp, selectedEngines: string[]): PositionBreakdown {
  if (selectedEngines.length === 1) {
    const slice = pb.query_group?.by_engine.find(s => s.engine === selectedEngines[0]);
    if (slice) return slice.breakdown;
  }
  return pb.breakdown;
}

// ── 雷达(5 维)──────────────────────────────────────
function RadarBlock({ pb, selectedEngines }: {
  pb: PositionBreakdownResp | null;
  selectedEngines: string[];
}) {
  const navigate = useNavigate();
  const L = useBgLang();
  if (!pb) {
    return <CardShell title={L.blockRadar} hint={L.hintRadar}><div className="text-xs text-muted py-10 text-center">{L.sourcesNoData}</div></CardShell>;
  }
  const dims: { key: 'top5_pct' | 'visible_pct' | 'source_pct' | 'seed_coverage_pct'; label: string; layer: string }[] = [
    { key: 'visible_pct', label: L.metricVisible, layer: 'visible' },
    { key: 'source_pct', label: L.metricSource, layer: 'source' },
    { key: 'top5_pct', label: L.metricTop5, layer: 'top5' },
    { key: 'seed_coverage_pct', label: L.metricSeedCoverage, layer: 'seed' },
  ];
  const active = pickBreakdown(pb, selectedEngines);
  const isFiltered = selectedEngines.length === 1;
  const max = Math.max(1, ...dims.map(d => active[d.key]));
  const baseline = isFiltered ? null : pb.industry_baseline;
  // 简单 SVG 雷达
  const cx = 130, cy = 130, r = 100;
  const points = (vals: number[]) =>
    vals.map((v, i) => {
      const angle = (Math.PI * 2 / vals.length) * i - Math.PI / 2;
      const dist = (v / max) * r;
      return `${cx + Math.cos(angle) * dist},${cy + Math.sin(angle) * dist}`;
    }).join(' ');
  const labels = dims.map((d, i) => {
    const angle = (Math.PI * 2 / dims.length) * i - Math.PI / 2;
    const lx = cx + Math.cos(angle) * (r + 18);
    const ly = cy + Math.sin(angle) * (r + 18);
    return { ...d, lx, ly };
  });
  const brandPts = points(dims.map(d => active[d.key]));
  const basePts = baseline ? points(dims.map(d => baseline[d.key])) : null;

  return (
    <CardShell title={L.blockRadar} hint={L.hintRadar}>
      <div className="flex-1 flex items-center justify-center">
        <svg viewBox="-30 -30 320 320" className="w-full max-w-[260px]">
          {[0.25, 0.5, 0.75, 1].map(s => (
            <polygon
              key={s} fill="none" stroke="var(--border-color)" strokeWidth="0.5"
              points={points(dims.map(() => max * s))}
            />
          ))}
          {basePts && (
            <polygon fill="rgba(148,163,184,0.18)" stroke="rgba(148,163,184,0.6)" strokeWidth="1" points={basePts} />
          )}
          <polygon fill="rgba(59,130,246,0.25)" stroke="var(--accent-primary)" strokeWidth="1.5" points={brandPts} />
          {labels.map(l => (
            <text
              key={l.key} x={l.lx} y={l.ly}
              fontSize="9" textAnchor="middle" dominantBaseline="middle"
              fill="var(--text-secondary)"
              style={{ cursor: 'pointer' }}
              onClick={() => navigate(
                l.layer === 'seed'
                  ? `/brand-growth/queries?topic=${pb.topic_id}`
                  : `/brand-growth/matrix?topic=${pb.topic_id}&layer=${l.layer}`,
              )}
            >
              {l.label}
            </text>
          ))}
        </svg>
      </div>
    </CardShell>
  );
}

// ── 6 入口卡 ─────────────────────────────────────────
type EntryIconKind = 'sources' | 'engines' | 'competitors' | 'matrix' | 'insights' | 'queries';

function EntryIcon({ kind }: { kind: EntryIconKind }) {
  const sw = 1.8;
  switch (kind) {
    case 'sources':
      return (
        <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={sw}
            d="M4 6h16M4 12h10M4 18h7M19 14l3 3m0 0l-3 3m3-3H14" />
        </svg>
      );
    case 'engines':
      return (
        <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <rect x="3" y="4" width="18" height="13" rx="1.5" strokeWidth={sw} />
          <path strokeLinecap="round" strokeWidth={sw} d="M8 20h8M12 17v3" />
          <circle cx="8" cy="10.5" r="1.2" fill="currentColor" />
          <circle cx="12" cy="10.5" r="1.2" fill="currentColor" />
          <circle cx="16" cy="10.5" r="1.2" fill="currentColor" />
        </svg>
      );
    case 'competitors':
      return (
        <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={sw}
            d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
        </svg>
      );
    case 'matrix':
      return (
        <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth={sw} />
          <path strokeLinecap="round" strokeWidth={sw} d="M3 9h18M3 15h18M9 3v18M15 3v18" />
        </svg>
      );
    case 'insights':
      return (
        <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={sw}
            d="M9.66 17h4.68M12 3v1M19 6l-.7.7M21 12h-1M4 12H3M5.34 6.06l-.7-.7M8.5 14.4a5 5 0 117 0L15 15a3.4 3.4 0 00-1 2.5V18a2 2 0 01-4 0v-.5A3.4 3.4 0 009 15z" />
        </svg>
      );
    case 'queries':
      return (
        <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle cx="10.5" cy="10.5" r="6.5" strokeWidth={sw} />
          <path strokeLinecap="round" strokeWidth={sw} d="M20 20l-4.5-4.5" />
        </svg>
      );
  }
}

interface EntryCard {
  kind: EntryIconKind;
  title: string;
  sub: string;
  to: string;
  tint: { bg: string; fg: string };  // 图标贴片 + 图标颜色
}

function EntryCardGrid({ overview, pb }: { overview: Overview | null; pb: PositionBreakdownResp | null }) {
  const navigate = useNavigate();
  const L = useBgLang();
  const tid = overview?.topic_id ?? pb?.topic_id ?? 0;
  const cards: EntryCard[] = [
    {
      kind: 'sources', title: L.entrySources,
      sub: overview?.top_domains[0] ? `Top: ${overview.top_domains[0].domain}` : L.entrySourcesEmpty,
      to: `/brand-growth/sources?topic=${tid}`,
      tint: { bg: 'linear-gradient(135deg, rgba(20,184,166,0.18), rgba(20,184,166,0.32))', fg: '#0d9488' },
    },
    {
      kind: 'engines', title: L.entryEngines,
      sub: `${overview?.engines_covered.value ?? 0} / ${overview?.engines_total ?? 0} ${L.entryEnginesSub}`,
      to: `/brand-growth/engines?topic=${tid}`,
      tint: { bg: 'linear-gradient(135deg, rgba(59,130,246,0.18), rgba(59,130,246,0.32))', fg: '#2563eb' },
    },
    {
      kind: 'competitors', title: L.entryCompetitors,
      sub: L.entryCompetitorsSub,
      to: `/brand-growth/competitors?topic=${tid}`,
      tint: { bg: 'linear-gradient(135deg, rgba(249,115,22,0.18), rgba(249,115,22,0.32))', fg: '#ea580c' },
    },
    {
      kind: 'queries', title: L.entryQueries,
      sub: L.entryQueriesSub,
      to: `/brand-growth/queries?topic=${tid}`,
      tint: { bg: 'linear-gradient(135deg, rgba(168,85,247,0.18), rgba(168,85,247,0.32))', fg: '#9333ea' },
    },
  ];
  return (
    <div className="p-4 rounded-lg h-full"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="grid grid-cols-2 grid-rows-2 gap-3 h-full">
        {cards.map(c => (
          <button
            key={c.kind}
            type="button"
            onClick={() => navigate(c.to)}
            className="flex flex-col items-center justify-center gap-3 py-5 px-3 rounded-lg text-center hover:scale-[1.04] transition h-full"
            style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)' }}
          >
            <span
              className="w-16 h-16 rounded-xl flex items-center justify-center"
              style={{ background: c.tint.bg, color: c.tint.fg }}
            >
              <EntryIcon kind={c.kind} />
            </span>
            <div className="text-base font-medium text-primary">{c.title}</div>
            <div className="text-[11px] text-muted truncate w-full px-1">{c.sub}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── 右核心指标 4+1 ────────────────────────────────────
type MetricIconKind = 'medal' | 'eye' | 'star' | 'link';

function MetricIcon({ kind }: { kind: MetricIconKind }) {
  const sw = 1.8;
  switch (kind) {
    case 'medal':
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle cx="12" cy="14" r="5.5" strokeWidth={sw} />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={sw} d="M8 2l4 6 4-6" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={sw} d="M10 13l1.5 1.5L14 12" />
        </svg>
      );
    case 'eye':
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={sw}
            d="M2.5 12s3.5-7 9.5-7 9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z" />
          <circle cx="12" cy="12" r="2.5" strokeWidth={sw} />
        </svg>
      );
    case 'star':
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={sw}
            d="M12 3l2.6 5.3 5.9.85-4.25 4.15 1 5.85L12 16.4 6.75 19.15l1-5.85L3.5 9.15l5.9-.85L12 3z" />
        </svg>
      );
    case 'link':
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={sw}
            d="M10 13a5 5 0 007.07 0l3-3a5 5 0 00-7.07-7.07l-1 1M14 11a5 5 0 00-7.07 0l-3 3a5 5 0 007.07 7.07l1-1" />
        </svg>
      );
  }
}

interface MetricCard {
  key: 'seed_coverage_pct' | 'top3_pct' | 'top5_pct' | 'visible_pct' | 'source_pct';
  label: string;
  layer: string;     // 'seed' → /brand-growth/queries;其余 → /brand-growth/matrix?layer=*
  icon: MetricIconKind;
  tint: { bg: string; fg: string };
}

const METRIC_CARDS: MetricCard[] = [
  { key: 'seed_coverage_pct', label: '', layer: 'seed', icon: 'medal',
    tint: { bg: 'linear-gradient(135deg, rgba(16,185,129,0.12), rgba(16,185,129,0.22))', fg: '#10b981' } },
  { key: 'visible_pct', label: '', layer: 'visible', icon: 'eye',
    tint: { bg: 'linear-gradient(135deg, rgba(244,63,94,0.12), rgba(244,63,94,0.22))', fg: '#e11d48' } },
  { key: 'top5_pct', label: '', layer: 'top5', icon: 'star',
    tint: { bg: 'linear-gradient(135deg, rgba(20,184,166,0.12), rgba(20,184,166,0.22))', fg: '#0d9488' } },
  { key: 'source_pct', label: '', layer: 'source', icon: 'link',
    tint: { bg: 'linear-gradient(135deg, rgba(244,114,182,0.12), rgba(244,114,182,0.22))', fg: '#db2777' } },
];

function CoreMetricsPanel({ pb, selectedEngines }: {
  pb: PositionBreakdownResp | null;
  selectedEngines: string[];
}) {
  const navigate = useNavigate();
  const L = useBgLang();
  if (!pb) {
    return <CardShell title={L.blockCoreMetrics} hint={L.hintCoreMetrics}><div className="text-xs text-muted py-10 text-center">{L.sourcesNoData}</div></CardShell>;
  }
  const active = pickBreakdown(pb, selectedEngines);
  const isFiltered = selectedEngines.length === 1;
  const baseline = isFiltered ? null : pb.industry_baseline;
  const labelOf = (key: MetricCard['key']) => {
    if (key === 'seed_coverage_pct') return L.metricSeedCoverage;
    if (key === 'visible_pct') return L.metricVisible;
    if (key === 'top5_pct') return L.metricTop5;
    if (key === 'top3_pct') return L.metricTop3;
    return L.metricSource;
  };
  const hintOf = (key: MetricCard['key']) => {
    if (key === 'seed_coverage_pct') return L.hintMetricSeedCoverage;
    if (key === 'visible_pct') return L.hintMetricVisible;
    if (key === 'top5_pct') return L.hintMetricTop5;
    return L.hintMetricSource;
  };
  return (
    <CardShell title={L.blockCoreMetrics} hint={L.hintCoreMetrics}>
      <div className="grid grid-cols-2 grid-rows-2 gap-3 flex-1">
        {METRIC_CARDS.map(m => {
          const v = active[m.key];
          const bv = baseline ? baseline[m.key] : null;
          return (
            <button
              key={m.key}
              type="button"
              onClick={() => navigate(
                m.layer === 'seed'
                  ? `/brand-growth/queries?topic=${pb.topic_id}`
                  : `/brand-growth/matrix?topic=${pb.topic_id}&layer=${m.layer}`,
              )}
              className="p-3 rounded-lg text-left hover:scale-[1.03] transition flex flex-col gap-2 h-full"
              style={{ background: m.tint.bg, border: '1px solid var(--border-color)' }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0"
                  style={{ background: 'rgba(255,255,255,0.6)', color: m.tint.fg }}
                >
                  <MetricIcon kind={m.icon} />
                </span>
                <span className="text-xs font-medium flex items-center gap-1" style={{ color: m.tint.fg }}>
                  {labelOf(m.key)}
                  <InfoHint text={hintOf(m.key)} />
                </span>
              </div>
              <div className="text-2xl font-bold tabular-nums mt-auto" style={{ color: m.tint.fg }}>
                {v.toFixed(2)}%
              </div>
              {!isFiltered && bv !== null && (
                <div className="text-[10px] text-muted">
                  {`${L.industryLabel} ${bv.toFixed(2)}%`}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </CardShell>
  );
}

// ── 报告明细(监测问题命中明细) ────────────────────────
function TrackingDetailBlock({ matrix, topic }: { matrix: TrackingMatrix | null; topic: Topic }) {
  const L = useBgLang();
  // 每条 query 聚合命中引擎,优先展示已命中过的
  const rows = (matrix?.queries ?? []).map(q => {
    const cells = matrix?.cells.filter(c => c.query === q) ?? [];
    const hitEngines = cells
      .filter(c => c.total_hits > 0)
      .sort((a, b) => (a.first_hit_at || '').localeCompare(b.first_hit_at || ''))
      .map(c => c.engine);
    return { query: q, hitEngines };
  }).sort((a, b) => b.hitEngines.length - a.hitEngines.length);
  return (
    <CardShell
      title={L.blockBriefings} hint={L.hintBriefings}
      action={<Link to={`/brand-growth/queries?topic=${topic.id}`} className="text-xs text-accent">{L.viewAll}</Link>}
    >
      {rows.length === 0 ? (
        <div className="text-xs text-muted py-6 text-center">{L.emptyBriefings}</div>
      ) : (
        <ul className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
          {rows.slice(0, 6).map(r => (
            <li key={r.query} className="py-2">
              <Link to={`/brand-growth/queries?topic=${topic.id}`}
                className="text-sm text-primary hover:underline block truncate"
                title={r.query}>
                {r.query}
              </Link>
              <div className="text-[10px] text-muted flex flex-wrap gap-1 mt-0.5">
                {r.hitEngines.length === 0 ? (
                  <span>{L.queriesNeverHit}</span>
                ) : (
                  r.hitEngines.map(e => (
                    <span key={e}
                      className="px-1.5 py-0.5 rounded"
                      style={{ background: 'rgba(34,197,94,0.15)', color: '#15803d' }}>
                      {engineLabel(e)}
                    </span>
                  ))
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}

// ── 投放战果 ─────────────────────────────────────────
function PublishedFeedBlock({ published, topic }: { published: ContentDoc[]; topic: Topic }) {
  const L = useBgLang();
  return (
    <CardShell
      title={L.blockPublished} hint={L.hintPublished}
      action={<Link to={`/brand-growth/published?topic=${topic.id}`} className="text-xs text-accent">{L.viewAll}</Link>}
    >
      {published.length === 0 ? (
        <div className="text-xs text-muted py-6 text-center">{L.emptyPublished}</div>
      ) : (
        <ul className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
          {published.slice(0, 6).map(d => {
            const target = d.publish_targets?.[0];
            return (
              <li key={d.id} className="py-2">
                <a
                  href={target?.url || `/brand-growth/published?topic=${topic.id}&doc=${d.id}`}
                  target={target?.url ? '_blank' : undefined}
                  rel="noopener noreferrer"
                  className="text-sm text-primary hover:underline block truncate"
                >
                  {d.title}
                </a>
                <div className="text-[10px] text-muted">
                  {target ? `${target.platform} · ${target.media}` : '—'}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </CardShell>
  );
}

// ── shared ───────────────────────────────────────────
function CardShell({ title, action, hint, children }: {
  title: string; action?: React.ReactNode; hint?: string; children: React.ReactNode;
}) {
  return (
    <div className="p-4 rounded-lg h-full flex flex-col"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="flex items-center justify-between mb-4 pb-2.5 border-b flex-shrink-0"
        style={{ borderColor: 'var(--border-color)' }}>
        <h3 className="text-sm font-medium text-primary flex items-center gap-2">
          <span className="w-1 h-4 rounded-sm" style={{ background: 'var(--accent-primary)' }} />
          {title}
          {hint && <InfoHint text={hint} />}
        </h3>
        {action}
      </div>
      <div className="flex-1 flex flex-col">{children}</div>
    </div>
  );
}
