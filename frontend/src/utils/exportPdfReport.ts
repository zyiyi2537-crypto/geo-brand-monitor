import type { TFunction } from 'i18next';
import type { GeoTestResult, CheckResult } from '../types/geo';
import {
  blockWrapClose,
  blockWrapOpen,
  composeAndSavePdf,
  escapeHtml,
  statusBadge,
} from './pdfPrimitives';

type GroupStat = {
  tab: string;
  total: number;
  passed: number;
  failed: number;
  warned: number;
  info: number;
  passRate: number;
  isPaid: boolean;
  isTabLocked: boolean;
};

interface ExportArgs {
  result: GeoTestResult;
  t: TFunction;
  language: string;
  groupStats: GroupStat[];
  categoryGroups: Record<string, string[]>;
  checksByCategory: Record<string, CheckResult[]>;
  otherCategories: string[];
}

const STATUS_RANK: Record<string, number> = { FAIL: 0, WARN: 1, INFO: 2, PASS: 3 };

// Fix recommendations in the PDF mirror the on-screen gating: only starter /
// growth / scale tiers get the "Top Fixes" section and the per-item fix text.
// Lower tiers (free, pro) get a fix-free report. Backend also strips fix text
// for those tiers, so this is belt-and-braces — if a fix field slips through
// we still don't render it.
const FIX_ALLOWED_TIERS: ReadonlySet<string> = new Set(['starter', 'growth', 'scale']);
const canIncludeFix = (result: GeoTestResult): boolean =>
  FIX_ALLOWED_TIERS.has((result.tier || '').toLowerCase());

const interpretScore = (score: number, t: TFunction): string => {
  if (score >= 90) return t('result.pdfReport.scoreLevels.excellent');
  if (score >= 75) return t('result.pdfReport.scoreLevels.good');
  if (score >= 60) return t('result.pdfReport.scoreLevels.average');
  if (score >= 40) return t('result.pdfReport.scoreLevels.poor');
  return t('result.pdfReport.scoreLevels.critical');
};

const tierLabel = (tier: string | null | undefined, t: TFunction): string => {
  const slug = (tier || 'free').toLowerCase();
  return t(`result.pdfReport.tierLabels.${slug}`, { defaultValue: slug.toUpperCase() });
};

// ---------- Block builders ----------

const buildCoverBlock = (args: ExportArgs): string => {
  const { result, t, language } = args;
  const generatedAt = new Date().toLocaleString(language.startsWith('zh') ? 'zh-CN' : 'en-US');
  return (
    blockWrapOpen('padding:4px 0 18px 0;border-bottom:3px solid #0ea5e9;margin-bottom:8px;') +
    `<div style="font-size:11px;letter-spacing:0.22em;color:#06b6d4;text-transform:uppercase;font-weight:700;margin-bottom:6px;">${escapeHtml(t('result.pdfReport.coverBadge'))}</div>` +
    `<div style="font-size:26px;font-weight:800;line-height:1.25;margin-bottom:6px;color:#0f172a;">${escapeHtml(t('result.pdfReport.title'))}</div>` +
    `<div style="font-size:12px;color:#475569;margin-bottom:14px;">${escapeHtml(t('result.pdfReport.subtitle'))}</div>` +
    `<table style="width:100%;font-size:11.5px;color:#334155;border-collapse:collapse;">` +
    `<tr><td style="padding:3px 0;width:110px;color:#94a3b8;">${escapeHtml(t('result.pdfReport.targetSite'))}</td><td style="padding:3px 0;font-weight:600;color:#0f172a;word-break:break-all;">${escapeHtml(result.url || '')}</td></tr>` +
    `<tr><td style="padding:3px 0;color:#94a3b8;">${escapeHtml(t('result.pdfReport.generatedAt'))}</td><td style="padding:3px 0;color:#0f172a;">${escapeHtml(generatedAt)}</td></tr>` +
    `<tr><td style="padding:3px 0;color:#94a3b8;">${escapeHtml(t('result.pdfReport.tier'))}</td><td style="padding:3px 0;color:#0f172a;">${escapeHtml(tierLabel(result.tier, t))}</td></tr>` +
    `</table>` +
    blockWrapClose
  );
};

const scoreRingColor = (score: number): string => {
  if (score >= 90) return '#22c55e';
  if (score >= 75) return '#06b6d4';
  if (score >= 60) return '#eab308';
  if (score >= 40) return '#f97316';
  return '#ef4444';
};

const buildScoreBlock = (args: ExportArgs): string => {
  const { result, t } = args;
  const score = result.score || 0;
  const grade = result.grade || 'F';
  const summary = result.summary || { pass_count: 0, warn_count: 0, fail_count: 0, info_count: 0, total_checks: 0 };

  // SVG circular progress ring
  const radius = 54;
  const stroke = 8;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - score / 100);
  const ringColor = scoreRingColor(score);

  const ringHtml =
    `<svg width="140" height="140" viewBox="0 0 140 140" xmlns="http://www.w3.org/2000/svg">` +
    `<circle cx="70" cy="70" r="${radius}" fill="none" stroke="#e2e8f0" stroke-width="${stroke}"/>` +
    `<circle cx="70" cy="70" r="${radius}" fill="none" stroke="${ringColor}" stroke-width="${stroke}" ` +
    `stroke-linecap="round" stroke-dasharray="${circumference}" stroke-dashoffset="${dashOffset}" ` +
    `transform="rotate(-90 70 70)"/>` +
    `</svg>`;

  return (
    blockWrapOpen('padding:0 0 8px 0;') +
    `<div style="display:flex;gap:14px;align-items:stretch;">` +
    // Left: ring progress
    `<div style="flex-shrink:0;width:190px;background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;border-radius:12px;padding:20px 18px;text-align:center;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;">` +
    `<div style="font-size:10px;letter-spacing:0.16em;color:#94a3b8;text-transform:uppercase;margin-bottom:10px;">${escapeHtml(t('result.pdfReport.overallScore'))}</div>` +
    `<div style="position:relative;width:140px;height:140px;">` +
    ringHtml +
    `<div style="position:absolute;top:0;left:0;width:140px;height:140px;display:flex;flex-direction:column;align-items:center;justify-content:center;">` +
    `<div style="font-size:40px;font-weight:800;line-height:1;color:#fff;position:relative;top:-4px;">${score}</div>` +
    `<div style="font-size:11px;color:#94a3b8;">/ 100</div>` +
    `</div>` +
    `</div>` +
    `<div style="margin-top:10px;font-size:16px;font-weight:700;color:#22d3ee;">${escapeHtml(grade)}</div>` +
    `</div>` +
    // Right: interpretation + summary counts
    `<div style="flex:1;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:space-between;">` +
    `<div>` +
    `<div style="font-size:11px;font-weight:700;color:#0f172a;margin-bottom:6px;">${escapeHtml(t('result.pdfReport.scoreInterpretation'))}</div>` +
    `<div style="font-size:12px;color:#334155;line-height:1.7;">${escapeHtml(interpretScore(score, t))}</div>` +
    `</div>` +
    `<div style="display:flex;gap:8px;margin-top:14px;">` +
    `<div style="flex:1;background:#dcfce7;border-radius:8px;padding:5px 6px 11px 6px;text-align:center;"><div style="font-size:16px;font-weight:800;color:#166534;">${summary.pass_count}</div><div style="font-size:9px;color:#166534;font-weight:600;margin-top:2px;">${escapeHtml(t('result.summary.passed'))}</div></div>` +
    `<div style="flex:1;background:#fef3c7;border-radius:8px;padding:5px 6px 11px 6px;text-align:center;"><div style="font-size:16px;font-weight:800;color:#92400e;">${summary.warn_count}</div><div style="font-size:9px;color:#92400e;font-weight:600;margin-top:2px;">${escapeHtml(t('result.summary.warnings'))}</div></div>` +
    `<div style="flex:1;background:#fee2e2;border-radius:8px;padding:5px 6px 11px 6px;text-align:center;"><div style="font-size:16px;font-weight:800;color:#991b1b;">${summary.fail_count}</div><div style="font-size:9px;color:#991b1b;font-weight:600;margin-top:2px;">${escapeHtml(t('result.summary.failed'))}</div></div>` +
    `<div style="flex:1;background:#dbeafe;border-radius:8px;padding:5px 6px 11px 6px;text-align:center;"><div style="font-size:16px;font-weight:800;color:#1e40af;">${summary.info_count}</div><div style="font-size:9px;color:#1e40af;font-weight:600;margin-top:2px;">${escapeHtml(t('result.summary.info'))}</div></div>` +
    `</div>` +
    `</div>` +
    `</div>` +
    blockWrapClose
  );
};

const buildLockedNoticeBlock = (lockedCount: number, t: TFunction): string =>
  blockWrapOpen('padding:0 0 4px 0;') +
  `<div style="font-size:11px;color:#92400e;background:#fef3c7;border-left:3px solid #f59e0b;padding:10px 12px;border-radius:6px;">${escapeHtml(t('result.pdfReport.lockedNotice', { count: lockedCount }))}</div>` +
  blockWrapClose;

const buildSectionHeadingBlock = (text: string, accent: string): string =>
  blockWrapOpen('padding:10px 0 4px 0;') +
  `<div style="font-size:16px;font-weight:800;color:#0f172a;border-left:4px solid ${accent};padding-left:10px;">${escapeHtml(text)}</div>` +
  blockWrapClose;

const buildGroupTableBlock = (args: ExportArgs): string => {
  const { t, groupStats } = args;
  const tabLabel = (tab: string) => t(`result.categories.${tab}`);
  const rows = groupStats
    .filter((g) => g.total > 0)
    .map((g) => {
      return (
        `<tr>` +
        `<td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;font-weight:600;color:#0f172a;">${escapeHtml(tabLabel(g.tab))}</td>` +
        `<td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center;color:#0f172a;">${g.total}</td>` +
        `<td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center;color:#166534;font-weight:600;">${g.passed}</td>` +
        `<td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center;color:#92400e;font-weight:600;">${g.warned}</td>` +
        `<td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:center;color:#991b1b;font-weight:600;">${g.failed}</td>` +
        `<td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;width:150px;">` +
        `<div style="background:#e5e7eb;border-radius:999px;height:7px;width:100%;overflow:hidden;"><div style="background:#0ea5e9;height:100%;width:${g.passRate}%;"></div></div>` +
        `<div style="font-size:10px;color:#475569;margin-top:3px;">${g.passRate}%</div>` +
        `</td>` +
        `</tr>`
      );
    })
    .join('');

  return (
    blockWrapOpen('padding:4px 0 10px 0;') +
    `<table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;font-size:11.5px;">` +
    `<thead><tr style="background:#f1f5f9;">` +
    `<th style="padding:9px 10px;text-align:left;font-size:10px;color:#475569;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;">${escapeHtml(t('result.pdfReport.groupLabel'))}</th>` +
    `<th style="padding:9px 10px;text-align:center;font-size:10px;color:#475569;font-weight:700;">${escapeHtml(t('result.summary.totalChecks'))}</th>` +
    `<th style="padding:9px 10px;text-align:center;font-size:10px;color:#166534;font-weight:700;">${escapeHtml(t('result.summary.passed'))}</th>` +
    `<th style="padding:9px 10px;text-align:center;font-size:10px;color:#92400e;font-weight:700;">${escapeHtml(t('result.summary.warnings'))}</th>` +
    `<th style="padding:9px 10px;text-align:center;font-size:10px;color:#991b1b;font-weight:700;">${escapeHtml(t('result.summary.failed'))}</th>` +
    `<th style="padding:9px 10px;text-align:left;font-size:10px;color:#475569;font-weight:700;">${escapeHtml(t('result.groupProgress.title'))}</th>` +
    `</tr></thead>` +
    `<tbody>${rows}</tbody>` +
    `</table>` +
    blockWrapClose
  );
};

const buildTopFixBlock = (check: CheckResult, idx: number, t: TFunction): string => {
  const catLabel = t(`result.categoryLabels.${check.category}`, { defaultValue: check.category });
  const fix = check.fix && check.fix.trim() ? check.fix.trim() : t('result.pdfReport.noFix');
  return (
    blockWrapOpen('padding:3px 0;') +
    `<div style="display:flex;gap:10px;padding:11px 13px;border:1px solid #e5e7eb;border-radius:10px;background:#fff;">` +
    `<div style="flex-shrink:0;width:24px;height:24px;border-radius:999px;background:#0f172a;color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;">${idx + 1}</div>` +
    `<div style="flex:1;min-width:0;">` +
    `<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">` +
    `<div style="font-size:11.5px;font-weight:700;color:#0f172a;">${escapeHtml(catLabel)}</div>` +
    statusBadge(check.status, t) +
    `</div>` +
    `<div style="font-size:11.5px;color:#334155;line-height:1.6;margin-bottom:4px;">${escapeHtml(check.message || '')}</div>` +
    `<div style="font-size:10.5px;color:#475569;line-height:1.6;"><span style="font-weight:600;color:#0f172a;">${escapeHtml(t('result.pdfReport.fixLabel'))}:</span> ${escapeHtml(fix)}</div>` +
    `</div>` +
    `</div>` +
    blockWrapClose
  );
};

const buildTabHeadingBlock = (tabKey: string, t: TFunction): string =>
  blockWrapOpen('padding:10px 0 4px 0;') +
  `<div style="font-size:14px;font-weight:800;color:#0ea5e9;border-bottom:2px solid #0ea5e9;padding-bottom:5px;">${escapeHtml(t(`result.categories.${tabKey}`))}</div>` +
  blockWrapClose;

const buildCategoryBlock = (
  cat: string,
  checks: CheckResult[],
  t: TFunction,
  showFix: boolean,
): string => {
  const catLabel = t(`result.categoryLabels.${cat}`, { defaultValue: cat });
  const catDesc = t(`result.categoryDescriptions.${cat}`, { defaultValue: '' });
  const itemsHtml = checks
    .map((c) => {
      const fix = c.fix && c.fix.trim() ? c.fix.trim() : t('result.pdfReport.noFix');
      return (
        `<div style="border:1px solid #e5e7eb;border-radius:8px;padding:11px 13px;margin-bottom:8px;background:#fff;">` +
        `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;gap:10px;">` +
        `<div style="font-size:12px;font-weight:600;color:#0f172a;flex:1;">${escapeHtml(c.message || '')}</div>` +
        `<div>${statusBadge(c.status, t)}</div>` +
        `</div>` +
        (showFix && c.status !== 'PASS'
          ? `<div style="font-size:11px;color:#475569;line-height:1.6;"><span style="font-weight:600;color:#0f172a;">${escapeHtml(t('result.pdfReport.fixLabel'))}:</span> ${escapeHtml(fix)}</div>`
          : '') +
        `</div>`
      );
    })
    .join('');

  return (
    blockWrapOpen('padding:6px 0 2px 0;') +
    `<div style="font-size:13.5px;font-weight:700;color:#0f172a;margin-bottom:4px;">${escapeHtml(catLabel)}</div>` +
    (catDesc
      ? `<div style="font-size:11px;color:#475569;line-height:1.6;margin-bottom:8px;padding:8px 10px;background:#f1f5f9;border-left:3px solid #06b6d4;border-radius:4px;">${escapeHtml(catDesc)}</div>`
      : '') +
    itemsHtml +
    blockWrapClose
  );
};

const buildAppendixBlock = (t: TFunction): string =>
  blockWrapOpen('padding:14px 0 4px 0;') +
  `<div style="padding:14px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;">` +
  `<div style="font-size:12px;font-weight:700;color:#0f172a;margin-bottom:6px;">${escapeHtml(t('result.pdfReport.appendixSection'))}</div>` +
  `<div style="font-size:11px;color:#475569;line-height:1.7;">${escapeHtml(t('result.pdfReport.appendixBody'))}</div>` +
  `</div>` +
  blockWrapClose;

// ---------- Compose ----------

const buildAllBlocks = (args: ExportArgs): string[] => {
  const { result, t, categoryGroups, checksByCategory, otherCategories } = args;
  const lockedSet = new Set(result.locked_categories || []);
  const showFix = canIncludeFix(result);
  const blocks: string[] = [];

  blocks.push(buildCoverBlock(args));
  blocks.push(buildScoreBlock(args));
  if (lockedSet.size > 0) blocks.push(buildLockedNoticeBlock(lockedSet.size, t));

  blocks.push(buildSectionHeadingBlock(t('result.pdfReport.groupSection'), '#0ea5e9'));
  blocks.push(buildGroupTableBlock(args));

  // Top-Fixes / recommendations block is a paid perk — omit entirely for
  // tiers that don't see fix recommendations, so the PDF layout matches the
  // on-screen experience.
  if (showFix) {
    const failsAndWarns = (result.checks || [])
      .filter((c) => c.status === 'FAIL' || c.status === 'WARN')
      .sort((a, b) => (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9))
      .slice(0, 12);

    blocks.push(buildSectionHeadingBlock(t('result.pdfReport.recommendationsSection'), '#ec4899'));
    blocks.push(
      blockWrapOpen('padding:2px 0 4px 0;') +
        `<div style="font-size:11px;color:#475569;">${escapeHtml(t('result.pdfReport.topFixesIntro'))}</div>` +
        blockWrapClose,
    );
    if (failsAndWarns.length === 0) {
      blocks.push(
        blockWrapOpen('padding:4px 0;') +
          `<div style="font-size:11.5px;color:#475569;padding:12px;background:#f1f5f9;border-radius:8px;">${escapeHtml(t('result.pdfReport.noFailItems'))}</div>` +
          blockWrapClose,
      );
    } else {
      failsAndWarns.forEach((c, idx) => blocks.push(buildTopFixBlock(c, idx, t)));
    }
  }

  blocks.push(buildSectionHeadingBlock(t('result.pdfReport.detailSection'), '#8b5cf6'));
  const allTabs = [...Object.keys(categoryGroups), ...(otherCategories.length ? ['other'] : [])];
  for (const tab of allTabs) {
    const cats = tab === 'other' ? otherCategories : categoryGroups[tab] || [];
    const visibleCats = cats.filter((c) => !lockedSet.has(c) && (checksByCategory[c]?.length ?? 0) > 0);
    if (visibleCats.length === 0) continue;
    blocks.push(buildTabHeadingBlock(tab, t));
    for (const cat of visibleCats) {
      blocks.push(buildCategoryBlock(cat, checksByCategory[cat] || [], t, showFix));
    }
  }

  blocks.push(buildAppendixBlock(t));
  return blocks;
};

// ---------- Entry point ----------

export async function exportPdfReport(args: ExportArgs): Promise<void> {
  const { result, t } = args;
  const htmlBlocks = buildAllBlocks(args);
  const safeUrl = (result.url || 'site').replace(/[^a-zA-Z0-9]/g, '-').slice(0, 60);
  const baseName = t('result.pdfReport.fileName');
  const headerRight = `${t('result.pdfReport.headerSite')}: ${result.url || ''}`;
  await composeAndSavePdf(
    htmlBlocks,
    { rightHeaderText: headerRight, t },
    `${baseName}-${safeUrl}.pdf`,
  );
}
