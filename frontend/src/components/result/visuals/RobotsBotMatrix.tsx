import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { parseRobotsTxt, type BotState } from '../lib/parseChecks';
import type { CheckResult } from '../../../types/geo';

interface Props {
  checks: CheckResult[];
}

const STATE_THEME: Record<BotState, { i18nKey: string; ring: string; text: string; bg: string; icon: ReactNode }> = {
  allowed: {
    i18nKey: 'result.visuals.robots.legend.allowed',
    ring: 'ring-emerald-400/50 border-emerald-500/40',
    text: 'text-emerald-600',
    bg: 'bg-emerald-500/10',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" className="h-3.5 w-3.5" strokeWidth={3}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    ),
  },
  blocked: {
    i18nKey: 'result.visuals.robots.legend.blocked',
    ring: 'ring-rose-500/50 border-rose-500/40',
    text: 'text-rose-600',
    bg: 'bg-rose-500/10',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" className="h-3.5 w-3.5" strokeWidth={3}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    ),
  },
  inherited: {
    i18nKey: 'result.visuals.robots.legend.inherited',
    ring: 'ring-cyan-400/30 border-cyan-500/30',
    text: 'text-cyan-600',
    bg: 'bg-cyan-500/10',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" className="h-3.5 w-3.5" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  unknown: {
    i18nKey: 'result.visuals.robots.legend.unknown',
    ring: 'border-border',
    text: 'text-muted',
    bg: 'bg-tertiary',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" className="h-3.5 w-3.5" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093M12 17h.01" />
      </svg>
    ),
  },
};

export function RobotsBotMatrix({ checks }: Props) {
  const { t } = useTranslation();
  const parsed = parseRobotsTxt(checks);
  if (!parsed) return null;

  const allowedCount = parsed.bots.filter((b) => b.state === 'allowed').length;
  const blockedCount = parsed.bots.filter((b) => b.state === 'blocked').length;
  const totalCount = parsed.bots.length;

  const subtitleParts = [
    parsed.fileFound
      ? t('result.visuals.robots.filePresent')
      : t('result.visuals.robots.fileMissing'),
  ];
  if (parsed.hasSitemapRef === true) subtitleParts.push(t('result.visuals.robots.sitemapRef'));
  if (parsed.hasSitemapRef === false) subtitleParts.push(t('result.visuals.robots.noSitemapRef'));

  // When robots.txt is missing there is nothing to classify — the bot grid,
  // counts, and legend would all be noise (all 15 bots as "unknown" is a
  // misleading label). Render the header alone so the user sees the missing
  // state clearly without the ambiguous downstream rows.
  if (!parsed.fileFound) {
    return (
      <div className="bg-card border border-border rounded-xl p-4 sm:p-5 overflow-hidden relative">
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-rose-400/50 to-transparent" />
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-rose-500/15 border border-rose-500/30 flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-rose-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-.633-1.964-.633-2.732 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-xs font-semibold text-primary">
              {t('result.visuals.robots.title')}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-rose-600">
              {t('result.visuals.robots.fileMissing')}
            </span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-card border border-border rounded-xl p-4 sm:p-5 overflow-hidden relative">
      {/* Gradient accent line */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-400/50 to-transparent" />

      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg gradient-bg flex items-center justify-center shadow-glow">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-xs font-semibold text-primary">
              {t('result.visuals.robots.title')}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-muted">
              {subtitleParts.join(' · ')}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono">
          <span className="text-emerald-600">✓ {allowedCount}</span>
          <span className="text-rose-600">✕ {blockedCount}</span>
          <span className="text-muted">
            {allowedCount}/{totalCount}
          </span>
        </div>
      </div>

      {parsed.wildcardBlocksAll && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-600">
          ⚠ {t('result.visuals.robots.wildcardWarning')}
        </div>
      )}

      {/* Bot grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        {parsed.bots.map((bot) => {
          const theme = STATE_THEME[bot.state];
          const label = t(theme.i18nKey);
          return (
            <div
              key={bot.name}
              className={`flex items-center gap-2 px-2.5 py-2 rounded-lg border ${theme.ring} ${theme.bg} transition-colors`}
              title={label}
            >
              <span className={`flex items-center justify-center w-5 h-5 rounded ${theme.bg} ${theme.text}`}>
                {theme.icon}
              </span>
              <span className="text-[11px] font-medium text-primary truncate" title={bot.name}>
                {bot.name}
              </span>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted">
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> {t('result.visuals.robots.legend.allowed')}
        </span>
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-rose-500" /> {t('result.visuals.robots.legend.blocked')}
        </span>
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-muted" /> {t('result.visuals.robots.legend.unknown')}
        </span>
      </div>
    </div>
  );
}
