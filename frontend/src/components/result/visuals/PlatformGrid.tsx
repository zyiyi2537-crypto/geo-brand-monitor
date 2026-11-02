import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { parseCrossPlatform, type PlatformState } from '../lib/parseChecks';
import type { CheckResult } from '../../../types/geo';

interface Props {
  checks: CheckResult[];
  variant?: 'cross-platform' | 'social';
}

// Minimal mono-line glyphs — no external icon libs. Each platform gets a
// distinctive shape so the grid is scannable at a glance.
const PLATFORM_GLYPH: Record<string, ReactNode> = {
  'X / Twitter': (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  ),
  LinkedIn: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.268 2.37 4.268 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.063 2.063 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  ),
  YouTube: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M23.498 6.186a3.016 3.016 0 00-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 00.502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 002.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 002.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
    </svg>
  ),
  GitHub: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </svg>
  ),
  Reddit: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M12 0A12 12 0 000 12a12 12 0 0012 12 12 12 0 0012-12A12 12 0 0012 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 01-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 01.042.52c0 2.694-3.13 4.87-6.991 4.87-3.862 0-6.99-2.176-6.99-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 014.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 01.14-.197.35.35 0 01.238-.042l2.906.617a1.214 1.214 0 011.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 00-.231.094.33.33 0 000 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 00.029-.463.33.33 0 00-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 00-.232-.095z" />
    </svg>
  ),
  Facebook: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 011.141.195v3.325a8.623 8.623 0 00-.653-.036 26.805 26.805 0 00-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 00-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647z" />
    </svg>
  ),
  Instagram: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
    </svg>
  ),
  Medium: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M13.54 12a6.8 6.8 0 01-6.77 6.82A6.8 6.8 0 010 12a6.8 6.8 0 016.77-6.82A6.8 6.8 0 0113.54 12zM20.96 12c0 3.54-1.51 6.42-3.38 6.42-1.87 0-3.39-2.88-3.39-6.42s1.52-6.42 3.39-6.42 3.38 2.88 3.38 6.42M24 12c0 3.17-.53 5.75-1.19 5.75-.66 0-1.19-2.58-1.19-5.75s.53-5.75 1.19-5.75C23.47 6.25 24 8.83 24 12z" />
    </svg>
  ),
  TikTok: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-5.2 1.74 2.89 2.89 0 012.31-4.64 2.93 2.93 0 01.88.13V9.4a6.84 6.84 0 00-1-.05A6.33 6.33 0 005.8 20.1a6.34 6.34 0 0010.86-4.43v-7a8.16 8.16 0 004.77 1.52v-3.4a4.85 4.85 0 01-1-.1z" />
    </svg>
  ),
  Quora: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M12.738 18.701c-.831-1.635-1.805-3.287-3.708-3.287-.362 0-.727.061-1.059.209l-.646-1.289c.786-.67 2.058-1.196 3.708-1.196 2.564 0 3.878 1.23 4.93 2.820.62-1.305.917-3.061.917-5.199 0-5.35-1.669-8.074-5.061-8.074-3.343 0-5.012 2.725-5.012 8.074 0 5.321 1.669 8.022 5.012 8.022.307 0 .598-.013.919-.081zm1.048 2.129c-.649.162-1.328.25-1.984.25-5.518 0-10.164-4.48-10.164-10.32 0-5.891 4.646-10.37 10.164-10.37 5.632 0 10.227 4.45 10.227 10.37 0 3.309-1.441 6.107-3.677 7.938.724 1.089 1.459 1.811 2.505 1.811 1.137 0 1.584-.867 1.668-1.55h1.474c.084.898-.359 4.941-4.837 4.941-2.721 0-4.172-1.581-5.376-3.07z" />
    </svg>
  ),
};

const STATE_THEME: Record<PlatformState, { ring: string; text: string; bg: string }> = {
  linked: {
    ring: 'border-emerald-500/50 ring-1 ring-emerald-400/30',
    text: 'text-emerald-600',
    bg: 'bg-emerald-500/10',
  },
  probed: {
    ring: 'border-cyan-500/50 ring-1 ring-cyan-400/30',
    text: 'text-cyan-600',
    bg: 'bg-cyan-500/10',
  },
  notFound: {
    ring: 'border-border',
    text: 'text-muted',
    bg: 'bg-tertiary',
  },
  unknown: {
    ring: 'border-border',
    text: 'text-muted',
    bg: 'bg-tertiary',
  },
};

const AI_TRAINING_MAP: Record<string, string> = {
  'X / Twitter': 'ChatGPT · Grok · Perplexity',
  Reddit: 'ChatGPT · Claude · Gemini · Perplexity',
  YouTube: 'Gemini · Perplexity',
  LinkedIn: 'Bing Copilot · Perplexity',
  GitHub: 'Copilot · ChatGPT · Claude',
  Medium: 'ChatGPT · Claude · Perplexity',
  Facebook: 'Meta AI',
  Instagram: 'Meta AI',
  TikTok: 'ByteDance AI',
  Quora: 'ChatGPT · Perplexity',
};

export function PlatformGrid({ checks, variant = 'cross-platform' }: Props) {
  const { t } = useTranslation();
  const parsed = parseCrossPlatform(checks);
  if (!parsed) return null;

  const header =
    variant === 'social'
      ? t('result.visuals.platform.titleSocial')
      : t('result.visuals.platform.titleCross');

  return (
    <div className="bg-card border border-border rounded-xl p-4 sm:p-5 relative overflow-hidden">
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-pink-400/50 to-transparent" />

      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg gradient-bg flex items-center justify-center shadow-glow">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-xs font-semibold text-primary">{header}</span>
            <span className="text-[10px] uppercase tracking-wider text-muted">
              {t('result.visuals.platform.subtitle')}
            </span>
          </div>
        </div>
        <span className="text-[10px] font-mono text-muted">
          {parsed.foundCount}/{parsed.totalCount}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        {parsed.platforms.map((p) => {
          const theme = STATE_THEME[p.state];
          const glyph = PLATFORM_GLYPH[p.name] ?? (
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
          );
          const isFound = p.state === 'linked' || p.state === 'probed';
          const trainingHint = isFound ? AI_TRAINING_MAP[p.name] : undefined;
          return (
            <a
              key={p.name}
              href={p.url || undefined}
              target={p.url ? '_blank' : undefined}
              rel={p.url ? 'noopener noreferrer' : undefined}
              className={`flex flex-col gap-1 px-2.5 py-2 rounded-lg border ${theme.ring} ${theme.bg} transition-all ${
                p.url ? 'hover:-translate-y-0.5 hover:shadow-glow cursor-pointer' : 'cursor-default'
              }`}
              title={p.url || t('result.visuals.platform.notDetected', { name: p.name })}
            >
              <div className="flex items-center justify-between">
                <span className={theme.text}>{glyph}</span>
                {isFound && (
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" className="h-3 w-3 text-emerald-600" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </div>
              <span className="text-[10px] font-medium text-primary truncate" title={p.name}>
                {p.name}
              </span>
              {trainingHint && (
                <span className="text-[8px] text-muted leading-tight truncate" title={trainingHint}>
                  {trainingHint}
                </span>
              )}
            </a>
          );
        })}
      </div>
    </div>
  );
}
