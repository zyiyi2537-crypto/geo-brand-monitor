// DOCX 导出 — GEO 体检报告.
//
// 为什么有这个文件:PDF 走 html2canvas + jsPDF,跨平台字体 metric 不一致一直在
// 追文本对齐 bug。DOCX 把渲染交给 Word / WPS / LibreOffice,字体 baseline 由
// 阅读器原生处理,跨平台稳。代价是没法做圆环图 / 渐变背景这种视觉装饰。
// 跟 exportSolutionPdf.ts 并存,前端两个按钮各走各的。

import type { TFunction } from 'i18next';
import {
  AlignmentType, BorderStyle, Document, HeadingLevel, LevelFormat, Packer, Paragraph,
  ShadingType, Table, TableCell, TableRow, TextRun, WidthType,
} from 'docx';
import type {
  TopicStrategicSolution, SolutionDiagnosisCluster,
  SolutionSevenStep, SolutionKeywordTier, SolutionVisionItem,
  SolutionDiagnosisCheck, SolutionQueriesSnapshot,
} from '../services/adminReviewApi';

const COLOR = {
  primary: '0F172A',
  secondary: '475569',
  muted: '94A3B8',
  accent: '6366F1',
  indigo: '312E81',
  green: '166534',
  yellow: '92400E',
  red: '991B1B',
  blue: '1E40AF',
} as const;

const SEVERITY_LABEL_ZH = { high: '重点突破', med: '建议补强', low: '已达标' } as const;
const SEVERITY_LABEL_EN = { high: 'Priority gap', med: 'Reinforce', low: 'On par' } as const;
const SEVERITY_COLOR = { high: COLOR.red, med: COLOR.yellow, low: COLOR.green } as const;

const STATUS_COLOR: Record<string, string> = {
  PASS: COLOR.green, WARN: COLOR.yellow, FAIL: COLOR.red, INFO: COLOR.blue,
};

const titleParagraph = (text: string): Paragraph =>
  new Paragraph({
    spacing: { before: 0, after: 120 },
    children: [new TextRun({ text, bold: true, size: 48, color: COLOR.primary })],
  });

const subtitleParagraph = (text: string): Paragraph =>
  new Paragraph({
    spacing: { before: 0, after: 200 },
    children: [new TextRun({ text, bold: true, size: 28, color: COLOR.secondary })],
  });

const sectionHeading = (text: string): Paragraph =>
  new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    children: [new TextRun({ text, bold: true, size: 32, color: COLOR.primary })],
  });

const subHeading = (text: string, color: string = COLOR.indigo): Paragraph =>
  new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 120 },
    children: [new TextRun({ text, bold: true, size: 26, color })],
  });

const bodyParagraph = (text: string, opts: { color?: string; size?: number; bold?: boolean } = {}): Paragraph =>
  new Paragraph({
    spacing: { before: 0, after: 120 },
    children: [new TextRun({
      text, bold: opts.bold ?? false,
      size: opts.size ?? 22, color: opts.color ?? COLOR.primary,
    })],
  });

const bulletParagraph = (text: string): Paragraph =>
  new Paragraph({
    spacing: { before: 0, after: 60 },
    numbering: { reference: 'bullets', level: 0 },
    children: [new TextRun({ text, size: 21, color: COLOR.secondary })],
  });

const labelValueRow = (label: string, value: string): TableRow =>
  new TableRow({
    children: [
      new TableCell({
        width: { size: 28, type: WidthType.PERCENTAGE },
        margins: { top: 80, bottom: 80, left: 0, right: 120 },
        borders: noBorders(),
        children: [bodyParagraph(label, { color: COLOR.muted, size: 21 })],
      }),
      new TableCell({
        width: { size: 72, type: WidthType.PERCENTAGE },
        margins: { top: 80, bottom: 80, left: 0, right: 0 },
        borders: noBorders(),
        children: [bodyParagraph(value, { color: COLOR.primary, size: 22 })],
      }),
    ],
  });

const noBorders = () => ({
  top:    { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
  bottom: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
  left:   { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
  right:  { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
});

const cellBorder = (color = 'E5E7EB') => ({
  top:    { style: BorderStyle.SINGLE, size: 4, color },
  bottom: { style: BorderStyle.SINGLE, size: 4, color },
  left:   { style: BorderStyle.SINGLE, size: 4, color },
  right:  { style: BorderStyle.SINGLE, size: 4, color },
});

const buildCoverSection = (sol: TopicStrategicSolution, t: TFunction): Paragraph[] => {
  const bp = sol.brand_snapshot;
  const brandName = bp?.company_short_name || bp?.company_full_name || bp?.profile_name || '';
  const out: Paragraph[] = [
    new Paragraph({
      spacing: { before: 0, after: 80 },
      children: [new TextRun({
        text: 'GEO STRATEGY', bold: true, size: 18, color: COLOR.accent,
        characterSpacing: 60,
      })],
    }),
    titleParagraph(String(t('admin.solution.title'))),
  ];
  if (brandName) out.push(subtitleParagraph(brandName));
  return out;
};

const buildCoverTable = (sol: TopicStrategicSolution, t: TFunction, language: string): Table => {
  const bp = sol.brand_snapshot;
  const generatedAt = sol.updated_at
    ? new Date(sol.updated_at).toLocaleString(language.startsWith('zh') ? 'zh-CN' : 'en-US')
    : '';
  const rows: TableRow[] = [
    labelValueRow(String(t('admin.solution.websiteLabel')), sol.website_url || ''),
  ];
  if (bp?.industry) rows.push(labelValueRow(String(t('admin.solution.brandFields.industry')), bp.industry));
  if (bp?.service_geo) rows.push(labelValueRow(String(t('admin.solution.brandFields.service_geo')), bp.service_geo));
  rows.push(labelValueRow(String(t('admin.solution.lastGeneratedAt')), generatedAt));
  if (sol.llm_model) rows.push(labelValueRow(String(t('admin.solution.llmModel')), sol.llm_model));
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: { ...noBorders(), insideHorizontal: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' }, insideVertical: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' } },
    rows,
  });
};

const buildBrandTable = (sol: TopicStrategicSolution, t: TFunction): Table | null => {
  const bp = sol.brand_snapshot;
  if (!bp) return null;
  const fields: [string, string | string[] | null | undefined][] = [
    [t('admin.solution.brandFields.core_business_lines') as string, bp.core_business_lines],
    [t('admin.solution.brandFields.target_scenarios') as string, bp.target_scenarios],
    [t('admin.solution.brandFields.brand_diff_tags') as string, bp.brand_diff_tags],
    [t('admin.solution.brandFields.brand_slogan') as string, bp.brand_slogan],
    [t('admin.solution.brandFields.core_message') as string, bp.core_message],
    [t('admin.solution.brandFields.core_service_overview') as string, bp.core_service_overview],
  ];
  const visible = fields.filter(([, v]) => Array.isArray(v) ? v.length > 0 : !!(v && String(v).trim()));
  if (visible.length === 0) return null;
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: { ...noBorders(), insideHorizontal: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' }, insideVertical: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' } },
    rows: visible.map(([k, v]) => labelValueRow(k, Array.isArray(v) ? v.join('、') : String(v || ''))),
  });
};

const buildScoreParagraphs = (sol: TopicStrategicSolution, t: TFunction): (Paragraph | Table)[] => {
  const d = sol.diagnosis;
  if (!d) return [];
  const out: (Paragraph | Table)[] = [];
  out.push(new Paragraph({
    spacing: { before: 80, after: 80 },
    children: [
      new TextRun({ text: `${t('admin.solution.scoreLabel')}: `, bold: true, size: 22, color: COLOR.muted }),
      new TextRun({ text: `${d.score}`, bold: true, size: 36, color: COLOR.primary }),
      new TextRun({ text: ' / 100', size: 22, color: COLOR.muted }),
      new TextRun({ text: '   ', size: 22 }),
      new TextRun({ text: `${t('admin.solution.gradeLabel', { defaultValue: '评级' })}: `, bold: true, size: 22, color: COLOR.muted }),
      new TextRun({ text: d.grade || '—', bold: true, size: 24, color: COLOR.accent }),
    ],
  }));
  // 4 列计数表
  const tile = (label: string, value: number, color: string): TableCell => new TableCell({
    width: { size: 25, type: WidthType.PERCENTAGE },
    borders: cellBorder('E5E7EB'),
    margins: { top: 120, bottom: 120, left: 120, right: 120 },
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { before: 0, after: 60 },
        children: [new TextRun({ text: `${value}`, bold: true, size: 32, color })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { before: 0, after: 0 },
        children: [new TextRun({ text: label, bold: true, size: 18, color })],
      }),
    ],
  });
  out.push(new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: [new TableRow({
      children: [
        tile(String(t('admin.solution.passLabel')), d.pass_count, COLOR.green),
        tile(String(t('admin.solution.warnLabel')), d.warn_count, COLOR.yellow),
        tile(String(t('admin.solution.failLabel')), d.fail_count, COLOR.red),
        tile(String(t('admin.solution.infoLabel')), d.info_count, COLOR.blue),
      ],
    })],
  }));
  return out;
};

const buildClusterParagraphs = (c: SolutionDiagnosisCluster, language: string): Paragraph[] => {
  const labelMap = language.startsWith('zh') ? SEVERITY_LABEL_ZH : SEVERITY_LABEL_EN;
  const color = SEVERITY_COLOR[c.severity];
  const out: Paragraph[] = [
    new Paragraph({
      spacing: { before: 220, after: 80 },
      children: [
        new TextRun({ text: c.title_zh, bold: true, size: 26, color: COLOR.primary }),
        new TextRun({ text: `   ${labelMap[c.severity]}`, bold: true, size: 20, color }),
      ],
    }),
  ];
  if (c.summary) out.push(bodyParagraph(c.summary, { color: COLOR.secondary, size: 22 }));
  for (const b of (c.bullets || []).slice(0, 6)) {
    out.push(bulletParagraph(b));
  }
  return out;
};

const buildExecutionLayersParagraphs = (sol: TopicStrategicSolution, t: TFunction): Paragraph[] => {
  const layers = sol.diagnosis?.execution_layers || [];
  if (layers.length === 0) return [];
  const out: Paragraph[] = [
    bodyParagraph(String(t('admin.solution.executionLayersHint')), { color: COLOR.secondary, size: 21 }),
  ];
  for (const l of layers) {
    out.push(subHeading(l.title_zh));
    if (l.hint) out.push(bodyParagraph(l.hint, { color: COLOR.muted, size: 21 }));
    for (const c of (l.clusters || [])) {
      out.push(bulletParagraph(c));
    }
  }
  return out;
};

const buildSevenStepsTable = (steps: SolutionSevenStep[], t: TFunction): Table | null => {
  if (steps.length === 0) return null;
  const headerCell = (text: string, width: number): TableCell => new TableCell({
    width: { size: width, type: WidthType.PERCENTAGE },
    borders: cellBorder('CBD5E1'),
    shading: { type: ShadingType.CLEAR, color: 'auto', fill: 'EEF2FF' },
    margins: { top: 120, bottom: 120, left: 120, right: 120 },
    children: [new Paragraph({
      spacing: { before: 0, after: 0 },
      children: [new TextRun({ text, bold: true, size: 20, color: COLOR.indigo })],
    })],
  });
  const bodyCell = (text: string, opts: { bold?: boolean; color?: string; align?: typeof AlignmentType[keyof typeof AlignmentType] } = {}): TableCell => new TableCell({
    borders: cellBorder('E5E7EB'),
    margins: { top: 120, bottom: 120, left: 120, right: 120 },
    children: [new Paragraph({
      spacing: { before: 0, after: 0 },
      alignment: opts.align,
      children: [new TextRun({ text, bold: opts.bold ?? false, size: 21, color: opts.color ?? COLOR.primary })],
    })],
  });
  const headerRow = new TableRow({
    tableHeader: true,
    children: [
      headerCell(String(t('admin.solution.stepCol.step')), 8),
      headerCell(String(t('admin.solution.stepCol.name')), 16),
      headerCell(String(t('admin.solution.stepCol.core_goal')), 20),
      headerCell(String(t('admin.solution.stepCol.core_action')), 36),
      headerCell(String(t('admin.solution.stepCol.output_value')), 20),
    ],
  });
  const dataRows = steps.map((s) => new TableRow({
    children: [
      bodyCell(String(s.step), { bold: true, color: COLOR.indigo, align: AlignmentType.CENTER }),
      bodyCell(s.name, { bold: true }),
      bodyCell(s.core_goal, { color: COLOR.secondary }),
      bodyCell(s.core_action),
      bodyCell(s.output_value, { color: COLOR.secondary }),
    ],
  }));
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: [headerRow, ...dataRows],
  });
};

const buildKeywordTierParagraphs = (tier: SolutionKeywordTier): Paragraph[] => {
  const out: Paragraph[] = [subHeading(tier.title_zh, COLOR.primary)];
  if (tier.description) out.push(bodyParagraph(tier.description, { color: COLOR.muted, size: 21 }));
  if (tier.keywords.length > 0) {
    out.push(new Paragraph({
      spacing: { before: 40, after: 80 },
      children: [new TextRun({ text: tier.keywords.join('  ·  '), size: 22, color: COLOR.indigo })],
    }));
  } else {
    out.push(bodyParagraph('—', { color: COLOR.muted, size: 22 }));
  }
  return out;
};

const buildQueriesParagraphs = (snapshot: SolutionQueriesSnapshot, t: TFunction): Paragraph[] => {
  if (!snapshot.queries.length) return [];
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
  const out: Paragraph[] = [
    bodyParagraph(
      `${String(t('admin.solution.queries.hint'))}  ·  ${String(t('admin.solution.queries.totalChip', { n: snapshot.queries.length }))}`,
      { color: COLOR.secondary, size: 21 },
    ),
  ];
  for (const key of order) {
    const items = grouped.get(key) || [];
    const label = key === unseededKey ? unseededLabel : key;
    out.push(new Paragraph({
      spacing: { before: 200, after: 80 },
      children: [
        new TextRun({ text: label, bold: true, size: 24, color: COLOR.primary }),
        new TextRun({ text: `  (${items.length})`, size: 20, color: COLOR.muted }),
      ],
    }));
    out.push(new Paragraph({
      spacing: { before: 0, after: 80 },
      children: [new TextRun({
        text: items.join('  ·  '), size: 21, color: COLOR.indigo,
      })],
    }));
  }
  return out;
};

const buildVisionParagraphs = (items: SolutionVisionItem[]): Paragraph[] => {
  const out: Paragraph[] = [];
  for (const v of items) {
    out.push(subHeading(v.title));
    out.push(bodyParagraph(v.body, { color: COLOR.primary, size: 22 }));
  }
  return out;
};

const buildDetailsTable = (checks: SolutionDiagnosisCheck[], t: TFunction): Table | null => {
  if (checks.length === 0) return null;
  const headerCell = (text: string, width: number): TableCell => new TableCell({
    width: { size: width, type: WidthType.PERCENTAGE },
    borders: cellBorder('CBD5E1'),
    shading: { type: ShadingType.CLEAR, color: 'auto', fill: 'EEF2FF' },
    margins: { top: 100, bottom: 100, left: 120, right: 120 },
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, size: 20, color: COLOR.indigo })] })],
  });
  const headerRow = new TableRow({
    tableHeader: true,
    children: [
      headerCell(String(t('admin.solution.details.category', { defaultValue: '分类' })), 30),
      headerCell(String(t('admin.solution.details.status', { defaultValue: '状态' })), 12),
      headerCell(String(t('admin.solution.details.message', { defaultValue: '说明' })), 58),
    ],
  });
  const dataRows = checks.map((c) => new TableRow({
    children: [
      new TableCell({
        borders: cellBorder('E5E7EB'),
        margins: { top: 100, bottom: 100, left: 120, right: 120 },
        children: [new Paragraph({ children: [new TextRun({ text: c.category, size: 20, color: COLOR.primary })] })],
      }),
      new TableCell({
        borders: cellBorder('E5E7EB'),
        margins: { top: 100, bottom: 100, left: 120, right: 120 },
        children: [new Paragraph({
          children: [new TextRun({
            text: c.status, bold: true, size: 20, color: STATUS_COLOR[c.status] || COLOR.blue,
          })],
        })],
      }),
      new TableCell({
        borders: cellBorder('E5E7EB'),
        margins: { top: 100, bottom: 100, left: 120, right: 120 },
        children: [new Paragraph({ children: [new TextRun({ text: c.message, size: 20, color: COLOR.primary })] })],
      }),
    ],
  }));
  return new Table({ width: { size: 100, type: WidthType.PERCENTAGE }, rows: [headerRow, ...dataRows] });
};

export async function exportSolutionDocx(
  sol: TopicStrategicSolution,
  t: TFunction,
  language: string,
): Promise<void> {
  const children: (Paragraph | Table)[] = [];
  children.push(...buildCoverSection(sol, t));
  children.push(buildCoverTable(sol, t, language));

  if (sol.brand_snapshot) {
    children.push(sectionHeading(String(t('admin.solution.section.brand'))));
    const tbl = buildBrandTable(sol, t);
    if (tbl) children.push(tbl);
  }

  if (sol.diagnosis) {
    children.push(sectionHeading(String(t('admin.solution.section.diagnosis'))));
    children.push(...buildScoreParagraphs(sol, t));
    for (const c of sol.diagnosis.clusters) {
      children.push(...buildClusterParagraphs(c, language));
    }

    children.push(sectionHeading(String(t('admin.solution.section.executionLayers'))));
    children.push(...buildExecutionLayersParagraphs(sol, t));
  }

  if (sol.seven_steps.length > 0) {
    children.push(sectionHeading(String(t('admin.solution.section.sevenSteps'))));
    const tbl = buildSevenStepsTable(sol.seven_steps, t);
    if (tbl) children.push(tbl);
  }

  if (sol.keyword_tiers.length > 0) {
    children.push(sectionHeading(String(t('admin.solution.section.keywords'))));
    for (const tier of sol.keyword_tiers) {
      children.push(...buildKeywordTierParagraphs(tier));
    }
  }

  if (sol.queries_snapshot && sol.queries_snapshot.queries.length > 0) {
    children.push(sectionHeading(String(t('admin.solution.section.queries'))));
    children.push(...buildQueriesParagraphs(sol.queries_snapshot, t));
  }

  if (sol.vision.length > 0) {
    children.push(sectionHeading(String(t('admin.solution.section.vision'))));
    children.push(...buildVisionParagraphs(sol.vision));
  }

  if (sol.diagnosis && sol.diagnosis.all_checks.length > 0) {
    children.push(sectionHeading(String(t('admin.solution.section.details'))));
    const tbl = buildDetailsTable(sol.diagnosis.all_checks, t);
    if (tbl) children.push(tbl);
  }

  const doc = new Document({
    creator: 'Vigilath',
    title: String(t('admin.solution.title')),
    styles: {
      default: {
        document: { run: { font: 'PingFang SC' } },
      },
    },
    numbering: {
      config: [{
        reference: 'bullets',
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: '•',
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 360, hanging: 240 } } },
        }],
      }],
    },
    sections: [{ children }],
  });

  const blob = await Packer.toBlob(doc);
  const brand =
    sol.brand_snapshot?.company_short_name ||
    sol.brand_snapshot?.company_full_name ||
    sol.brand_snapshot?.profile_name ||
    'brand';
  const safeName = brand.replace(/[^a-zA-Z0-9一-龥_-]/g, '-').slice(0, 60);
  const baseName = String(t('admin.solution.title'));
  const fileName = `${safeName}-${baseName}.docx`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
