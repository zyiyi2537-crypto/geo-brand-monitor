// PDF 导出 — GEO 品牌增长战略方案.
// 沿用 pdfPrimitives 的 jsPDF + html2canvas 流水线 + CJK 字体栈,
// 不引新依赖。结构跟 AdminSolution 页面保持一致(6 段)。

import type { TFunction } from 'i18next';
import {
  blockWrapClose, blockWrapOpen, composeAndSavePdf, escapeHtml,
} from './pdfPrimitives';
import type {
  TopicStrategicSolution, SolutionDiagnosisCluster,
  SolutionSevenStep, SolutionKeywordTier, SolutionVisionItem,
  SolutionDiagnosisCheck, SolutionQueriesSnapshot,
} from '../services/adminReviewApi';

// 严重度标签:去掉 pill 背景,只用纯文字 + 颜色。
// 原因:html2canvas 下"title + 带背景的小 badge"在同一行很难真居中(标题字号 13.5,
// badge 字号 10.5 + padding,line-box 算出来基线差几 px,反复调整都对不齐)。
// 用户指令:对不齐就别用背景,改纯文字。
const SEVERITY_STYLE = {
  high: { c: '#991b1b', label: '重点突破' },
  med:  { c: '#92400e', label: '建议补强' },
  low:  { c: '#166534', label: '已达标' },
} as const;

const SEVERITY_STYLE_EN = {
  high: { c: '#991b1b', label: 'Priority gap' },
  med:  { c: '#92400e', label: 'Reinforce' },
  low:  { c: '#166534', label: 'On par' },
} as const;

const scoreRingColor = (s: number): string => {
  if (s >= 90) return '#22c55e';
  if (s >= 75) return '#06b6d4';
  if (s >= 60) return '#eab308';
  if (s >= 40) return '#f97316';
  return '#ef4444';
};

const buildCoverBlock = (sol: TopicStrategicSolution, t: TFunction, language: string): string => {
  const generatedAt = sol.updated_at
    ? new Date(sol.updated_at).toLocaleString(language.startsWith('zh') ? 'zh-CN' : 'en-US')
    : '';
  const bp = sol.brand_snapshot || null;
  const brandName = bp?.company_short_name || bp?.company_full_name || bp?.profile_name || '';
  return (
    blockWrapOpen('padding:6px 0 22px 0;border-bottom:3px solid #6366f1;margin-bottom:8px;') +
    `<div style="font-size:11px;letter-spacing:0.22em;color:#6366f1;text-transform:uppercase;font-weight:700;margin-bottom:8px;">GEO STRATEGY</div>` +
    `<div style="font-size:26px;font-weight:800;line-height:1.25;margin-bottom:6px;color:#0f172a;">${escapeHtml(t('admin.solution.title'))}</div>` +
    (brandName
      ? `<div style="font-size:18px;color:#334155;font-weight:600;margin-bottom:10px;">${escapeHtml(brandName)}</div>`
      : '') +
    `<table style="width:100%;font-size:11.5px;color:#334155;border-collapse:collapse;">` +
    `<tr><td style="padding:3px 0;width:110px;color:#94a3b8;">${escapeHtml(t('admin.solution.websiteLabel'))}</td><td style="padding:3px 0;color:#0f172a;word-break:break-all;">${escapeHtml(sol.website_url || '')}</td></tr>` +
    (bp?.industry
      ? `<tr><td style="padding:3px 0;color:#94a3b8;">${escapeHtml(t('admin.solution.brandFields.industry'))}</td><td style="padding:3px 0;color:#0f172a;">${escapeHtml(bp.industry)}</td></tr>`
      : '') +
    (bp?.service_geo
      ? `<tr><td style="padding:3px 0;color:#94a3b8;">${escapeHtml(t('admin.solution.brandFields.service_geo'))}</td><td style="padding:3px 0;color:#0f172a;">${escapeHtml(bp.service_geo)}</td></tr>`
      : '') +
    `<tr><td style="padding:3px 0;color:#94a3b8;">${escapeHtml(t('admin.solution.lastGeneratedAt'))}</td><td style="padding:3px 0;color:#0f172a;">${escapeHtml(generatedAt)}</td></tr>` +
    (sol.llm_model
      ? `<tr><td style="padding:3px 0;color:#94a3b8;">${escapeHtml(t('admin.solution.llmModel'))}</td><td style="padding:3px 0;color:#0f172a;">${escapeHtml(sol.llm_model)}</td></tr>`
      : '') +
    `</table>` +
    blockWrapClose
  );
};

// 章节标题:去掉左侧紫色 border 装饰条(用户反馈视觉上偏移),只留纯标题文字。
const buildSectionHeading = (text: string): string =>
  blockWrapOpen('padding:16px 0 6px 0;') +
  `<div style="font-size:17px;font-weight:800;color:#0f172a;">${escapeHtml(text)}</div>` +
  blockWrapClose;

const buildBrandBlock = (sol: TopicStrategicSolution, t: TFunction): string => {
  const bp = sol.brand_snapshot;
  if (!bp) return '';
  const rows: [string, string | string[] | null | undefined][] = [
    [t('admin.solution.brandFields.core_business_lines'), bp.core_business_lines],
    [t('admin.solution.brandFields.target_scenarios'), bp.target_scenarios],
    [t('admin.solution.brandFields.brand_diff_tags'), bp.brand_diff_tags],
    [t('admin.solution.brandFields.brand_slogan'), bp.brand_slogan],
    [t('admin.solution.brandFields.core_message'), bp.core_message],
    [t('admin.solution.brandFields.core_service_overview'), bp.core_service_overview],
  ];
  const visible = rows.filter(([, v]) => Array.isArray(v) ? v.length > 0 : !!(v && String(v).trim()));
  if (visible.length === 0) return '';
  const html =
    visible.map(([k, v]) => {
      const text = Array.isArray(v) ? v.join('、') : String(v || '');
      // 单元格用 vertical-align:middle:value 多行时,label 与 value 视觉中线对齐,
      // 不会出现 label 飘在顶上、value 长成 3 行的不对齐感。
      return (
        `<tr>` +
        `<td style="padding:6px 12px 6px 0;color:#94a3b8;width:130px;vertical-align:middle;font-size:11.5px;">${escapeHtml(k)}</td>` +
        `<td style="padding:6px 0;color:#0f172a;line-height:1.7;font-size:12px;vertical-align:middle;">${escapeHtml(text)}</td>` +
        `</tr>`
      );
    }).join('');
  return (
    blockWrapOpen('padding:4px 0 6px 0;') +
    `<table style="width:100%;border-collapse:collapse;">${html}</table>` +
    blockWrapClose
  );
};

const buildScoreBlock = (sol: TopicStrategicSolution, t: TFunction): string => {
  const d = sol.diagnosis;
  if (!d) return '';
  const ringColor = scoreRingColor(d.score);
  // 评分:删掉深色面板背景 + 圆环图 + 4 个彩色 tile,改成纯文字行
  // (用户:不要文字背景)。分数用大字号 + 评分色,4 项计数用「· 」分隔。
  return (
    blockWrapOpen('padding:8px 0;') +
    `<div style="margin-bottom:8px;">` +
    `<span style="font-size:11px;color:#94a3b8;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;margin-right:10px;">${escapeHtml(t('admin.solution.scoreLabel'))}</span>` +
    `<span style="font-size:32px;font-weight:800;color:${ringColor};vertical-align:middle;">${d.score}</span>` +
    `<span style="font-size:14px;color:#94a3b8;margin-left:4px;vertical-align:middle;">/ 100</span>` +
    `<span style="font-size:16px;font-weight:700;color:${ringColor};margin-left:16px;vertical-align:middle;">${escapeHtml(d.grade || '')}</span>` +
    `</div>` +
    `<div style="font-size:12px;line-height:1.7;color:#334155;">` +
    `<span style="color:#166534;font-weight:700;">${escapeHtml(t('admin.solution.passLabel'))} ${d.pass_count}</span>` +
    `<span style="color:#cbd5e1;margin:0 8px;">·</span>` +
    `<span style="color:#92400e;font-weight:700;">${escapeHtml(t('admin.solution.warnLabel'))} ${d.warn_count}</span>` +
    `<span style="color:#cbd5e1;margin:0 8px;">·</span>` +
    `<span style="color:#991b1b;font-weight:700;">${escapeHtml(t('admin.solution.failLabel'))} ${d.fail_count}</span>` +
    `<span style="color:#cbd5e1;margin:0 8px;">·</span>` +
    `<span style="color:#1e40af;font-weight:700;">${escapeHtml(t('admin.solution.infoLabel'))} ${d.info_count}</span>` +
    `</div>` +
    blockWrapClose
  );
};

const buildClusterBlock = (c: SolutionDiagnosisCluster, language: string): string => {
  const sty = (language.startsWith('zh') ? SEVERITY_STYLE : SEVERITY_STYLE_EN)[c.severity] || SEVERITY_STYLE.low;
  const bullets = (c.bullets || []).slice(0, 6).map(b =>
    `<li style="font-size:11.5px;color:#475569;line-height:1.7;margin-bottom:2px;">${escapeHtml(b)}</li>`,
  ).join('');
  // 标题 + 严重度标签:都是纯文字、同 baseline、同 line-height,
  // html2canvas 下天然对齐,无背景就无法错位。
  const header =
    `<div style="margin-bottom:6px;font-size:13.5px;line-height:1.4;">` +
    `<span style="font-weight:700;color:#0f172a;">${escapeHtml(c.title_zh)}</span>` +
    `<span style="font-weight:700;color:${sty.c};margin-left:10px;font-size:11px;">${escapeHtml(sty.label)}</span>` +
    `</div>`;
  // 去掉外卡片的 border + 白底 — html2canvas 下卡片边距和文本基线对不齐,
  // 用户指令"对不齐就去背景"。改用上下 padding 做卡间距,纯文本展示。
  return (
    blockWrapOpen('padding:8px 0;') +
    header +
    (c.summary
      ? `<div style="font-size:12px;color:#334155;line-height:1.75;margin-bottom:6px;">${escapeHtml(c.summary)}</div>`
      : '') +
    (bullets ? `<ul style="margin:4px 0 0 18px;padding:0;list-style:disc;">${bullets}</ul>` : '') +
    blockWrapClose
  );
};

const buildExecutionLayersBlock = (sol: TopicStrategicSolution, t: TFunction): string => {
  const layers = sol.diagnosis?.execution_layers || [];
  if (layers.length === 0) return '';
  // 用 2 列 table 网格代替 `display:flex;gap;flex-wrap`,html2canvas 1.4.1 下 gap 会被吃掉、
  // flex-wrap 后续行 baseline 也会漂移。table-layout:fixed + width:50% 出来的 PDF 是稳的。
  // 执行层卡片:去掉灰底 + 边框,纯文字 + 标题色区分。
  const cellInner = (l: typeof layers[number]): string => {
    const clustersHtml = (l.clusters || []).map(c =>
      `<div style="font-size:11px;color:#475569;line-height:1.6;margin-top:3px;">· ${escapeHtml(c)}</div>`,
    ).join('');
    return (
      `<div style="padding:4px 0;">` +
      `<div style="font-size:13px;font-weight:700;color:#312e81;margin-bottom:4px;">${escapeHtml(l.title_zh)}</div>` +
      `<div style="font-size:11px;color:#64748b;line-height:1.7;margin-bottom:6px;">${escapeHtml(l.hint || '')}</div>` +
      clustersHtml +
      `</div>`
    );
  };
  const rows: string[] = [];
  for (let i = 0; i < layers.length; i += 2) {
    const left = layers[i];
    const right = layers[i + 1];
    rows.push(
      `<tr>` +
      `<td style="width:50%;padding:5px 5px 5px 0;vertical-align:top;box-sizing:border-box;">${cellInner(left)}</td>` +
      `<td style="width:50%;padding:5px 0 5px 5px;vertical-align:top;box-sizing:border-box;">${right ? cellInner(right) : ''}</td>` +
      `</tr>`,
    );
  }
  return (
    blockWrapOpen('padding:2px 0 4px 0;') +
    `<div style="font-size:11.5px;color:#475569;margin-bottom:8px;">${escapeHtml(t('admin.solution.executionLayersHint'))}</div>` +
    `<table style="width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;">${rows.join('')}</table>` +
    blockWrapClose
  );
};

const buildSevenStepsBlock = (steps: SolutionSevenStep[], t: TFunction): string => {
  if (steps.length === 0) return '';
  // 七步法:去掉表格外框 + 表头底色,改成无背景的表格,只用下边线分隔行。
  // 表头去掉淡紫色底色,只用加粗 + 深紫色文字。
  const rows = steps.map((s) => {
    return (
      `<tr>` +
      `<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;font-weight:700;color:#312e81;text-align:center;font-size:13px;vertical-align:middle;">${s.step}</td>` +
      `<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;font-weight:600;color:#0f172a;font-size:12px;vertical-align:middle;">${escapeHtml(s.name)}</td>` +
      `<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;color:#475569;font-size:11.5px;line-height:1.7;vertical-align:middle;">${escapeHtml(s.core_goal)}</td>` +
      `<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;color:#0f172a;font-size:11.5px;line-height:1.7;vertical-align:middle;">${escapeHtml(s.core_action)}</td>` +
      `<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;color:#475569;font-size:11.5px;line-height:1.7;vertical-align:middle;">${escapeHtml(s.output_value)}</td>` +
      `</tr>`
    );
  }).join('');
  return (
    blockWrapOpen('padding:4px 0;') +
    `<table style="width:100%;border-collapse:collapse;font-size:11.5px;">` +
    `<thead><tr>` +
    `<th style="padding:8px;text-align:center;font-size:10.5px;color:#312e81;font-weight:700;width:40px;border-bottom:2px solid #cbd5e1;">${escapeHtml(t('admin.solution.stepCol.step'))}</th>` +
    `<th style="padding:8px;text-align:left;font-size:10.5px;color:#312e81;font-weight:700;width:110px;border-bottom:2px solid #cbd5e1;">${escapeHtml(t('admin.solution.stepCol.name'))}</th>` +
    `<th style="padding:8px;text-align:left;font-size:10.5px;color:#312e81;font-weight:700;width:140px;border-bottom:2px solid #cbd5e1;">${escapeHtml(t('admin.solution.stepCol.core_goal'))}</th>` +
    `<th style="padding:8px;text-align:left;font-size:10.5px;color:#312e81;font-weight:700;border-bottom:2px solid #cbd5e1;">${escapeHtml(t('admin.solution.stepCol.core_action'))}</th>` +
    `<th style="padding:8px;text-align:left;font-size:10.5px;color:#312e81;font-weight:700;width:140px;border-bottom:2px solid #cbd5e1;">${escapeHtml(t('admin.solution.stepCol.output_value'))}</th>` +
    `</tr></thead><tbody>${rows}</tbody></table>` +
    blockWrapClose
  );
};

const buildKeywordTierBlock = (tier: SolutionKeywordTier): string => {
  // 关键词组:chip 的浅紫底色也去掉(用户:不要文字背景),
  // 关键词用纯深紫色文字 + 「 · 」分隔,跟一般书面正文一致。
  const keywordText = tier.keywords.length > 0
    ? tier.keywords.map(escapeHtml).join('  ·  ')
    : '—';
  return (
    blockWrapOpen('padding:8px 0;') +
    `<div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:4px;">${escapeHtml(tier.title_zh)}</div>` +
    (tier.description
      ? `<div style="font-size:11.5px;color:#64748b;line-height:1.7;margin-bottom:6px;">${escapeHtml(tier.description)}</div>`
      : '') +
    `<div style="font-size:11.5px;color:#312e81;line-height:1.85;">${keywordText}</div>` +
    blockWrapClose
  );
};

const buildQueriesBlock = (snapshot: SolutionQueriesSnapshot, t: TFunction): string => {
  if (!snapshot.queries.length) return '';
  // 按种子提示词 (seed) 分组,与页面 QueriesSection 保持一致 — 见 Solution.tsx:527.
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
  const unseededLabel = String(t('admin.solution.queries.unseeded'));
  // chips:跟关键词节一样,纯文字 + 「 · 」分隔,避免 flex / chip 背景对齐问题(memory: feedback_pdf_no_flex).
  const groupHtml = order.map((key) => {
    const items = grouped.get(key) || [];
    const label = key === unseededKey ? unseededLabel : key;
    const text = items.map(escapeHtml).join('  ·  ');
    return (
      `<div style="padding:8px 0;">` +
      `<div style="font-size:12.5px;font-weight:700;color:#0f172a;margin-bottom:4px;">` +
      `${escapeHtml(label)}` +
      `<span style="font-size:10.5px;color:#94a3b8;font-weight:500;margin-left:8px;">(${items.length})</span>` +
      `</div>` +
      `<div style="font-size:11.5px;color:#312e81;line-height:1.85;">${text}</div>` +
      `</div>`
    );
  }).join('');
  return (
    blockWrapOpen('padding:4px 0;') +
    `<div style="font-size:11.5px;color:#475569;margin-bottom:8px;line-height:1.7;">` +
    `${escapeHtml(String(t('admin.solution.queries.hint')))}` +
    `<span style="color:#94a3b8;margin:0 8px;">·</span>` +
    `${escapeHtml(String(t('admin.solution.queries.totalChip', { n: snapshot.queries.length })))}` +
    `</div>` +
    groupHtml +
    blockWrapClose
  );
};

const buildVisionBlock = (items: SolutionVisionItem[]): string => {
  if (items.length === 0) return '';
  // 愿景:去外卡 border + 灰底,纯标题(深紫加粗)+ 正文(深灰)。
  const html = items.map((v) => (
    `<div style="padding:6px 0 10px 0;">` +
    `<div style="font-size:13px;font-weight:700;color:#312e81;margin-bottom:6px;">${escapeHtml(v.title)}</div>` +
    `<div style="font-size:12px;color:#334155;line-height:1.85;">${escapeHtml(v.body)}</div>` +
    `</div>`
  )).join('');
  return (
    blockWrapOpen('padding:4px 0;') + html + blockWrapClose
  );
};

const buildDetailsTableBlock = (checks: SolutionDiagnosisCheck[]): string => {
  if (checks.length === 0) return '';
  // category / status 都是单行短文本,message 可能多行 — 全行 middle 居中,统一视觉.
  const rows = checks.map((c) => (
    `<tr>` +
    `<td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:11px;color:#334155;vertical-align:middle;">${escapeHtml(c.category)}</td>` +
    `<td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:11px;vertical-align:middle;font-weight:700;color:${
      c.status === 'PASS' ? '#166534' :
      c.status === 'WARN' ? '#92400e' :
      c.status === 'FAIL' ? '#991b1b' : '#1e40af'
    };">${escapeHtml(c.status)}</td>` +
    `<td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:11px;color:#0f172a;line-height:1.6;vertical-align:middle;">${escapeHtml(c.message)}</td>` +
    `</tr>`
  )).join('');
  return (
    blockWrapOpen('padding:4px 0;') +
    `<table style="width:100%;border-collapse:collapse;">` +
    `<tbody>${rows}</tbody></table>` +
    blockWrapClose
  );
};

export async function exportSolutionPdf(
  sol: TopicStrategicSolution,
  t: TFunction,
  language: string,
): Promise<void> {
  const blocks: string[] = [];

  blocks.push(buildCoverBlock(sol, t, language));

  if (sol.brand_snapshot) {
    blocks.push(buildSectionHeading(t('admin.solution.section.brand')));
    blocks.push(buildBrandBlock(sol, t));
  }

  if (sol.diagnosis) {
    blocks.push(buildSectionHeading(t('admin.solution.section.diagnosis')));
    blocks.push(buildScoreBlock(sol, t));
    for (const c of sol.diagnosis.clusters) {
      blocks.push(buildClusterBlock(c, language));
    }

    blocks.push(buildSectionHeading(t('admin.solution.section.executionLayers')));
    blocks.push(buildExecutionLayersBlock(sol, t));
  }

  if (sol.seven_steps.length > 0) {
    blocks.push(buildSectionHeading(t('admin.solution.section.sevenSteps')));
    blocks.push(buildSevenStepsBlock(sol.seven_steps, t));
  }

  if (sol.keyword_tiers.length > 0) {
    blocks.push(buildSectionHeading(t('admin.solution.section.keywords')));
    for (const tier of sol.keyword_tiers) {
      blocks.push(buildKeywordTierBlock(tier));
    }
  }

  if (sol.queries_snapshot && sol.queries_snapshot.queries.length > 0) {
    blocks.push(buildSectionHeading(t('admin.solution.section.queries')));
    blocks.push(buildQueriesBlock(sol.queries_snapshot, t));
  }

  if (sol.vision.length > 0) {
    blocks.push(buildSectionHeading(t('admin.solution.section.vision')));
    blocks.push(buildVisionBlock(sol.vision));
  }

  if (sol.diagnosis && sol.diagnosis.all_checks.length > 0) {
    blocks.push(buildSectionHeading(t('admin.solution.section.details')));
    blocks.push(buildDetailsTableBlock(sol.diagnosis.all_checks));
  }

  const brand =
    sol.brand_snapshot?.company_short_name ||
    sol.brand_snapshot?.company_full_name ||
    sol.brand_snapshot?.profile_name ||
    'brand';
  const safeName = brand.replace(/[^a-zA-Z0-9一-龥_-]/g, '-').slice(0, 60);
  const baseName = t('admin.solution.title');
  const headerRight = `${baseName} · ${sol.website_url || ''}`;

  await composeAndSavePdf(
    blocks,
    { rightHeaderText: headerRight, t },
    `${safeName}-${baseName}.pdf`,
  );
}
