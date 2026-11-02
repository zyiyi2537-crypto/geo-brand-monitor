// Admin GEO 体检报告 — 基于官网技术诊断 + 品牌资料生成报告,可导出 PDF.
// 路由:/workbench/topics/:topicId/solution

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import { TopicStepper } from '../../components/TopicStepper';
import {
  adminReviewApi,
  type TopicStrategicSolution,
  type SolutionDiagnosisCluster,
  type SolutionExecutionLayer,
  type SolutionSevenStep,
  type SolutionKeywordTier,
  type SolutionVisionItem,
  type SolutionQueriesSnapshot,
} from '../../services/adminReviewApi';
import { exportSolutionPdf } from '../../utils/exportSolutionPdf';
import { exportSolutionDocx } from '../../utils/exportSolutionDocx';

const SEVERITY_STYLE: Record<string, { c: string; bg: string }> = {
  high: { c: '#ef4444', bg: 'rgba(239,68,68,0.10)' },
  med:  { c: '#eab308', bg: 'rgba(234,179,8,0.10)' },
  low:  { c: '#10b981', bg: 'rgba(16,185,129,0.10)' },
};

export function AdminSolution() {
  const { t, i18n } = useTranslation();
  const { topicId } = useParams();
  const token = localStorage.getItem('token') || '';
  const tid = Number(topicId);

  const [sol, setSol] = useState<TopicStrategicSolution | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [websiteUrl, setWebsiteUrl] = useState('');
  const [profileWebsite, setProfileWebsite] = useState<string>('');
  const pollRef = useRef<number | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const fetchOnce = useCallback(async () => {
    try {
      const s = await adminReviewApi.getStrategicSolution(tid, token);
      setSol(s);
      if (s.status !== 'generating') {
        stopPoll();
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      stopPoll();
    }
  }, [tid, token, stopPoll]);

  useEffect(() => {
    fetchOnce();
    return stopPoll;
  }, [fetchOnce, stopPoll]);

  // 生成开始或重试时,确保轮询在跑
  const ensurePolling = useCallback(() => {
    if (!pollRef.current) {
      pollRef.current = window.setInterval(fetchOnce, 3000);
    }
  }, [fetchOnce]);

  // sol.status 变 generating 时启动轮询
  useEffect(() => {
    if (sol?.status === 'generating') ensurePolling();
    else stopPoll();
  }, [sol?.status, ensurePolling, stopPoll]);

  // 当 sol 有 website_url 时初始化输入框(已生成过一次的复用)
  useEffect(() => {
    if (sol?.website_url && !websiteUrl) setWebsiteUrl(sol.website_url);
  }, [sol?.website_url, websiteUrl]);

  // 首次进入页面 — 从主题资料里读 website,自动填充输入框,admin 不用手填
  useEffect(() => {
    adminReviewApi.getTopicReview(tid, token)
      .then(d => {
        const w = (d.profile?.website || '').trim();
        if (w) setProfileWebsite(w);
      })
      .catch(() => {});
  }, [tid, token]);

  useEffect(() => {
    if (profileWebsite && !websiteUrl) setWebsiteUrl(profileWebsite);
  }, [profileWebsite, websiteUrl]);

  const handleGenerate = async () => {
    if (busy) return;
    const url = websiteUrl.trim();
    setBusy(true); setErr(null);
    try {
      const s = await adminReviewApi.generateStrategicSolution(tid, url, token);
      setSol(s);
      ensurePolling();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleExport = async () => {
    if (!sol || sol.status !== 'ready' || exporting) return;
    setExporting(true);
    try {
      await exportSolutionPdf(sol, t, i18n.language || 'zh');
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  const handleExportDocx = async () => {
    if (!sol || sol.status !== 'ready' || exporting) return;
    setExporting(true);
    try {
      await exportSolutionDocx(sol, t, i18n.language || 'zh');
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  const isReady = sol?.status === 'ready';
  const isGenerating = sol?.status === 'generating';
  const isFailed = sol?.status === 'failed';
  const isIdle = !sol || sol.status === 'idle';

  return (
    <div className="space-y-4">
      <PageHead titleKey="admin.solution.title" titleFallback="GEO策略优化方案" />
      <TopicStepper topicId={tid} active="solution" />
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-primary">{t('admin.solution.title')}</h1>
          <p className="text-xs text-secondary mt-0.5">{t('admin.solution.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          {isReady && (
            <>
              <button type="button" disabled={exporting} onClick={handleExport}
                      className="text-xs px-3 py-1.5 rounded-md text-white"
                      style={{ background: 'var(--accent-primary)', opacity: exporting ? 0.5 : 1 }}>
                {exporting ? t('admin.solution.exporting') : t('admin.solution.export')}
              </button>
              <button type="button" disabled={exporting} onClick={handleExportDocx}
                      className="text-xs px-3 py-1.5 rounded-md text-white"
                      style={{ background: '#2563eb', opacity: exporting ? 0.5 : 1 }}>
                {exporting ? t('admin.solution.exporting') : t('admin.solution.exportDocx')}
              </button>
              <button type="button" disabled={busy} onClick={handleGenerate}
                      className="text-xs px-3 py-1.5 rounded-md"
                      style={{ background: 'var(--bg-tertiary)', color: 'var(--accent-primary)',
                               opacity: busy ? 0.5 : 1 }}>
                {t('admin.solution.regenerate')}
              </button>
            </>
          )}
        </div>
      </header>

      {err && (
        <div className="rounded-md p-3 text-sm"
             style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                      border: '1px solid rgba(239,68,68,0.3)' }}>
          {err}
        </div>
      )}

      {!sol && !err && <div className="py-12 text-center text-sm text-muted">…</div>}

      {sol && (isIdle || isFailed) && (
        <GenerateForm
          websiteUrl={websiteUrl}
          setWebsiteUrl={setWebsiteUrl}
          busy={busy}
          isFailed={isFailed}
          error={sol.error}
          onSubmit={handleGenerate}
        />
      )}

      {isGenerating && (
        <div className="rounded-md p-4 text-sm"
             style={{ background: 'rgba(99,102,241,0.10)', color: 'var(--accent-primary)',
                      border: '1px solid rgba(99,102,241,0.30)' }}>
          <div className="flex items-center gap-2">
            <div className="animate-spin rounded-full h-4 w-4 border-2 border-t-transparent"
                 style={{ borderColor: 'var(--accent-primary)', borderTopColor: 'transparent' }} />
            <div>{t('admin.solution.generating')}</div>
          </div>
          <p className="text-xs mt-1.5 opacity-70">{t('admin.solution.generatingHint')}</p>
        </div>
      )}

      {isReady && sol && <SolutionView sol={sol} />}
    </div>
  );
}

// 「健康诊断报告」完整内容渲染.AdminSolution 页 + TopicEditor step 4 内嵌共用,
// 保证两个入口看到的内容/排版一致.
export function SolutionView({ sol }: { sol: TopicStrategicSolution }) {
  return (
    <div className="space-y-4">
      {sol.brand_snapshot && (
        <BrandSection sol={sol} />
      )}
      {sol.diagnosis && sol.diagnosis.clusters.length > 0 && (
        <>
          <DiagnosisSection sol={sol} />
          <ExecutionLayersSection layers={sol.diagnosis.execution_layers} />
        </>
      )}
      {sol.seven_steps.length > 0 && (
        <SevenStepsSection steps={sol.seven_steps} />
      )}
      {sol.keyword_tiers.length > 0 && (
        <KeywordsSection tiers={sol.keyword_tiers} />
      )}
      {sol.queries_snapshot && sol.queries_snapshot.queries.length > 0 && (
        <QueriesSection snapshot={sol.queries_snapshot} />
      )}
      {sol.vision.length > 0 && (
        <VisionSection items={sol.vision} />
      )}
      {sol.diagnosis && sol.diagnosis.all_checks.length > 0 && (
        <DetailsSection checks={sol.diagnosis.all_checks} />
      )}
    </div>
  );
}

function GenerateForm({
  websiteUrl, setWebsiteUrl, busy, isFailed, error, onSubmit,
}: {
  websiteUrl: string;
  setWebsiteUrl: (s: string) => void;
  busy: boolean;
  isFailed: boolean;
  error?: string | null;
  onSubmit: () => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="rounded-md p-5"
             style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <h2 className="text-sm font-semibold text-primary mb-1">
        {isFailed ? t('admin.solution.failed') : t('admin.solution.emptyState.title')}
      </h2>
      <p className="text-xs text-secondary mb-3">
        {isFailed && error
          ? error
          : t('admin.solution.emptyState.body')}
      </p>
      <label className="block text-xs font-medium text-secondary mb-1">
        {t('admin.solution.websiteLabel')}
      </label>
      <input type="url" value={websiteUrl}
             onChange={(e) => setWebsiteUrl(e.target.value)}
             onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); onSubmit(); } }}
             placeholder={t('admin.solution.websitePlaceholder')}
             disabled={busy}
             className="w-full text-sm px-3 py-2 rounded-md"
             style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                      border: '1px solid var(--border-color)' }} />
      <p className="text-[11px] text-muted mt-1">{t('admin.solution.websiteHint')}</p>
      <button type="button" disabled={busy} onClick={onSubmit}
              className="mt-3 text-xs px-4 py-2 rounded-md text-white"
              style={{ background: 'var(--accent-primary)', opacity: busy ? 0.5 : 1 }}>
        {isFailed ? t('admin.solution.retry') : t('admin.solution.generate')}
      </button>
    </section>
  );
}

function SectionCard({ title, children, action }: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="rounded-md p-4"
             style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="flex items-center justify-between mb-3 gap-3">
        <h2 className="text-sm font-semibold text-primary">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function BrandSection({ sol }: { sol: TopicStrategicSolution }) {
  const { t } = useTranslation();
  const bp = sol.brand_snapshot;
  if (!bp) return null;
  const rows: [string, unknown][] = [
    [t('admin.solution.brandFields.industry'), bp.industry],
    [t('admin.solution.brandFields.service_geo'), bp.service_geo],
    [t('admin.solution.brandFields.core_business_lines'),
      Array.isArray(bp.core_business_lines) ? bp.core_business_lines.join('、') : ''],
    [t('admin.solution.brandFields.target_scenarios'),
      Array.isArray(bp.target_scenarios) ? bp.target_scenarios.join('、') : ''],
    [t('admin.solution.brandFields.brand_diff_tags'),
      Array.isArray(bp.brand_diff_tags) ? bp.brand_diff_tags.join('、') : ''],
    [t('admin.solution.brandFields.brand_slogan'), bp.brand_slogan],
    [t('admin.solution.brandFields.core_message'), bp.core_message],
    [t('admin.solution.brandFields.core_service_overview'), bp.core_service_overview],
  ];
  const heading = bp.company_short_name || bp.company_full_name || bp.profile_name;
  return (
    <SectionCard title={t('admin.solution.section.brand')}>
      {heading && (
        <div className="text-base font-semibold text-primary mb-3">{heading}</div>
      )}
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {rows.filter(([_, v]) => v && String(v).trim()).map(([k, v]) => (
          <div key={k} className="flex items-start gap-2">
            <dt className="text-muted shrink-0 min-w-[88px]">{k}:</dt>
            <dd className="text-primary break-words leading-relaxed">{String(v)}</dd>
          </div>
        ))}
      </dl>
    </SectionCard>
  );
}

function scoreColor(s: number): string {
  if (s >= 90) return '#22c55e';
  if (s >= 75) return '#06b6d4';
  if (s >= 60) return '#eab308';
  if (s >= 40) return '#f97316';
  return '#ef4444';
}

function DiagnosisSection({ sol }: { sol: TopicStrategicSolution }) {
  const { t } = useTranslation();
  const d = sol.diagnosis!;
  return (
    <SectionCard title={t('admin.solution.section.diagnosis')}>
      <div className="flex gap-4 flex-wrap mb-4">
        <ScoreRing score={d.score} grade={d.grade} t={t} />
        <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-2 min-w-[280px]">
          <StatChip n={d.pass_count} label={t('admin.solution.passLabel')} c="#166534" bg="#dcfce7" />
          <StatChip n={d.warn_count} label={t('admin.solution.warnLabel')} c="#92400e" bg="#fef3c7" />
          <StatChip n={d.fail_count} label={t('admin.solution.failLabel')} c="#991b1b" bg="#fee2e2" />
          <StatChip n={d.info_count} label={t('admin.solution.infoLabel')} c="#1e40af" bg="#dbeafe" />
        </div>
      </div>
      <div className="space-y-3">
        {d.clusters.map((c) => (
          <ClusterCard key={c.key} cluster={c} />
        ))}
      </div>
    </SectionCard>
  );
}

function ScoreRing({ score, grade, t }: { score: number; grade: string; t: ReturnType<typeof useTranslation>['t'] }) {
  const radius = 50;
  const stroke = 8;
  const c = 2 * Math.PI * radius;
  const dash = c * (1 - score / 100);
  const color = scoreColor(score);
  return (
    <div className="rounded-lg px-4 py-3 flex items-center gap-3 shrink-0"
         style={{ background: 'linear-gradient(135deg,#0f172a,#312e81)' }}>
      <div className="relative" style={{ width: 100, height: 100 }}>
        <svg width="100" height="100" viewBox="0 0 120 120">
          <circle cx="60" cy="60" r={radius} fill="none" stroke="#1e293b" strokeWidth={stroke} />
          <circle cx="60" cy="60" r={radius} fill="none" stroke={color} strokeWidth={stroke}
                  strokeLinecap="round" strokeDasharray={c} strokeDashoffset={dash}
                  transform="rotate(-90 60 60)" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center text-white">
          <div className="text-2xl font-bold leading-none">{score}</div>
          <div className="text-[10px] opacity-60">/ 100</div>
        </div>
      </div>
      <div className="text-white">
        <div className="text-[10px] uppercase tracking-widest opacity-60">
          {t('admin.solution.scoreLabel')}
        </div>
        <div className="text-2xl font-bold mt-0.5" style={{ color }}>{grade || '—'}</div>
      </div>
    </div>
  );
}

function StatChip({ n, label, c, bg }: { n: number; label: string; c: string; bg: string }) {
  return (
    <div className="rounded-md py-2 px-3 text-center"
         style={{ background: bg }}>
      <div className="text-xl font-bold" style={{ color: c }}>{n}</div>
      <div className="text-[10px] font-semibold mt-0.5" style={{ color: c }}>{label}</div>
    </div>
  );
}

function ClusterCard({ cluster }: { cluster: SolutionDiagnosisCluster }) {
  const { t } = useTranslation();
  const sty = SEVERITY_STYLE[cluster.severity] || SEVERITY_STYLE.low;
  return (
    <div className="rounded-md p-3"
         style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <div className="font-semibold text-primary">{cluster.title_zh}</div>
        <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
              style={{ background: sty.bg, color: sty.c }}>
          {t(`admin.solution.severityLabel.${cluster.severity}`)}
        </span>
      </div>
      {cluster.summary && (
        <div className="text-sm text-secondary leading-relaxed mb-2">{cluster.summary}</div>
      )}
      {cluster.bullets.length > 0 && (
        <ul className="text-xs text-secondary space-y-1 ml-4 list-disc">
          {cluster.bullets.slice(0, 6).map((b, i) => (
            <li key={i} className="leading-relaxed">{b}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ExecutionLayersSection({ layers }: { layers: SolutionExecutionLayer[] }) {
  const { t } = useTranslation();
  if (layers.length === 0) return null;
  return (
    <SectionCard title={t('admin.solution.section.executionLayers')}>
      <p className="text-xs text-secondary mb-3">{t('admin.solution.executionLayersHint')}</p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {layers.map((l) => (
          <div key={l.key} className="rounded-md p-3"
               style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
            <div className="font-semibold text-primary mb-1">{l.title_zh}</div>
            <div className="text-xs text-muted mb-2 leading-relaxed">{l.hint}</div>
            <ul className="text-xs text-secondary space-y-1">
              {l.clusters.map((c, i) => (
                <li key={i}>· {c}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function SevenStepsSection({ steps }: { steps: SolutionSevenStep[] }) {
  const { t } = useTranslation();
  return (
    <SectionCard title={t('admin.solution.section.sevenSteps')}>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left" style={{ color: 'var(--text-muted)' }}>
              <th className="py-2 px-2 font-medium w-10 text-center">{t('admin.solution.stepCol.step')}</th>
              <th className="py-2 px-2 font-medium w-24">{t('admin.solution.stepCol.name')}</th>
              <th className="py-2 px-2 font-medium w-32">{t('admin.solution.stepCol.core_goal')}</th>
              <th className="py-2 px-2 font-medium">{t('admin.solution.stepCol.core_action')}</th>
              <th className="py-2 px-2 font-medium w-40">{t('admin.solution.stepCol.output_value')}</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s) => (
              <tr key={s.step} style={{ borderTop: '1px solid var(--border-color)' }}>
                <td className="py-3 px-2 text-center font-bold tabular-nums"
                    style={{ color: 'var(--accent-primary)' }}>{s.step}</td>
                <td className="py-3 px-2 font-semibold text-primary align-top">{s.name}</td>
                <td className="py-3 px-2 text-secondary align-top leading-relaxed">{s.core_goal}</td>
                <td className="py-3 px-2 text-primary align-top leading-relaxed">{s.core_action || '—'}</td>
                <td className="py-3 px-2 text-secondary align-top leading-relaxed">{s.output_value || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

function KeywordsSection({ tiers }: { tiers: SolutionKeywordTier[] }) {
  const { t } = useTranslation();
  return (
    <SectionCard title={t('admin.solution.section.keywords')}>
      <div className="space-y-3">
        {tiers.map((tt) => (
          <div key={tt.tier} className="rounded-md p-3"
               style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
            <div className="font-semibold text-primary mb-1">{tt.title_zh}</div>
            {tt.description && (
              <div className="text-xs text-muted mb-2 leading-relaxed">{tt.description}</div>
            )}
            <div className="flex flex-wrap gap-1.5">
              {tt.keywords.length === 0 ? (
                <span className="text-xs text-muted">{t('admin.solution.noKeywords')}</span>
              ) : tt.keywords.map((k, i) => (
                <span key={i} className="text-xs px-2 py-0.5 rounded-md"
                      style={{ background: 'var(--bg-card)', color: 'var(--accent-primary)',
                               border: '1px solid var(--border-color)' }}>
                  {k}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function QueriesSection({ snapshot }: { snapshot: SolutionQueriesSnapshot }) {
  const { t } = useTranslation();
  // 按种子提示词 (seed) 分组 — 与「七步模型」第 1-2 步语义对齐:种子词 → 扩展 query。
  // 空 seed(legacy 数据 / 非种子路径补录)归入"其它"桶,按 seed 首次出现顺序排列。
  const grouped = new Map<string, string[]>();
  const order: string[] = [];
  const unseededKey = '__no_seed__';
  for (const q of snapshot.queries) {
    const key = (q.seed || '').trim() || unseededKey;
    if (!grouped.has(key)) {
      grouped.set(key, []);
      order.push(key);
    }
    grouped.get(key)!.push(q.text);
  }
  const total = snapshot.queries.length;
  return (
    <SectionCard
      title={t('admin.solution.section.queries')}
      action={
        <span className="text-[11px] px-2 py-0.5 rounded-md"
              style={{ background: 'var(--bg-tertiary)', color: 'var(--accent-primary)' }}>
          {t('admin.solution.queries.totalChip', { n: total })}
        </span>
      }>
      <p className="text-xs text-secondary mb-3">{t('admin.solution.queries.hint')}</p>
      <div className="space-y-3">
        {order.map((key) => {
          const items = grouped.get(key) || [];
          const label = key === unseededKey
            ? t('admin.solution.queries.unseeded')
            : key;
          return (
            <div key={key} className="rounded-md p-3"
                 style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
              <div className="flex items-center justify-between mb-2 gap-2">
                <div className="font-semibold text-primary">{label}</div>
                <span className="text-[10px] text-muted">{items.length}</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {items.map((q, i) => (
                  <span key={i} className="text-xs px-2 py-0.5 rounded-md"
                        style={{ background: 'var(--bg-card)', color: 'var(--accent-primary)',
                                 border: '1px solid var(--border-color)' }}>
                    {q}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

function VisionSection({ items }: { items: SolutionVisionItem[] }) {
  const { t } = useTranslation();
  return (
    <SectionCard title={t('admin.solution.section.vision')}>
      <div className="space-y-3">
        {items.map((v, i) => (
          <div key={i} className="rounded-md p-3"
               style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
            <div className="font-semibold text-primary mb-1.5">{v.title}</div>
            <div className="text-sm text-secondary leading-relaxed">{v.body}</div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function DetailsSection({ checks }: { checks: { category: string; status: string; message: string }[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const STATUS_COLOR: Record<string, string> = {
    PASS: '#10b981', WARN: '#eab308', FAIL: '#ef4444', INFO: '#3b82f6',
  };
  return (
    <SectionCard
      title={t('admin.solution.section.details')}
      action={
        <button type="button" onClick={() => setOpen(!open)}
                className="text-[11px] px-2 py-1 rounded-md"
                style={{ background: 'var(--bg-tertiary)', color: 'var(--accent-primary)' }}>
          {open ? '▾' : '▸'} {checks.length}
        </button>
      }>
      {open && (
        <div className="overflow-x-auto max-h-80">
          <table className="w-full text-xs">
            <tbody>
              {checks.map((c, i) => (
                <tr key={i} style={{ borderTop: '1px solid var(--border-color)' }}>
                  <td className="py-1.5 px-2 text-secondary align-top whitespace-nowrap">{c.category}</td>
                  <td className="py-1.5 px-2 align-top font-semibold"
                      style={{ color: STATUS_COLOR[c.status] || 'var(--text-secondary)' }}>
                    {c.status}
                  </td>
                  <td className="py-1.5 px-2 text-primary align-top leading-relaxed">{c.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
