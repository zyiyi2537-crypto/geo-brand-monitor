import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { parseMetaTags, type MetaItemStatus, type MetaItem } from '../lib/parseChecks';
import type { CheckResult } from '../../../types/geo';
import { Tooltip } from '../../Tooltip';

interface Props {
  checks: CheckResult[];
}

// Labels are code-facing tags (kept in English because they ARE the HTML tag
// names the developer sees); icons are presentation-only. The user-visible
// `help` text lives in i18n at result.visuals.meta.items.<key>.help.
const ITEM_LABELS: Record<MetaItem['key'], { label: string; icon: ReactNode }> = {
  title: {
    label: '<title>',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h10" />
      </svg>
    ),
  },
  description: {
    label: 'description',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  canonical: {
    label: 'canonical',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
      </svg>
    ),
  },
  og: {
    label: 'Open Graph',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    ),
  },
  lang: {
    label: 'html[lang]',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
      </svg>
    ),
  },
  hreflang: {
    label: 'hreflang',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
};

const STATUS_THEME: Record<MetaItemStatus, { border: string; bg: string; text: string; dot: string }> = {
  PASS: { border: 'border-emerald-500/40', bg: 'bg-emerald-500/10', text: 'text-emerald-600', dot: 'bg-emerald-500' },
  WARN: { border: 'border-amber-500/40', bg: 'bg-amber-500/10', text: 'text-amber-600', dot: 'bg-amber-500' },
  FAIL: { border: 'border-rose-500/40', bg: 'bg-rose-500/10', text: 'text-rose-600', dot: 'bg-rose-500' },
  INFO: { border: 'border-cyan-500/30', bg: 'bg-cyan-500/10', text: 'text-cyan-600', dot: 'bg-cyan-500' },
  UNKNOWN: { border: 'border-border', bg: 'bg-tertiary', text: 'text-muted', dot: 'bg-muted' },
};

export function MetaTagsGrid({ checks }: Props) {
  const { t } = useTranslation();
  const parsed = parseMetaTags(checks);
  if (!parsed) return null;

  const passCount = parsed.items.filter((i) => i.status === 'PASS').length;
  const totalCount = parsed.items.length;

  return (
    <div className="bg-card border border-border rounded-xl p-4 sm:p-5 relative overflow-hidden">
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-purple-400/50 to-transparent" />

      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg gradient-bg flex items-center justify-center shadow-glow">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-xs font-semibold text-primary">
              {t('result.visuals.meta.title')}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-muted">
              {t('result.visuals.meta.subtitle')}
            </span>
          </div>
        </div>
        <span className="text-[10px] font-mono text-muted">
          {t('result.visuals.meta.passCount', { pass: passCount, total: totalCount })}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
        {parsed.items.map((item) => {
          const label = ITEM_LABELS[item.key];
          const theme = STATUS_THEME[item.status];
          const help = t(`result.visuals.meta.items.${item.key}.help`);
          return (
            <Tooltip key={item.key} content={help}>
              <div
                className={`flex flex-col gap-1.5 px-3 py-2.5 rounded-lg border cursor-help ${theme.border} ${theme.bg}`}
              >
                <div className="flex items-center justify-between">
                  <div className={`flex items-center gap-1.5 ${theme.text}`}>
                    {label.icon}
                    <span className="text-[11px] font-semibold font-mono">{label.label}</span>
                  </div>
                  <span className={`w-1.5 h-1.5 rounded-full ${theme.dot}`} />
                </div>
                <p className="text-[10px] text-secondary leading-snug line-clamp-2 min-h-[1.5em]">
                  {item.status === 'UNKNOWN' ? '—' : item.detail || help}
                </p>
              </div>
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}
