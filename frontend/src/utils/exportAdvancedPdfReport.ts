// Per-mode PDF templates for the 6 advanced check modes. Each mode has
// its own buildBlocks function that returns an array of HTML blocks; the
// shared pipeline in pdfPrimitives.ts captures them, paginates, and saves.
//
// Different modes show different things — e.g. visibility highlights an
// AI score with dimension breakdown, crawlTest highlights crawler access
// rather than a score, compare shows a multi-site leaderboard.

import type { TFunction } from 'i18next';
import type {
  AdvancedMode,
  AeoVisibilityResponse,
  AiVisibilityResponse,
  AuthorityAuditResponse,
  CitationCheckResponse,
  CompareResponse,
  CrawlTestResponse,
  EntityAuditResponse,
} from '../types/advanced';
import {
  blockWrapClose,
  blockWrapOpen,
  composeAndSavePdf,
  escapeHtml,
} from './pdfPrimitives';

// ---------- Shared building blocks ----------

const fmtPercent = (n: number): string => `${Math.round(n)}%`;
const fmtScore = (earned: number, max: number): string => `${earned}/${max}`;
const safeFile = (s: string): string => s.replace(/[^a-zA-Z0-9]/g, '-').slice(0, 60) || 'site';

const todayStamp = (): string => {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
};

const localeFor = (language: string): string => (language.startsWith('zh') ? 'zh-CN' : 'en-US');

interface CoverRow { label: string; value: string; }

const coverBlock = (args: {
  badge: string;
  title: string;
  subtitle?: string;
  rows: CoverRow[];
  accent?: string;
}): string => {
  const accent = args.accent || '#0ea5e9';
  const tableRows = args.rows
    .map(
      (r) =>
        `<tr>` +
        `<td style="padding:3px 0;width:120px;color:#94a3b8;">${escapeHtml(r.label)}</td>` +
        `<td style="padding:3px 0;font-weight:600;color:#0f172a;word-break:break-all;">${escapeHtml(r.value)}</td>` +
        `</tr>`,
    )
    .join('');
  return (
    blockWrapOpen(`padding:4px 0 18px 0;border-bottom:3px solid ${accent};margin-bottom:8px;`) +
    `<div style="font-size:11px;letter-spacing:0.22em;color:${accent};text-transform:uppercase;font-weight:700;margin-bottom:6px;">${escapeHtml(args.badge)}</div>` +
    `<div style="font-size:24px;font-weight:800;line-height:1.25;margin-bottom:6px;color:#0f172a;">${escapeHtml(args.title)}</div>` +
    (args.subtitle
      ? `<div style="font-size:12px;color:#475569;margin-bottom:14px;line-height:1.5;">${escapeHtml(args.subtitle)}</div>`
      : '') +
    `<table style="width:100%;font-size:11.5px;color:#334155;border-collapse:collapse;">${tableRows}</table>` +
    blockWrapClose
  );
};

const sectionHeading = (text: string, accent = '#0ea5e9'): string =>
  blockWrapOpen('padding:10px 0 4px 0;') +
  `<div style="font-size:15px;font-weight:800;color:#0f172a;border-left:4px solid ${accent};padding-left:10px;">${escapeHtml(text)}</div>` +
  blockWrapClose;

type StatTone = 'good' | 'warn' | 'bad' | 'neutral';
const TONE_BG: Record<StatTone, { bg: string; fg: string }> = {
  good: { bg: '#dcfce7', fg: '#166534' },
  warn: { bg: '#fef3c7', fg: '#92400e' },
  bad: { bg: '#fee2e2', fg: '#991b1b' },
  neutral: { bg: '#dbeafe', fg: '#1e40af' },
};

interface SubStat { label: string; value: string | number; tone?: StatTone; }

// Hero block: dark gradient score card on the left, optional sub-stats grid on the right.
const scoreHero = (args: {
  scoreLabel: string;
  scoreValue: string | number;
  scoreSuffix?: string;
  grade?: string;
  gradeNote?: string;
  rightStats?: SubStat[];
  rightCaption?: string;
}): string => {
  const grade = args.grade
    ? `<div style="margin-top:10px;font-size:15px;font-weight:700;color:#22d3ee;">${escapeHtml(args.grade)}${args.gradeNote ? ` · ${escapeHtml(args.gradeNote)}` : ''}</div>`
    : '';
  const tiles = (args.rightStats || [])
    .map((s) => {
      const c = TONE_BG[s.tone || 'neutral'];
      return `<div style="flex:1;background:${c.bg};border-radius:8px;padding:6px 6px 12px 6px;text-align:center;"><div style="font-size:18px;font-weight:800;color:${c.fg};">${escapeHtml(s.value)}</div><div style="font-size:9px;color:${c.fg};font-weight:600;margin-top:3px;">${escapeHtml(s.label)}</div></div>`;
    })
    .join('');
  const right =
    args.rightStats && args.rightStats.length > 0
      ? `<div style="flex:1;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;box-sizing:border-box;">` +
        (args.rightCaption
          ? `<div style="font-size:11px;font-weight:700;color:#0f172a;margin-bottom:8px;">${escapeHtml(args.rightCaption)}</div>`
          : '') +
        `<div style="display:flex;gap:8px;">${tiles}</div>` +
        `</div>`
      : '';
  return (
    blockWrapOpen('padding:0 0 8px 0;') +
    `<div style="display:flex;gap:14px;align-items:stretch;">` +
    `<div style="flex-shrink:0;width:180px;background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;border-radius:12px;padding:18px;text-align:center;box-sizing:border-box;">` +
    `<div style="font-size:10px;letter-spacing:0.16em;color:#94a3b8;text-transform:uppercase;margin-bottom:6px;">${escapeHtml(args.scoreLabel)}</div>` +
    `<div style="font-size:42px;font-weight:800;line-height:1;color:#22d3ee;">${escapeHtml(args.scoreValue)}</div>` +
    (args.scoreSuffix ? `<div style="font-size:11px;color:#94a3b8;margin-top:4px;">${escapeHtml(args.scoreSuffix)}</div>` : '') +
    grade +
    `</div>` +
    right +
    `</div>` +
    blockWrapClose
  );
};

// Generic key→value table.
const kvTable = (rows: Array<{ k: string; v: string; vColor?: string }>): string => {
  if (rows.length === 0) return '';
  const body = rows
    .map(
      (r) =>
        `<tr>` +
        `<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#475569;font-size:11px;width:40%;">${escapeHtml(r.k)}</td>` +
        `<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:${r.vColor || '#0f172a'};font-size:11.5px;font-weight:600;">${escapeHtml(r.v)}</td>` +
        `</tr>`,
    )
    .join('');
  return (
    blockWrapOpen('padding:4px 0 8px 0;') +
    `<table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">${body}</table>` +
    blockWrapClose
  );
};

interface DataTableCell { value: string; align?: 'left' | 'center' | 'right'; color?: string; bold?: boolean; }
type DataRow = Array<string | DataTableCell>;

const dataTable = (headers: string[], rows: DataRow[]): string => {
  if (rows.length === 0) return '';
  const head = headers
    .map(
      (h, i) =>
        `<th style="padding:9px 10px;text-align:${i === 0 ? 'left' : 'center'};font-size:10px;color:#475569;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;">${escapeHtml(h)}</th>`,
    )
    .join('');
  // word-break + overflow-wrap so long CJK strings (e.g. truncated meta-desc
  // queries) wrap inside the cell rather than overflow the table.
  const tdBase = 'padding:9px 10px;border-bottom:1px solid #e5e7eb;word-break:break-word;overflow-wrap:anywhere;';
  const body = rows
    .map(
      (r) =>
        `<tr>${r
          .map((cell, i) => {
            if (typeof cell === 'string') {
              return `<td style="${tdBase}text-align:${i === 0 ? 'left' : 'center'};color:#0f172a;${i === 0 ? 'font-weight:600;' : ''}">${escapeHtml(cell)}</td>`;
            }
            const align = cell.align || (i === 0 ? 'left' : 'center');
            const color = cell.color || '#0f172a';
            const bold = cell.bold ? 'font-weight:700;' : '';
            return `<td style="${tdBase}text-align:${align};color:${color};${bold}">${escapeHtml(cell.value)}</td>`;
          })
          .join('')}</tr>`,
    )
    .join('');
  return (
    blockWrapOpen('padding:4px 0 10px 0;') +
    `<table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;font-size:11.5px;">` +
    `<thead><tr style="background:#f1f5f9;">${head}</tr></thead>` +
    `<tbody>${body}</tbody>` +
    `</table>` +
    blockWrapClose
  );
};

const callout = (text: string, tone: StatTone | 'neutral' = 'neutral'): string => {
  const c = TONE_BG[tone];
  const borderMap: Record<StatTone, string> = {
    good: '#10b981',
    warn: '#f59e0b',
    bad: '#ef4444',
    neutral: '#3b82f6',
  };
  return (
    blockWrapOpen('padding:2px 0 4px 0;') +
    `<div style="font-size:11px;color:${c.fg};background:${c.bg};border-left:3px solid ${borderMap[tone]};padding:10px 12px;border-radius:6px;line-height:1.6;">${escapeHtml(text)}</div>` +
    blockWrapClose
  );
};

const bulletList = (heading: string, items: string[], emptyText?: string): string => {
  if (items.length === 0 && !emptyText) return '';
  const body =
    items.length > 0
      ? `<ul style="margin:0;padding:0 0 0 18px;font-size:11.5px;color:#334155;line-height:1.7;">${items
          .map((i) => `<li style="margin-bottom:3px;">${escapeHtml(i)}</li>`)
          .join('')}</ul>`
      : `<div style="font-size:11px;color:#94a3b8;font-style:italic;">${escapeHtml(emptyText || '')}</div>`;
  return (
    blockWrapOpen('padding:6px 0 4px 0;') +
    `<div style="font-size:12px;font-weight:700;color:#0f172a;margin-bottom:6px;">${escapeHtml(heading)}</div>` +
    body +
    blockWrapClose
  );
};

// Tone derivation from a 0-100 percent.
const toneForPercent = (p: number): StatTone => (p >= 75 ? 'good' : p >= 50 ? 'warn' : 'bad');

// ---------- compare ----------

const buildCompareBlocks = (data: CompareResponse, t: TFunction, language: string): string[] => {
  const blocks: string[] = [];
  const generatedAt = new Date().toLocaleString(localeFor(language));
  const subtitle = t('home.advanced.cards.compare.desc', { defaultValue: '' }) as string;

  blocks.push(
    coverBlock({
      badge: t('home.advanced.cards.compare.title', { defaultValue: 'Competitive Comparison' }) as string,
      title: t('result.advancedPdf.compare.title', { defaultValue: 'Competitive GEO Comparison' }) as string,
      subtitle,
      rows: [
        { label: t('result.advancedPdf.urlsCount', { defaultValue: 'URLs compared' }) as string, value: String(data.urls.length) },
        { label: t('result.pdfReport.generatedAt') as string, value: generatedAt },
      ],
      accent: '#06b6d4',
    }),
  );

  if (data.winner) {
    blocks.push(
      scoreHero({
        scoreLabel: t('result.advancedPdf.compare.winner', { defaultValue: 'Winner' }) as string,
        scoreValue: data.winner.score,
        scoreSuffix: '/ 100',
        grade: data.winner.grade,
        gradeNote: data.winner.domain,
        rightStats: [
          { label: t('result.advancedPdf.compare.lead', { defaultValue: 'Lead (pts)' }) as string, value: data.winner.lead, tone: 'good' },
          { label: t('result.advancedPdf.compare.contestants', { defaultValue: 'Sites' }) as string, value: data.results.length, tone: 'neutral' },
        ],
      }),
    );
  }

  blocks.push(
    sectionHeading(t('result.advancedPdf.compare.leaderboard', { defaultValue: 'Site Leaderboard' }) as string, '#06b6d4'),
  );
  const sorted = [...data.results].sort((a, b) => b.score - a.score);
  blocks.push(
    dataTable(
      [
        '#',
        t('result.advancedPdf.compare.domain', { defaultValue: 'Domain' }) as string,
        t('result.advancedPdf.compare.score', { defaultValue: 'Score' }) as string,
        t('result.advancedPdf.compare.grade', { defaultValue: 'Grade' }) as string,
      ],
      sorted.map((r, i) => [
        { value: String(i + 1), align: 'center' as const },
        { value: r.domain, align: 'left' as const, bold: true },
        { value: String(r.score), align: 'center' as const, bold: true, color: i === 0 ? '#166534' : '#0f172a' },
        { value: r.grade, align: 'center' as const, color: i === 0 ? '#166534' : '#0f172a' },
      ]),
    ),
  );

  if (data.advantages && data.advantages.length > 0) {
    blocks.push(
      sectionHeading(
        t('result.advancedPdf.compare.advantages', { defaultValue: 'Per-Category Leaders' }) as string,
        '#8b5cf6',
      ),
    );
    blocks.push(
      dataTable(
        [
          t('home.advanced.result.compare.category', { defaultValue: 'Category' }) as string,
          t('result.advancedPdf.compare.topDomain', { defaultValue: 'Top domain' }) as string,
          t('result.advancedPdf.compare.share', { defaultValue: 'Share' }) as string,
        ],
        data.advantages.map((adv) => {
          const top = adv.ranked[0];
          return [
            adv.category,
            { value: top?.domain || '—', align: 'center' as const, bold: true },
            { value: top ? fmtPercent(top.percent) : '—', align: 'center' as const },
          ];
        }),
      ),
    );
  }

  return blocks;
};

// ---------- crawlTest ----------

const buildCrawlTestBlocks = (data: CrawlTestResponse, t: TFunction, language: string): string[] => {
  const blocks: string[] = [];
  const generatedAt = new Date().toLocaleString(localeFor(language));

  blocks.push(
    coverBlock({
      badge: t('home.advanced.cards.crawlTest.title', { defaultValue: 'AI Crawler Test' }) as string,
      title: t('result.advancedPdf.crawlTest.title', { defaultValue: 'AI Crawler Accessibility' }) as string,
      subtitle: t('home.advanced.cards.crawlTest.desc', { defaultValue: '' }) as string,
      rows: [
        { label: t('result.pdfReport.targetSite') as string, value: data.url },
        { label: t('home.advanced.result.crawl.targetDomain') as string, value: data.domain },
        { label: t('result.pdfReport.generatedAt') as string, value: generatedAt },
      ],
      accent: '#8b5cf6',
    }),
  );

  const robotsAllowed = data.robots.bots.filter((b) => b.status === 'allowed' || b.status === 'allow').length;
  const wafPassed = data.waf.bots.filter((b) => b.result === 'pass' || b.result === 'ok').length;
  const issuesTone: StatTone = data.total_issues === 0 ? 'good' : data.total_issues > 3 ? 'bad' : 'warn';

  blocks.push(
    scoreHero({
      scoreLabel: t('home.advanced.result.crawl.totalIssues') as string,
      scoreValue: data.total_issues,
      scoreSuffix: data.total_issues === 0
        ? (t('home.advanced.result.crawl.allClear') as string)
        : (t('home.advanced.result.crawl.needsFix') as string),
      grade: data.total_issues === 0 ? 'A' : data.total_issues > 3 ? 'F' : 'C',
      rightStats: [
        { label: t('home.advanced.result.crawl.robotsAllowed') as string, value: `${robotsAllowed}/${data.robots.bots.length}`, tone: 'neutral' },
        { label: t('home.advanced.result.crawl.wafAllowed') as string, value: `${wafPassed}/${data.waf.bots.length}`, tone: issuesTone },
      ],
    }),
  );

  // robots.txt section
  blocks.push(sectionHeading(t('home.advanced.result.crawl.robotsTitle') as string, '#8b5cf6'));
  if (!data.robots.found) {
    blocks.push(callout(t('home.advanced.result.crawl.robotsMissingWarning') as string, 'warn'));
  } else {
    blocks.push(
      dataTable(
        [
          t('result.advancedPdf.crawlTest.bot', { defaultValue: 'Bot' }) as string,
          t('result.advancedPdf.crawlTest.userAgent', { defaultValue: 'User-Agent' }) as string,
          t('result.advancedPdf.crawlTest.status', { defaultValue: 'Status' }) as string,
        ],
        data.robots.bots.map((b) => {
          const allowed = b.status === 'allowed' || b.status === 'allow';
          return [
            { value: b.bot, align: 'left' as const, bold: true },
            { value: b.ua, align: 'left' as const },
            { value: b.status, align: 'center' as const, color: allowed ? '#166534' : '#991b1b', bold: true },
          ];
        }),
      ),
    );
  }

  // WAF section
  blocks.push(sectionHeading(t('home.advanced.result.crawl.wafTitle') as string, '#ec4899'));
  blocks.push(
    callout(
      t('home.advanced.result.crawl.wafBaseline', {
        status: data.waf.baseline_status ?? '—',
        size: Math.round(data.waf.baseline_size / 1024),
      }) as string,
      'neutral',
    ),
  );
  blocks.push(
    dataTable(
      [
        t('result.advancedPdf.crawlTest.bot', { defaultValue: 'Bot' }) as string,
        t('result.advancedPdf.crawlTest.statusCode', { defaultValue: 'HTTP' }) as string,
        t('result.advancedPdf.crawlTest.sizeKb', { defaultValue: 'Size (KB)' }) as string,
        t('result.advancedPdf.crawlTest.result', { defaultValue: 'Result' }) as string,
      ],
      data.waf.bots.map((b) => {
        const ok = b.result === 'pass' || b.result === 'ok';
        return [
          { value: b.bot, align: 'left' as const, bold: true },
          { value: b.status_code !== null ? String(b.status_code) : '—', align: 'center' as const },
          { value: String(Math.round(b.size / 1024)), align: 'center' as const },
          { value: b.error || b.result, align: 'center' as const, color: ok ? '#166534' : '#991b1b', bold: true },
        ];
      }),
    ),
  );

  // Common Crawl section
  blocks.push(sectionHeading(t('home.advanced.result.crawl.commonCrawlTitle') as string, '#0ea5e9'));
  if (data.common_crawl.found) {
    blocks.push(
      callout(
        `${t('home.advanced.result.crawl.foundInCcPrefix') as string}${data.common_crawl.count}${t('home.advanced.result.crawl.foundInCcSuffix') as string}`,
        'good',
      ),
    );
    if (data.common_crawl.samples.length > 0) {
      blocks.push(
        bulletList(
          t('result.advancedPdf.crawlTest.ccSamples', { defaultValue: 'Sample indexed pages' }) as string,
          data.common_crawl.samples.slice(0, 8),
        ),
      );
    }
  } else {
    blocks.push(callout(t('home.advanced.result.crawl.notIndexed') as string, 'warn'));
  }

  return blocks;
};

// ---------- authority ----------

const buildAuthorityBlocks = (data: AuthorityAuditResponse, t: TFunction, language: string): string[] => {
  const blocks: string[] = [];
  const generatedAt = new Date().toLocaleString(localeFor(language));

  blocks.push(
    coverBlock({
      badge: t('home.advanced.cards.authority.title', { defaultValue: 'Authority Audit' }) as string,
      title: t('result.advancedPdf.authority.title', { defaultValue: 'Off-Page Authority Audit' }) as string,
      subtitle: t('home.advanced.cards.authority.desc', { defaultValue: '' }) as string,
      rows: [
        { label: t('result.pdfReport.targetSite') as string, value: data.url },
        { label: t('result.advancedPdf.brand', { defaultValue: 'Brand' }) as string, value: data.brand },
        { label: t('result.pdfReport.generatedAt') as string, value: generatedAt },
      ],
      accent: '#f59e0b',
    }),
  );

  blocks.push(
    scoreHero({
      scoreLabel: t('result.advancedPdf.authority.score', { defaultValue: 'Authority Score' }) as string,
      scoreValue: fmtPercent(data.percent),
      scoreSuffix: fmtScore(data.score, data.max_score),
      grade: data.grade,
      rightStats: [
        {
          label: t('result.advancedPdf.authority.reviews', { defaultValue: 'Review platforms' }) as string,
          value: data.reviews.platforms.length,
          tone: data.reviews.platforms.length >= 3 ? 'good' : 'warn',
        },
        {
          label: t('result.advancedPdf.authority.awards', { defaultValue: 'Award signals' }) as string,
          value: data.awards.signal_count,
          tone: data.awards.signal_count >= 2 ? 'good' : 'neutral',
        },
        {
          label: t('result.advancedPdf.authority.kg', { defaultValue: 'Knowledge Graph' }) as string,
          value: data.google.wikipedia_or_wikidata ? '✓' : '—',
          tone: data.google.wikipedia_or_wikidata ? 'good' : 'warn',
        },
      ],
    }),
  );

  // Reviews
  blocks.push(sectionHeading(t('result.advancedPdf.authority.reviewsSection', { defaultValue: 'Review Coverage' }) as string, '#f59e0b'));
  blocks.push(
    kvTable([
      {
        k: t('result.advancedPdf.authority.platforms', { defaultValue: 'Platforms found' }) as string,
        v: data.reviews.platforms.length > 0 ? data.reviews.platforms.join(', ') : '—',
      },
      {
        k: t('result.advancedPdf.authority.reviewSchema', { defaultValue: 'Review schema present' }) as string,
        v: data.reviews.has_schema ? '✓' : '—',
        vColor: data.reviews.has_schema ? '#166534' : '#991b1b',
      },
    ]),
  );

  // Awards
  blocks.push(sectionHeading(t('result.advancedPdf.authority.awardsSection', { defaultValue: 'Awards & Trust Signals' }) as string, '#ef4444'));
  blocks.push(
    kvTable([
      {
        k: t('result.advancedPdf.authority.awardKeywords', { defaultValue: 'Keywords detected' }) as string,
        v: data.awards.keywords.length > 0 ? data.awards.keywords.slice(0, 6).join(', ') : '—',
      },
      {
        k: t('result.advancedPdf.authority.badges', { defaultValue: 'Badges' }) as string,
        v: data.awards.badges.length > 0 ? data.awards.badges.slice(0, 6).join(', ') : '—',
      },
      {
        k: t('result.advancedPdf.authority.signalCount', { defaultValue: 'Total signals' }) as string,
        v: String(data.awards.signal_count),
      },
    ]),
  );

  // Google KG
  blocks.push(sectionHeading(t('result.advancedPdf.authority.googleSection', { defaultValue: 'Google Knowledge Graph' }) as string, '#0ea5e9'));
  blocks.push(
    kvTable([
      {
        k: t('result.advancedPdf.authority.indexedPages', { defaultValue: 'Indexed pages (estimate)' }) as string,
        v: data.google.indexed_pages !== null ? String(data.google.indexed_pages) : '—',
      },
      {
        k: t('result.advancedPdf.authority.kgFields', { defaultValue: 'KG schema fields' }) as string,
        v: String(data.google.kg_schema_fields),
      },
      {
        k: t('result.advancedPdf.authority.wikipedia', { defaultValue: 'Wikipedia / Wikidata' }) as string,
        v: data.google.wikipedia_or_wikidata ? '✓' : '—',
        vColor: data.google.wikipedia_or_wikidata ? '#166534' : '#991b1b',
      },
    ]),
  );

  // Mentions
  if (data.mentions.platforms.length > 0) {
    blocks.push(sectionHeading(t('result.advancedPdf.authority.mentionsSection', { defaultValue: 'Brand Mentions' }) as string, '#8b5cf6'));
    blocks.push(
      bulletList(
        t('result.advancedPdf.authority.mentionPlatforms', { defaultValue: 'Mentioned on' }) as string,
        data.mentions.platforms,
      ),
    );
  }

  return blocks;
};

// ---------- citation ----------

const buildCitationBlocks = (data: CitationCheckResponse, t: TFunction, language: string): string[] => {
  const blocks: string[] = [];
  const generatedAt = new Date().toLocaleString(localeFor(language));

  blocks.push(
    coverBlock({
      badge: t('home.advanced.cards.citation.title', { defaultValue: 'AI Citation Check' }) as string,
      title: t('result.advancedPdf.citation.title', { defaultValue: 'AI Citation Check' }) as string,
      subtitle: t('home.advanced.cards.citation.desc', { defaultValue: '' }) as string,
      rows: [
        { label: t('result.pdfReport.targetSite') as string, value: data.url },
        { label: t('result.advancedPdf.brand', { defaultValue: 'Brand' }) as string, value: data.brand },
        { label: t('result.advancedPdf.engine', { defaultValue: 'Engine' }) as string, value: data.engine },
        { label: t('result.pdfReport.generatedAt') as string, value: generatedAt },
      ],
      accent: '#10b981',
    }),
  );

  blocks.push(
    scoreHero({
      scoreLabel: t('home.advanced.result.citation.overallScore') as string,
      scoreValue: fmtPercent(data.citation_rate),
      scoreSuffix: t('home.advanced.result.citation.queriesSuffix', { count: data.total_queries }) as string,
      grade: data.grade,
      rightStats: [
        {
          label: t('home.advanced.result.citation.cited') as string,
          value: `${data.cited_queries}/${data.valid_queries}`,
          tone: toneForPercent((data.cited_queries / Math.max(1, data.valid_queries)) * 100),
        },
        {
          label: t('home.advanced.result.citation.directCitations') as string,
          value: data.total_citations,
          tone: data.total_citations > 0 ? 'good' : 'bad',
        },
      ],
    }),
  );

  blocks.push(sectionHeading(t('home.advanced.result.citation.perQuery') as string, '#10b981'));
  blocks.push(
    dataTable(
      [
        '#',
        t('result.advancedPdf.citation.query', { defaultValue: 'Query' }) as string,
        t('home.advanced.result.citation.cited') as string,
        t('result.advancedPdf.citation.citationCount', { defaultValue: 'Citations' }) as string,
      ],
      data.queries.map((q, i) => [
        { value: String(i + 1), align: 'center' as const },
        { value: q.query, align: 'left' as const },
        {
          value: q.cited ? '✓' : '—',
          align: 'center' as const,
          color: q.cited ? '#166534' : '#991b1b',
          bold: true,
        },
        { value: String(q.citations.length), align: 'center' as const },
      ]),
    ),
  );

  return blocks;
};

// ---------- visibility ----------

const buildVisibilityBlocks = (data: AiVisibilityResponse, t: TFunction, language: string): string[] => {
  const blocks: string[] = [];
  const generatedAt = new Date().toLocaleString(localeFor(language));

  blocks.push(
    coverBlock({
      badge: t('home.advanced.cards.visibility.title', { defaultValue: 'AI Visibility Audit' }) as string,
      title: t('result.advancedPdf.visibility.title', { defaultValue: 'Multi-Engine AI Visibility Audit' }) as string,
      subtitle: t('home.advanced.cards.visibility.desc', { defaultValue: '' }) as string,
      rows: [
        { label: t('result.pdfReport.targetSite') as string, value: data.url },
        { label: t('result.advancedPdf.brand', { defaultValue: 'Brand' }) as string, value: data.brand },
        {
          label: t('result.advancedPdf.engines', { defaultValue: 'Engines' }) as string,
          value: data.engines.join(', '),
        },
        { label: t('result.pdfReport.generatedAt') as string, value: generatedAt },
      ],
      accent: '#a855f7',
    }),
  );

  blocks.push(
    scoreHero({
      scoreLabel: t('result.advancedPdf.visibility.score', { defaultValue: 'Visibility Score' }) as string,
      scoreValue: fmtScore(data.total_score, data.max_score),
      scoreSuffix: t('home.advanced.result.visibility.queryBreakdown', {
        count: data.query_count,
        runs: data.stability_runs,
      }) as string,
      grade: data.grade,
      gradeNote: data.grade_label,
      rightStats: [
        { label: t('result.advancedPdf.visibility.dimVisibility', { defaultValue: 'Visibility' }) as string, value: data.scores.visibility, tone: 'neutral' },
        { label: t('result.advancedPdf.visibility.dimEntity', { defaultValue: 'Entity' }) as string, value: data.scores.entity, tone: 'neutral' },
        { label: t('result.advancedPdf.visibility.dimStability', { defaultValue: 'Stability' }) as string, value: data.scores.stability, tone: 'neutral' },
      ],
    }),
  );

  // Dimension scores
  blocks.push(sectionHeading(t('result.advancedPdf.visibility.dimensionScores', { defaultValue: 'Dimension Scores' }) as string, '#a855f7'));
  blocks.push(
    kvTable([
      { k: t('result.advancedPdf.visibility.dimVisibility', { defaultValue: 'Visibility' }) as string, v: String(data.scores.visibility) },
      { k: t('result.advancedPdf.visibility.dimEntity', { defaultValue: 'Entity' }) as string, v: String(data.scores.entity) },
      { k: t('result.advancedPdf.visibility.dimCompetitor', { defaultValue: 'Competitor' }) as string, v: String(data.scores.competitor) },
      { k: t('result.advancedPdf.visibility.dimStability', { defaultValue: 'Stability' }) as string, v: String(data.scores.stability) },
      { k: t('result.advancedPdf.visibility.dimContentGap', { defaultValue: 'Content gap' }) as string, v: String(data.scores.content_gap) },
    ]),
  );

  // Per-engine rates
  blocks.push(sectionHeading(t('home.advanced.result.visibility.perEngineRate') as string, '#06b6d4'));
  blocks.push(
    dataTable(
      [
        t('result.advancedPdf.visibility.engine', { defaultValue: 'Engine' }) as string,
        t('result.advancedPdf.visibility.rate', { defaultValue: 'Visibility' }) as string,
      ],
      Object.entries(data.per_engine_rates).map(([engine, rate]) => [
        { value: engine, align: 'left' as const, bold: true },
        {
          value: fmtPercent(rate),
          align: 'center' as const,
          color: rate >= 50 ? '#166534' : rate >= 25 ? '#92400e' : '#991b1b',
          bold: true,
        },
      ]),
    ),
  );

  // Competitors
  if (data.top_competitors.length > 0) {
    blocks.push(sectionHeading(t('home.advanced.result.visibility.competitors') as string, '#ec4899'));
    blocks.push(
      dataTable(
        [
          t('result.advancedPdf.compare.domain', { defaultValue: 'Domain' }) as string,
          t('result.advancedPdf.visibility.mentions', { defaultValue: 'Mentions' }) as string,
        ],
        data.top_competitors.slice(0, 10).map((c) => [
          { value: c.domain, align: 'left' as const, bold: true },
          { value: String(c.mentions), align: 'center' as const },
        ]),
      ),
    );
  }

  // Framings
  if (Object.keys(data.framings).length > 0) {
    blocks.push(sectionHeading(t('home.advanced.result.visibility.framings') as string, '#f59e0b'));
    blocks.push(
      kvTable(
        Object.entries(data.framings).map(([k, v]) => ({ k, v: String(v) })),
      ),
    );
  }

  // Content gaps — parsed `[engine] "query" (group)` strings into a 3-column
  // table so CJK queries wrap inside their cell rather than overflow as one
  // long bullet line.
  if (data.content_gaps.length > 0) {
    blocks.push(sectionHeading(t('home.advanced.result.visibility.contentGaps') as string, '#8b5cf6'));
    const gapPattern = /^\[([^\]]+)\]\s*"(.+)"\s*\(([^)]+)\)\s*$/;
    const rows: DataRow[] = data.content_gaps.map((g) => {
      const m = gapPattern.exec(g);
      if (!m) {
        return [{ value: '—', align: 'left' as const }, { value: g, align: 'left' as const }, { value: '—', align: 'left' as const }];
      }
      return [
        { value: m[1], align: 'left' as const, bold: true },
        { value: m[2], align: 'left' as const },
        { value: m[3], align: 'left' as const, color: '#64748b' },
      ];
    });
    blocks.push(
      dataTable(
        [
          t('result.advancedPdf.visibility.engine', { defaultValue: 'Engine' }) as string,
          t('result.advancedPdf.visibility.gapQuery', { defaultValue: 'Query' }) as string,
          t('result.advancedPdf.visibility.gapGroup', { defaultValue: 'Group' }) as string,
        ],
        rows,
      ),
    );
  }

  return blocks;
};

// ---------- entity ----------

// ---------- Entity PDF helpers ----------

const entityPill = (label: string, found: boolean): string => {
  const bg = found ? 'rgba(16,185,129,0.1)' : 'rgba(244,63,94,0.1)';
  const fg = found ? '#059669' : '#e11d48';
  const border = found ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)';
  const icon = found ? '✓' : '✕';
  return `<span style="display:inline-block;font-size:10px;font-weight:600;padding:3px 8px;border-radius:99px;background:${bg};color:${fg};border:1px solid ${border};margin:2px 3px 2px 0;white-space:nowrap;">${icon} ${escapeHtml(label)}</span>`;
};

const entityBadge = (label: string, bg: string, fg: string, border: string): string =>
  `<span style="display:inline-block;font-size:9px;font-weight:600;padding:2px 7px;border-radius:99px;background:${bg};color:${fg};border:1px solid ${border};margin:0 3px;white-space:nowrap;">${escapeHtml(label)}</span>`;

const entityScoreBar = (label: string, value: number, max: number): string => {
  const pct = Math.round((value / max) * 100);
  const barColor = pct >= 70 ? '#22c55e' : pct >= 40 ? '#eab308' : '#ef4444';
  return (
    `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;">` +
    `<div style="width:110px;font-size:10px;color:#475569;flex-shrink:0;">${escapeHtml(label)}</div>` +
    `<div style="flex:1;height:6px;background:#f1f5f9;border-radius:3px;overflow:hidden;">` +
    `<div style="width:${pct}%;height:100%;background:${barColor};border-radius:3px;"></div>` +
    `</div>` +
    `<div style="width:40px;text-align:right;font-size:10px;font-weight:700;color:${barColor};">${value}/${max}</div>` +
    `</div>`
  );
};

const entityKgRow = (label: string, found: boolean, statusLabel: string): string => {
  const iconBg = found ? 'rgba(16,185,129,0.12)' : 'rgba(244,63,94,0.08)';
  const iconBorder = found ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)';
  const iconColor = found ? '#059669' : '#e11d48';
  const icon = found
    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${iconColor}" stroke-width="2.5" stroke-linecap="round"><path d="M20 6L9 17l-5-5"/></svg>`
    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${iconColor}" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
  const statusColor = found ? '#059669' : '#e11d48';
  return (
    `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-radius:10px;background:#f8fafc;border:1px solid #e2e8f0;margin-bottom:6px;">` +
    `<div style="display:flex;align-items:center;gap:10px;">` +
    `<div style="width:28px;height:28px;border-radius:7px;display:flex;align-items:center;justify-content:center;background:${iconBg};border:1px solid ${iconBorder};">${icon}</div>` +
    `<span style="font-size:11px;font-weight:600;color:#0f172a;">${escapeHtml(label)}</span>` +
    `</div>` +
    `<span style="font-size:9px;font-weight:700;color:${statusColor};text-transform:uppercase;letter-spacing:0.08em;">${escapeHtml(statusLabel)}</span>` +
    `</div>`
  );
};

const buildEntityBlocks = (data: EntityAuditResponse, t: TFunction, _language: string): string[] => {
  const blocks: string[] = [];
  const esc = escapeHtml;
  const totalPlatforms = data.platforms.found.length + data.platforms.not_found.length;
  const foundLabel = t('home.advanced.result.entity.found', { defaultValue: 'Found' }) as string;
  const missingLabel = t('home.advanced.result.entity.missing', { defaultValue: 'Missing' }) as string;

  // ── 1. Score hero card ────────────────────────────────────
  // Score ring SVG
  const pct = data.percent;
  const ringColor = pct >= 70 ? '#22c55e' : pct >= 40 ? '#eab308' : '#ef4444';
  const circumference = 2 * Math.PI * 40;
  const dashOffset = circumference * (1 - pct / 100);
  const scoreRing =
    `<svg width="80" height="80" viewBox="0 0 100 100" style="flex-shrink:0;">` +
    `<circle cx="50" cy="50" r="40" fill="none" stroke="#f1f5f9" stroke-width="7"/>` +
    `<circle cx="50" cy="50" r="40" fill="none" stroke="${ringColor}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${circumference}" stroke-dashoffset="${dashOffset}" transform="rotate(-90 50 50)"/>` +
    `<text x="50" y="46" text-anchor="middle" font-size="22" font-weight="800" fill="#0f172a">${data.total_score}</text>` +
    `<text x="50" y="62" text-anchor="middle" font-size="9" fill="#94a3b8">/${data.max_score}</text>` +
    `</svg>`;

  blocks.push(
    blockWrapOpen('padding:16px 18px;border:1px solid #e2e8f0;border-radius:14px;') +
    `<div style="display:flex;align-items:center;gap:16px;">` +
    scoreRing +
    `<div style="flex:1;min-width:0;">` +
    `<div style="font-size:9px;color:#94a3b8;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:2px;">${esc(t('home.advanced.cards.entity.title', { defaultValue: 'Entity GEO Audit' }))}</div>` +
    `<div style="font-size:18px;font-weight:800;color:#0f172a;margin-bottom:4px;">${esc(data.entity)}</div>` +
    `<div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;">` +
    entityBadge(data.entity_type.toUpperCase(), 'rgba(236,72,153,0.1)', '#ec4899', 'rgba(236,72,153,0.3)') +
    entityBadge(`${t('home.advanced.result.entity.gradePrefix', { defaultValue: 'Grade' })} ${data.grade}`, 'linear-gradient(135deg,#f59e0b,#ec4899)', '#fff', 'transparent') +
    entityBadge(`${pct}%`, '#f8fafc', '#64748b', '#e2e8f0') +
    `</div>` +
    `</div>` +
    `</div>` +
    blockWrapClose,
  );

  // ── 2. Score bars ─────────────────────────────────────────
  const SLUG: Record<string, string> = {
    'Entity Recognition': 'entityRecognition', 'Entity Clarity': 'entityClarity',
    'Category Association': 'categoryAssociation', 'Competitive Position': 'competitivePosition',
    'Sentiment & Framing': 'sentimentFraming', 'Content Gap': 'contentGap',
    'Knowledge Graph': 'knowledgeGraph', 'Platform Footprint': 'platformFootprint',
  };
  const bars = Object.entries(data.scores)
    .map(([name, v]) => {
      const slug = SLUG[name];
      const label = slug
        ? t(`home.advanced.result.entity.scoreLabels.${slug}`, { defaultValue: name }) as string
        : name;
      return entityScoreBar(label, v, 20);
    })
    .join('');
  blocks.push(
    blockWrapOpen('padding:14px 18px;border:1px solid #e2e8f0;border-radius:14px;') +
    bars +
    blockWrapClose,
  );

  // ── 3. Two-column: Knowledge Graph + Platforms ────────────
  // Knowledge graph column
  const kgItems = [
    { label: 'Wikipedia', found: data.knowledge_graph.wikipedia },
    { label: 'Wikidata', found: data.knowledge_graph.wikidata },
    { label: 'Google KG', found: data.knowledge_graph.google_kg },
    { label: 'Baidu Baike (百度百科)', found: !!data.knowledge_graph.baidu_baike },
  ];
  const kgHtml = kgItems.map((kg) => entityKgRow(kg.label, kg.found, kg.found ? foundLabel : missingLabel)).join('');

  // Platforms column
  const platTags = [
    ...data.platforms.found.map((p) => entityPill(p, true)),
    ...data.platforms.not_found.map((p) => entityPill(p, false)),
  ].join('');

  blocks.push(
    blockWrapOpen('padding:0;display:flex;gap:12px;') +
    // Left: KG
    `<div style="flex:1;border:1px solid #e2e8f0;border-radius:14px;padding:14px 14px 8px 14px;">` +
    `<div style="font-size:11px;font-weight:800;color:#0f172a;margin-bottom:10px;padding-left:2px;border-left:3px solid #ef4444;">&nbsp;${esc(t('home.advanced.result.entity.kgTitle', { defaultValue: 'Knowledge Graph' }))}</div>` +
    kgHtml +
    `</div>` +
    // Right: Platforms
    `<div style="flex:1;border:1px solid #e2e8f0;border-radius:14px;padding:14px;">` +
    `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">` +
    `<div style="font-size:11px;font-weight:800;color:#0f172a;padding-left:2px;border-left:3px solid #ef4444;">&nbsp;${esc(t('home.advanced.result.entity.platforms', { defaultValue: 'Platform Coverage' }))}</div>` +
    `<span style="font-size:10px;color:#94a3b8;">${data.platforms.found.length}/${totalPlatforms}</span>` +
    `</div>` +
    `<div style="line-height:1.8;">${platTags}</div>` +
    `</div>` +
    blockWrapClose,
  );

  // ── 4. Two-column: AI怎么看你 + Content Gaps ──────────────
  // Sentiment column — overall only (no per-engine breakdown)
  const overallSentiment = data.per_engine
    ? Object.values(data.per_engine).find(d => d.recognized)?.sentiment || data.sentiment
    : data.sentiment;
  const overallFraming = data.per_engine
    ? Object.values(data.per_engine).find(d => d.recognized)?.framing || data.best_framing
    : data.best_framing;
  const sentimentHtml =
    `<div style="display:flex;align-items:center;justify-content:space-between;padding:7px 10px;border-radius:8px;background:#f8fafc;border:1px solid #e2e8f0;margin-bottom:8px;">` +
    `<span style="font-size:9px;color:#64748b;font-weight:600;">${esc(t('home.advanced.result.entity.overallSentiment', { defaultValue: 'Overall Sentiment' }))}</span>` +
    `<span style="font-size:12px;font-weight:700;color:#0f172a;">${esc(t(`home.advanced.result.entity.sentiments.${overallSentiment}`, { defaultValue: overallSentiment || 'unknown' }) as string)}</span>` +
    `</div>` +
    `<div style="display:flex;align-items:center;justify-content:space-between;padding:7px 10px;border-radius:8px;background:#f8fafc;border:1px solid #e2e8f0;margin-bottom:8px;">` +
    `<span style="font-size:9px;color:#64748b;font-weight:600;">${esc(t('home.advanced.result.entity.bestFraming', { defaultValue: 'Best Framing' }))}</span>` +
    `<span style="font-size:12px;font-weight:700;color:#0f172a;">${esc(t(`home.advanced.result.entity.framings.${overallFraming}`, { defaultValue: (overallFraming || 'unknown').replace('_', ' ') }) as string)}</span>` +
    `</div>` +
    `<div style="display:flex;align-items:center;justify-content:space-between;padding:7px 10px;border-radius:8px;background:#f8fafc;border:1px solid #e2e8f0;margin-bottom:8px;">` +
    `<span style="font-size:9px;color:#64748b;font-weight:600;">${esc(t('home.advanced.result.entity.recognitionRate', { defaultValue: 'Recognition Rate' }))}</span>` +
    `<span style="font-size:12px;font-weight:800;color:#0f172a;">${Math.round(data.recognition_rate)}%</span>` +
    `</div>`;

  // Content gaps column
  let gapsHtml = '';
  if (data.content_gaps.length > 0) {
    gapsHtml = data.content_gaps
      .map(
        (g) =>
          `<div style="padding:6px 10px;border-radius:8px;background:rgba(244,63,94,0.05);border:1px solid rgba(244,63,94,0.2);margin-bottom:5px;">` +
          `<span style="font-size:10px;color:#e11d48;">· ${esc(g)}</span>` +
          `</div>`,
      )
      .join('');
  } else {
    gapsHtml =
      `<div style="display:flex;align-items:center;gap:6px;padding:8px;color:#059669;font-size:11px;">` +
      `<span>✓</span><span>${esc(t('home.advanced.result.entity.noGaps', { defaultValue: 'No gaps found' }))}</span>` +
      `</div>`;
  }

  blocks.push(
    blockWrapOpen('padding:0;display:flex;gap:12px;') +
    // Left: Sentiment
    `<div style="flex:1;border:1px solid #e2e8f0;border-radius:14px;padding:14px 14px 10px 14px;">` +
    `<div style="font-size:11px;font-weight:800;color:#0f172a;margin-bottom:10px;padding-left:2px;border-left:3px solid #ef4444;">&nbsp;${esc(t('home.advanced.result.entity.sentimentTitle', { defaultValue: 'AI Sentiment' }))}</div>` +
    sentimentHtml +
    `</div>` +
    // Right: Content Gaps
    `<div style="flex:1;border:1px solid #e2e8f0;border-radius:14px;padding:14px;">` +
    `<div style="font-size:11px;font-weight:800;color:#0f172a;margin-bottom:10px;padding-left:2px;border-left:3px solid #ef4444;">&nbsp;${esc(t('home.advanced.result.entity.contentGaps', { defaultValue: 'Content Gaps' }))}</div>` +
    gapsHtml +
    `</div>` +
    blockWrapClose,
  );

  return blocks;
};

// ---------- aeo ----------

const buildAeoBlocks = (data: AeoVisibilityResponse, t: TFunction, language: string): string[] => {
  const blocks: string[] = [];
  const generatedAt = new Date().toLocaleString(localeFor(language));

  blocks.push(
    coverBlock({
      badge: t('home.advanced.cards.aeo.title', { defaultValue: 'AEO Visibility Audit' }) as string,
      title: t('home.advanced.result.aeo.title', { defaultValue: 'AEO Score' }) as string,
      subtitle: t('home.advanced.cards.aeo.desc', { defaultValue: '' }) as string,
      rows: [
        { label: t('result.pdfReport.targetSite') as string, value: data.url },
        { label: t('result.advancedPdf.domain', { defaultValue: 'Domain' }) as string, value: data.domain },
        { label: t('result.pdfReport.generatedAt') as string, value: generatedAt },
      ],
      accent: '#0ea5e9',
    }),
  );

  const pct = (data.score / Math.max(1, data.max_score)) * 100;
  blocks.push(
    scoreHero({
      scoreLabel: t('home.advanced.result.aeo.overall', { defaultValue: 'Overall AEO Score' }) as string,
      scoreValue: fmtScore(data.score, data.max_score),
      scoreSuffix: fmtPercent(pct),
      grade: data.grade,
      rightStats: [
        {
          label: t('home.advanced.result.aeo.pageScores', { defaultValue: 'Per-Page AEO Scores' }) as string,
          value: data.page_results.length,
          tone: 'neutral',
        },
        {
          label: t('home.advanced.result.aeo.priorities', { defaultValue: 'Priority Improvements' }) as string,
          value: data.priority_improvements.length,
          tone: data.priority_improvements.length === 0 ? 'good' : 'warn',
        },
      ],
    }),
  );

  // Category breakdown
  blocks.push(sectionHeading(t('home.advanced.result.aeo.categoryBreakdown', { defaultValue: 'Category Breakdown' }) as string, '#0ea5e9'));
  const catEntries = Object.entries(data.categories);
  blocks.push(
    dataTable(
      [
        t('home.advanced.result.compare.category', { defaultValue: 'Category' }) as string,
        t('result.advancedPdf.compare.score', { defaultValue: 'Score' }) as string,
        '%',
      ],
      catEntries.map(([cat, { earned, max }]) => {
        const p = max > 0 ? (earned / max) * 100 : 0;
        return [
          { value: cat, align: 'left' as const, bold: true },
          { value: fmtScore(earned, max), align: 'center' as const },
          { value: fmtPercent(p), align: 'center' as const, color: p >= 75 ? '#166534' : p >= 50 ? '#92400e' : '#991b1b', bold: true },
        ];
      }),
    ),
  );

  // Per-page scores
  if (data.page_results.length > 0) {
    blocks.push(sectionHeading(t('home.advanced.result.aeo.pageScores', { defaultValue: 'Per-Page AEO Scores' }) as string, '#8b5cf6'));
    blocks.push(
      dataTable(
        [
          t('home.advanced.result.aeo.pagePath', { defaultValue: 'Page' }) as string,
          t('home.advanced.result.aeo.pageScore', { defaultValue: 'Score' }) as string,
          t('home.advanced.result.aeo.weakest', { defaultValue: 'Weakest Signal' }) as string,
        ],
        data.page_results.map((p) => [
          { value: p.path, align: 'left' as const, bold: true },
          { value: String(p.score), align: 'center' as const, color: p.score >= 75 ? '#166534' : p.score >= 50 ? '#92400e' : '#991b1b', bold: true },
          { value: p.weakest_signal || '—', align: 'left' as const },
        ]),
      ),
    );
  }

  // Priority improvements
  if (data.priority_improvements.length > 0) {
    blocks.push(sectionHeading(t('home.advanced.result.aeo.priorities', { defaultValue: 'Priority Improvements' }) as string, '#f59e0b'));
    blocks.push(
      callout(t('home.advanced.result.aeo.prioritiesHint', { defaultValue: 'Categories scoring below 50% — focus here first.' }) as string, 'warn'),
    );
    blocks.push(
      bulletList(
        t('home.advanced.result.aeo.priorities', { defaultValue: 'Priority Improvements' }) as string,
        data.priority_improvements.map((pi) => `${pi.category} — ${fmtPercent(pi.percent)}`),
      ),
    );
  }

  return blocks;
};

// ---------- Dispatcher ----------

interface ModeArgsMap {
  aeo: AeoVisibilityResponse;
  compare: CompareResponse;
  crawlTest: CrawlTestResponse;
  authority: AuthorityAuditResponse;
  citation: CitationCheckResponse;
  visibility: AiVisibilityResponse;
  entity: EntityAuditResponse;
}

export interface ExportAdvancedArgs<M extends AdvancedMode> {
  mode: M;
  data: ModeArgsMap[M];
  t: TFunction;
  language: string;
}

const buildBlocksFor = <M extends AdvancedMode>(args: ExportAdvancedArgs<M>): string[] => {
  switch (args.mode) {
    case 'aeo':
      return buildAeoBlocks(args.data as AeoVisibilityResponse, args.t, args.language);
    case 'compare':
      return buildCompareBlocks(args.data as CompareResponse, args.t, args.language);
    case 'crawlTest':
      return buildCrawlTestBlocks(args.data as CrawlTestResponse, args.t, args.language);
    case 'authority':
      return buildAuthorityBlocks(args.data as AuthorityAuditResponse, args.t, args.language);
    case 'citation':
      return buildCitationBlocks(args.data as CitationCheckResponse, args.t, args.language);
    case 'visibility':
      return buildVisibilityBlocks(args.data as AiVisibilityResponse, args.t, args.language);
    case 'entity':
      return buildEntityBlocks(args.data as EntityAuditResponse, args.t, args.language);
  }
  return [];
};

// Pick a header-right text + filename subject from each mode's data.
const headerSubjectFor = <M extends AdvancedMode>(args: ExportAdvancedArgs<M>): { headerRight: string; filenameSubject: string } => {
  const { mode, data, t } = args;
  const labelSite = t('result.pdfReport.headerSite') as string;
  switch (mode) {
    case 'compare': {
      const d = data as CompareResponse;
      const winner = d.winner?.domain || d.results[0]?.domain || 'compare';
      return { headerRight: `${labelSite}: ${d.urls.length} URLs`, filenameSubject: winner };
    }
    case 'aeo':
    case 'crawlTest':
    case 'authority':
    case 'citation':
    case 'visibility': {
      const d = data as { url: string; domain?: string; brand?: string };
      return { headerRight: `${labelSite}: ${d.url || ''}`, filenameSubject: d.domain || d.brand || d.url || mode };
    }
    case 'entity': {
      const d = data as EntityAuditResponse;
      return { headerRight: `${t('result.advancedPdf.entity.name', { defaultValue: 'Entity' }) as string}: ${d.entity}`, filenameSubject: d.entity };
    }
  }
  return { headerRight: labelSite, filenameSubject: mode };
};

export async function exportAdvancedPdfReport<M extends AdvancedMode>(
  args: ExportAdvancedArgs<M>,
): Promise<void> {
  const blocks = buildBlocksFor(args);
  const { headerRight, filenameSubject } = headerSubjectFor(args);
  const fileName = `geo-${args.mode}-${safeFile(filenameSubject)}-${todayStamp()}.pdf`;
  await composeAndSavePdf(
    blocks,
    { rightHeaderText: headerRight, t: args.t },
    fileName,
  );
}
