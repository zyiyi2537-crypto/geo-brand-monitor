// PDF 导出 — 品牌增长报告(首次跑批 vs 当前累计)。
// 复用 pdfPrimitives 的 jsPDF + html2canvas 流水线 + CJK 字体栈,不引新依赖。
// 布局一律用 table / table-cell(html2canvas@1.4.1 下 flex / gap 会偏移)。

import type { TFunction } from 'i18next';
import {
  blockWrapClose, blockWrapOpen, composeAndSavePdf, escapeHtml,
} from './pdfPrimitives';
import type { GrowthReport, GrowthSnapshot, GrowthStatus } from '../services/aiTelemetryApi';
import { engineLabel } from '../pages/BrandGrowth/lang';

interface Dict {
  reportTitle: string;
  subtitle: string;
  brandLabel: string;
  generatedAt: string;
  baselineRunAt: string;
  notRun: string;
  summaryHeading: string;
  metric: string;
  baselineCol: string;
  currentCol: string;
  queriesHit: string;
  hitRate: string;
  avgRank: string;
  enginesCovered: string;
  rowsHeading: string;
  colIndex: string;
  colQuery: string;
  colBaseline: string;
  colCurrent: string;
  colChange: string;
  miss: string;
  rowsEmpty: string;
  rankShort: (n: number) => string;
  hitNoRank: string;
  status: Record<GrowthStatus, string>;
  noBaseline: string;
}

const ZH: Dict = {
  reportTitle: '品牌增长报告',
  subtitle: '首次跑批 vs 当前 · 监测问题逐条对比',
  brandLabel: '品牌',
  generatedAt: '生成时间',
  baselineRunAt: '首次跑批时间',
  notRun: '尚未跑批',
  summaryHeading: '整体对比',
  metric: '指标',
  baselineCol: '首次跑批',
  currentCol: '当前',
  queriesHit: '命中问题数',
  hitRate: '命中率',
  avgRank: '平均排名',
  enginesCovered: '覆盖引擎数',
  rowsHeading: '监测问题明细',
  colIndex: '序号',
  colQuery: '监测问题',
  colBaseline: '首次命中模型',
  colCurrent: '当前命中模型',
  colChange: '变化',
  miss: '未命中',
  rowsEmpty: '暂无命中的监测问题',
  rankShort: (n) => `第 ${n} 位`,
  hitNoRank: '命中',
  status: {
    new_hit: '新命中',
    improved: '排名提升',
    steady: '持平',
    regressed: '下滑',
    still_miss: '仍未命中',
  },
  noBaseline: '该主题还没有首次跑批记录,无法生成对比。',
};

const EN: Dict = {
  reportTitle: 'Brand Growth Report',
  subtitle: 'First run vs current · per-query comparison',
  brandLabel: 'Brand',
  generatedAt: 'Generated',
  baselineRunAt: 'First run',
  notRun: 'Not run yet',
  summaryHeading: 'Overall comparison',
  metric: 'Metric',
  baselineCol: 'First run',
  currentCol: 'Current',
  queriesHit: 'Queries hit',
  hitRate: 'Hit rate',
  avgRank: 'Avg rank',
  enginesCovered: 'Engines covered',
  rowsHeading: 'Tracked queries',
  colIndex: '#',
  colQuery: 'Query',
  colBaseline: 'First-run hits',
  colCurrent: 'Current hits',
  colChange: 'Change',
  miss: 'Miss',
  rowsEmpty: 'No hit queries yet',
  rankShort: (n) => `rank ${n}`,
  hitNoRank: 'Hit',
  status: {
    new_hit: 'New hit',
    improved: 'Improved',
    steady: 'Steady',
    regressed: 'Regressed',
    still_miss: 'Still miss',
  },
  noBaseline: 'No first run recorded for this topic — comparison unavailable.',
};

const STATUS_COLOR: Record<GrowthStatus, string> = {
  new_hit: '#15803d',
  improved: '#0d9488',
  steady: '#64748b',
  regressed: '#b91c1c',
  still_miss: '#94a3b8',
};

const fmtDate = (iso: string | null, lang: string): string =>
  iso ? new Date(iso).toLocaleString(lang.startsWith('zh') ? 'zh-CN' : 'en-US') : '';

// 命中模型列:列出命中的引擎(本地化名),命中且抽出排名时追加「· 第N位」。未命中显示「未命中」。
const resultText = (hit: boolean, rank: number | null, engines: string[], L: Dict): string => {
  if (!hit) return L.miss;
  const names = engines.length ? engines.map(engineLabel).join('、') : L.hitNoRank;
  return rank != null ? `${names} · ${L.rankShort(rank)}` : names;
};

const buildCover = (report: GrowthReport, L: Dict, lang: string): string =>
  blockWrapOpen('padding:6px 0 20px 0;border-bottom:3px solid #6366f1;margin-bottom:8px;') +
  `<div style="font-size:11px;letter-spacing:0.22em;color:#6366f1;text-transform:uppercase;font-weight:700;margin-bottom:8px;">GROWTH</div>` +
  `<div style="font-size:25px;font-weight:800;line-height:1.25;margin-bottom:4px;color:#0f172a;">${escapeHtml(L.reportTitle)}</div>` +
  `<div style="font-size:13px;color:#64748b;margin-bottom:12px;">${escapeHtml(L.subtitle)}</div>` +
  `<table style="width:100%;font-size:11.5px;color:#334155;border-collapse:collapse;">` +
  `<tr><td style="padding:3px 0;width:120px;color:#94a3b8;">${escapeHtml(L.brandLabel)}</td><td style="padding:3px 0;color:#0f172a;font-weight:600;">${escapeHtml(report.target)}</td></tr>` +
  `<tr><td style="padding:3px 0;color:#94a3b8;">${escapeHtml(L.baselineRunAt)}</td><td style="padding:3px 0;color:#0f172a;">${escapeHtml(report.baseline.run_at ? fmtDate(report.baseline.run_at, lang) : L.notRun)}</td></tr>` +
  `<tr><td style="padding:3px 0;color:#94a3b8;">${escapeHtml(L.generatedAt)}</td><td style="padding:3px 0;color:#0f172a;">${escapeHtml(fmtDate(report.generated_at, lang))}</td></tr>` +
  `</table>` +
  blockWrapClose;

const heading = (text: string): string =>
  blockWrapOpen('padding:16px 0 6px 0;') +
  `<div style="font-size:16px;font-weight:800;color:#0f172a;">${escapeHtml(text)}</div>` +
  blockWrapClose;

const fmtRank = (v: number | null): string => (v != null ? String(v) : '—');

const buildSummary = (b: GrowthSnapshot, c: GrowthSnapshot, L: Dict): string => {
  const rows: [string, string, string][] = [
    [L.queriesHit, `${b.queries_hit} / ${b.queries_total}`, `${c.queries_hit} / ${c.queries_total}`],
    [L.hitRate, `${b.hit_rate_pct.toFixed(1)}%`, `${c.hit_rate_pct.toFixed(1)}%`],
    [L.avgRank, fmtRank(b.avg_rank), fmtRank(c.avg_rank)],
    [L.enginesCovered, String(b.engines_covered), String(c.engines_covered)],
  ];
  const body = rows.map(([k, bv, cv]) =>
    `<tr>` +
    `<td style="padding:7px 10px;border-bottom:1px solid #eef2f7;color:#475569;font-size:12px;">${escapeHtml(k)}</td>` +
    `<td style="padding:7px 10px;border-bottom:1px solid #eef2f7;text-align:center;color:#64748b;font-size:12px;">${escapeHtml(bv)}</td>` +
    `<td style="padding:7px 10px;border-bottom:1px solid #eef2f7;text-align:center;color:#0f172a;font-weight:700;font-size:12px;">${escapeHtml(cv)}</td>` +
    `</tr>`,
  ).join('');
  return (
    blockWrapOpen('padding:4px 0;') +
    `<table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">` +
    `<tr style="background:#f8fafc;">` +
    `<th style="padding:8px 10px;text-align:left;font-size:11px;color:#94a3b8;font-weight:700;">${escapeHtml(L.metric)}</th>` +
    `<th style="padding:8px 10px;text-align:center;font-size:11px;color:#94a3b8;font-weight:700;">${escapeHtml(L.baselineCol)}</th>` +
    `<th style="padding:8px 10px;text-align:center;font-size:11px;color:#94a3b8;font-weight:700;">${escapeHtml(L.currentCol)}</th>` +
    `</tr>${body}</table>` +
    blockWrapClose
  );
};

const buildRowsTable = (report: GrowthReport, L: Dict): string => {
  // 只展示当前命中的监测问题 — 未命中的不进表(噪音)。
  const rows = report.rows.filter(r => r.current_hit);
  if (rows.length === 0) {
    return (
      blockWrapOpen('padding:14px 0;') +
      `<div style="font-size:12.5px;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:12px 14px;text-align:center;">${escapeHtml(L.rowsEmpty)}</div>` +
      blockWrapClose
    );
  }
  const head =
    `<tr style="background:#f8fafc;">` +
    `<th style="padding:7px 8px;text-align:left;font-size:10.5px;color:#94a3b8;font-weight:700;width:34px;">${escapeHtml(L.colIndex)}</th>` +
    `<th style="padding:7px 8px;text-align:left;font-size:10.5px;color:#94a3b8;font-weight:700;">${escapeHtml(L.colQuery)}</th>` +
    `<th style="padding:7px 8px;text-align:left;font-size:10.5px;color:#94a3b8;font-weight:700;width:128px;">${escapeHtml(L.colBaseline)}</th>` +
    `<th style="padding:7px 8px;text-align:left;font-size:10.5px;color:#94a3b8;font-weight:700;width:138px;">${escapeHtml(L.colCurrent)}</th>` +
    `<th style="padding:7px 8px;text-align:left;font-size:10.5px;color:#94a3b8;font-weight:700;width:64px;">${escapeHtml(L.colChange)}</th>` +
    `</tr>`;
  const body = rows.map((r, i) =>
    `<tr>` +
    `<td style="padding:6px 8px;border-bottom:1px solid #eef2f7;color:#94a3b8;font-size:11px;vertical-align:top;">${i + 1}</td>` +
    `<td style="padding:6px 8px;border-bottom:1px solid #eef2f7;color:#0f172a;font-size:11.5px;line-height:1.5;vertical-align:top;">${escapeHtml(r.query)}</td>` +
    `<td style="padding:6px 8px;border-bottom:1px solid #eef2f7;color:#64748b;font-size:11px;line-height:1.5;vertical-align:top;">${escapeHtml(resultText(r.baseline_hit, r.baseline_rank, r.baseline_engines, L))}</td>` +
    `<td style="padding:6px 8px;border-bottom:1px solid #eef2f7;color:#0f172a;font-size:11px;line-height:1.5;vertical-align:top;">${escapeHtml(resultText(r.current_hit, r.current_rank, r.current_engines, L))}</td>` +
    `<td style="padding:6px 8px;border-bottom:1px solid #eef2f7;font-size:11px;font-weight:700;vertical-align:top;color:${STATUS_COLOR[r.status]};">${escapeHtml(L.status[r.status])}</td>` +
    `</tr>`,
  ).join('');
  return (
    blockWrapOpen('padding:4px 0;') +
    `<table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;">${head}${body}</table>` +
    blockWrapClose
  );
};

export async function exportGrowthReportPdf(
  report: GrowthReport,
  t: TFunction,
  language: string,
): Promise<void> {
  const L = language.startsWith('en') ? EN : ZH;

  const blocks: string[] = [buildCover(report, L, language)];
  if (!report.has_baseline) {
    blocks.push(
      blockWrapOpen('padding:14px 0;') +
      `<div style="font-size:12.5px;color:#b45309;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:12px 14px;">${escapeHtml(L.noBaseline)}</div>` +
      blockWrapClose,
    );
  }
  blocks.push(heading(L.summaryHeading));
  blocks.push(buildSummary(report.baseline, report.current, L));
  blocks.push(heading(L.rowsHeading));
  blocks.push(buildRowsTable(report, L));

  const safeName = (report.target || 'brand').replace(/[^a-zA-Z0-9一-龥_-]/g, '-').slice(0, 60);
  await composeAndSavePdf(
    blocks,
    { rightHeaderText: `${L.reportTitle} · ${report.target}`, t },
    `${safeName}-${L.reportTitle}.pdf`,
  );
}
